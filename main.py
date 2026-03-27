import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from walter.LLM_API import LLMAPI
from walter.config import (
    API_WALLET_PRIVATE_KEY,
    COIN,
    GENERAL_PUBLIC_KEY,
    HYPERLIQUID_URL,
    LLM_HISTORY_LENGTH,
    LLM_MODEL,
    OPENROUTER_API_KEY,
    SCHEDULER_INTERVAL_SECONDS,
    TOTAL_SESSION_HOURS,
)
from walter.dashboard import TradingDashboard, fmt_money, fmt_num
from walter.db_utils import (
    initialize_database,
    save_account_snapshot,
    save_market_snapshot,
    save_news_snapshot,
    save_order_attempt,
)
from walter.hyperliquid_API import (
    close_position,
    get_open_position_details,
    get_withdrawable_balance,
    place_order,
)
from walter.market_data import get_market_snapshot
from walter.news_aggregator import CryptoNewsAggregator
from walter.news_summarizer import get_summaries_from_news
from walter.web_dashboard import WebDashboardServer


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
    handlers=[
        logging.FileHandler("walter.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

interval = int(SCHEDULER_INTERVAL_SECONDS)
coin = str(COIN)
hyperliquid_url = str(HYPERLIQUID_URL)
general_public_key = str(GENERAL_PUBLIC_KEY)
api_wallet_private_key = str(API_WALLET_PRIVATE_KEY)
llm_model = LLM_MODEL
openrouter_key = OPENROUTER_API_KEY
history_length = int(LLM_HISTORY_LENGTH)
llm_api = LLMAPI(
    api_key=openrouter_key,
    model=llm_model,
    history_length=history_length,
)
total_session_hours = int(TOTAL_SESSION_HOURS)
total_cycles = (total_session_hours * 3600) // interval
initialize_database()

web_dashboard_enabled = os.getenv("WALTER_ENABLE_WEB_DASHBOARD", "1") != "0"
web_dashboard_host = os.getenv("WALTER_WEB_HOST", "localhost")
try:
    web_dashboard_port = int(os.getenv("WALTER_WEB_PORT", "8765"))
except ValueError:
    web_dashboard_port = 8765


def _persist_cycle(
    current_time: Any,
    account_snapshot: dict,
    market_snapshot: dict,
    major_titles: list[str],
    decision: Any,
    *,
    order_args: dict | None = None,
    order_placed: bool | None = None,
    decision_action_override: str | None = None,
) -> None:
    """Save all snapshots and the order attempt for a single loop iteration."""
    account_snapshot_id = save_account_snapshot(current_time, account_snapshot)
    market_snapshot_id = save_market_snapshot(market_snapshot, captured_at=current_time)
    news_snapshot_id = save_news_snapshot(major_titles, captured_at=current_time)
    save_order_attempt(
        created_at=current_time,
        coin=coin,
        is_buy=order_args["is_buy"] if order_args else False,
        size=order_args["size"] if order_args else None,
        leverage=order_args["leverage"] if order_args else None,
        tif=order_args["tif"] if order_args else None,
        decision_action=decision_action_override or decision.action,
        thinking=decision.thinking,
        market_snapshot_id=market_snapshot_id,
        news_snapshot_id=news_snapshot_id,
        account_snapshot_id=account_snapshot_id,
        order_payload=order_args,
        order_placed=order_placed,
    )


def main() -> None:
    logger.info("Scheduler running every %d seconds.", interval)
    web_dashboard: WebDashboardServer | None = None
    if web_dashboard_enabled:
        try:
            web_dashboard = WebDashboardServer(
                host=web_dashboard_host,
                port=web_dashboard_port,
            )
            web_dashboard.start()
            logger.info("Web dashboard available at %s", web_dashboard.url)
        except OSError as exc:
            logger.warning("Web dashboard disabled (bind failed): %s", exc)
            web_dashboard = None

    dashboard = TradingDashboard(coin, web_dashboard=web_dashboard)
    dashboard.add_event(f"Scheduler started (interval={interval}s)")
    if web_dashboard is not None:
        dashboard.add_event(f"Web dashboard: {web_dashboard.url}")
    dashboard.set_state(stage="initializing")
    logger.info("Scheduler initialized.")
    cycle = 0

    try:
        while True:
            try:
                cycle += 1
                current_time = datetime.now(timezone.utc)
                dashboard.set_state(
                    stage="collecting_news",
                    cycle=cycle,
                    current_time=current_time,
                    order_status="pending",
                )
                logger.info("--- Starting Cycle %d ---", cycle)
                logger.info("Collecting news and market data...")

                news = CryptoNewsAggregator.get_aggregated_news()
                summary = get_summaries_from_news(news)
                major_titles = [n.get("title", "") for n in summary.get("major_narratives", [])]
                dashboard.set_state(major_titles=major_titles, stage="collecting_market")
                dashboard.add_event(f"News processed ({len(major_titles)} major narratives)")
                logger.info("News processed: %d major narratives found.", len(major_titles))

                market_snapshot = get_market_snapshot(coin, interval, hyperliquid_url, 24)
                dashboard.set_state(market_snapshot=market_snapshot, stage="collecting_account")
                logger.info("Market data fetched. Current Price: $%.2f", market_snapshot.get("current_price", 0))

                account_snapshot = get_open_position_details(
                    hyperliquid_url, general_public_key
                )
                dashboard.set_state(account_snapshot=account_snapshot, stage="llm_decision")
                logger.info("Account data fetched. Requesting LLM decision...")

                decision = llm_api.decide_from_market(
                    market_snapshot, account_snapshot, major_titles,
                    current_cycle=cycle, total_cycles=total_cycles
                )
                dashboard.set_state(decision=decision, stage="decision_ready")
                dashboard.add_event(
                    f"Decision={decision.action.upper()} size={decision.size} lev={decision.leverage}"
                )
                logger.info(
                    "Decision Ready: %s | Size: %s | Lev: %s",
                    decision.action.upper(),
                    decision.size,
                    decision.leverage,
                )
                logger.info("LLM Thinking: %s", decision.thinking)

                if decision.action == "hold":
                    _persist_cycle(
                        current_time,
                        account_snapshot,
                        market_snapshot,
                        major_titles,
                        decision,
                        order_placed=None,
                    )
                    dashboard.set_state(
                        stage="cycle_complete",
                        order_status="hold_no_order",
                        required_margin=None,
                        available_balance=None,
                    )
                    dashboard.add_event("HOLD: no order placed", current_time)
                    logger.info("Action is HOLD. No order placed. Waiting for next cycle.")
                    time.sleep(interval)
                    continue

                if decision.action == "close":
                    dashboard.set_state(stage="closing_position", order_status="closing")
                    logger.info("Action is CLOSE. Attempting to close open position...")
                    closed = close_position(
                        hyperliquid_url,
                        api_wallet_private_key,
                        general_public_key,
                        coin,
                    )
                    _persist_cycle(
                        current_time,
                        account_snapshot,
                        market_snapshot,
                        major_titles,
                        decision,
                        order_placed=closed,
                    )
                    if closed:
                        dashboard.set_state(
                            stage="cycle_complete",
                            order_status="position_closed",
                            required_margin=None,
                            available_balance=None,
                        )
                        dashboard.add_event(f"CLOSE: {coin} position closed", current_time)
                        logger.info("Position closed successfully.")
                    else:
                        dashboard.set_state(
                            stage="cycle_complete",
                            order_status="close_failed_or_no_position",
                            required_margin=None,
                            available_balance=None,
                        )
                        dashboard.add_event("CLOSE: no position to close or failed", current_time)
                        logger.info("CLOSE failed or no position to close.")
                    time.sleep(interval)
                    continue

                order_args = {
                    "is_buy": decision.action == "buy",
                    "coin": coin,
                    "size": decision.size,
                    "leverage": decision.leverage,
                    "tif": decision.tif or "Ioc",
                }

                if (
                    decision.size is None
                    or decision.leverage is None
                    or decision.size <= 0
                    or decision.leverage <= 0
                ):
                    dashboard.set_state(
                        stage="cycle_complete",
                        order_status="invalid_decision_payload",
                        required_margin=None,
                        available_balance=None,
                    )
                    dashboard.add_event(
                        "Decision missing valid size/leverage; order skipped",
                        current_time,
                    )
                    _persist_cycle(
                        current_time,
                        account_snapshot,
                        market_snapshot,
                        major_titles,
                        decision,
                        order_args=order_args,
                        order_placed=False,
                        decision_action_override=f"{decision.action}_invalid_payload",
                    )
                    time.sleep(interval)
                    continue

                available = get_withdrawable_balance(account_snapshot)
                current_price = market_snapshot.get("current_price", 0)
                leverage = decision.leverage if decision.leverage else 1
                required_margin = (decision.size * current_price) / leverage

                # Auto-scale size down if margin exceeds available balance
                if available is not None and current_price > 0 and required_margin > available:
                    max_size = (available * 0.95 * leverage) / current_price
                    logger.info(
                        "Auto-scaling %s size from %.6f to %.6f (margin $%.2f > available $%.2f)",
                        decision.action.upper(),
                        decision.size,
                        max_size,
                        required_margin,
                        available,
                    )
                    order_args["size"] = max_size
                    required_margin = (max_size * current_price) / leverage
                    dashboard.add_event(
                        f"Size auto-scaled to {fmt_num(max_size, 5)} (balance limit)",
                        current_time,
                    )

                dashboard.set_state(
                    stage="risk_check",
                    required_margin=required_margin,
                    available_balance=available,
                )

                if available is None or required_margin > available or order_args["size"] <= 0:
                    available_str = f"${available:,.2f}" if available is not None else "unknown"
                    logger.warning(
                        "Order rejected (%s): required margin $%,.2f exceeds available balance %s",
                        decision.action.upper(),
                        required_margin,
                        available_str,
                    )
                    _persist_cycle(
                        current_time,
                        account_snapshot,
                        market_snapshot,
                        major_titles,
                        decision,
                        order_args=order_args,
                        order_placed=False,
                        decision_action_override=f"{decision.action}_rejected_insufficient_balance",
                    )
                    dashboard.set_state(
                        stage="cycle_complete",
                        order_status="rejected_insufficient_balance",
                    )
                    dashboard.add_event(
                        (
                            f"{decision.action.upper()} rejected: required {fmt_money(required_margin)} "
                            f"> available {available_str}"
                        ),
                        current_time,
                    )
                    time.sleep(interval)
                    continue

                dashboard.set_state(stage="placing_order", order_status="submitting_order")
                logger.info("Placing %s order for %s %s @ %sx lev", decision.action.upper(), decision.size, coin, decision.leverage)
                order_placed = place_order(
                    hyperliquid_url,
                    api_wallet_private_key,
                    order_args["is_buy"],
                    coin,
                    order_args["size"],
                    decision.leverage,
                    decision.tif,
                )
                if order_placed:
                    _persist_cycle(
                        current_time,
                        account_snapshot,
                        market_snapshot,
                        major_titles,
                        decision,
                        order_args=order_args,
                        order_placed=order_placed,
                    )
                    dashboard.set_state(
                        stage="cycle_complete",
                        order_status="order_placed",
                    )
                    dashboard.add_event(
                        (
                            f"Order placed: {decision.action.upper()} "
                            f"{fmt_num(decision.size, 5)} {coin} @ lev {decision.leverage}"
                        ),
                        current_time,
                    )
                    logger.info("Order placed successfully.")
                else:
                    dashboard.set_state(
                        stage="cycle_complete",
                        order_status="order_failed",
                    )
                    dashboard.add_event("Order placement failed", current_time)
                    logger.error("Order placement failed.")
                time.sleep(interval)
            except Exception as e:
                logger.error("Loop error: %s", e, exc_info=True)
                dashboard.add_event(f"Loop error: {e}")
                dashboard.set_state(stage="error_state", order_status="error")
                logger.info("Retrying in %d seconds", interval)
                time.sleep(interval)
    except KeyboardInterrupt:
        dashboard.add_event("Scheduler stopped by user")
        dashboard.set_state(stage="stopped", order_status="stopped")
        logger.info("Scheduler stopped by user.")
    finally:
        if web_dashboard is not None:
            web_dashboard.stop()


if __name__ == "__main__":
    main()
