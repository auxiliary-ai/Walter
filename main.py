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
)
logger = logging.getLogger(__name__)

# --- Configuration & Setup ---
INTERVAL = int(SCHEDULER_INTERVAL_SECONDS)
COIN_TICKER = str(COIN)
HL_URL = str(HYPERLIQUID_URL)
GEN_PUB_KEY = str(GENERAL_PUBLIC_KEY)
API_PRIV_KEY = str(API_WALLET_PRIVATE_KEY)

llm_api = LLMAPI(
    api_key=OPENROUTER_API_KEY,
    model=LLM_MODEL,
    history_length=int(LLM_HISTORY_LENGTH),
)
initialize_database()

WEB_DASHBOARD_ENABLED = os.getenv("WALTER_ENABLE_WEB_DASHBOARD", "1") != "0"
WEB_DASHBOARD_HOST = os.getenv("WALTER_WEB_HOST", "127.0.0.1")
try:
    WEB_DASHBOARD_PORT = int(os.getenv("WALTER_WEB_PORT", "8765"))
except ValueError:
    WEB_DASHBOARD_PORT = 8765


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
        coin=COIN_TICKER,
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
    logger.info("Scheduler running every %d seconds.", INTERVAL)
    web_dashboard: WebDashboardServer | None = None
    if WEB_DASHBOARD_ENABLED:
        try:
            web_dashboard = WebDashboardServer(
                host=WEB_DASHBOARD_HOST,
                port=WEB_DASHBOARD_PORT,
            )
            web_dashboard.start()
            logger.info("Web dashboard available at %s", web_dashboard.url)
        except OSError as exc:
            logger.warning("Web dashboard disabled (bind failed): %s", exc)
            web_dashboard = None

    dashboard = TradingDashboard(COIN_TICKER, web_dashboard=web_dashboard)
    dashboard.add_event(f"Scheduler started (interval={INTERVAL}s)")
    if web_dashboard is not None:
        dashboard.add_event(f"Web dashboard: {web_dashboard.url}")
    dashboard.set_state(stage="initializing")
    dashboard.render()
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
                dashboard.render()

                news = CryptoNewsAggregator.get_aggregated_news()
                summary = get_summaries_from_news(news)
                major_titles = [n.get("title", "") for n in summary.get("major_narratives", [])]
                dashboard.set_state(major_titles=major_titles, stage="collecting_market")
                dashboard.add_event(f"News processed ({len(major_titles)} major narratives)")
                dashboard.render()

                market_snapshot = get_market_snapshot(COIN_TICKER, "1h", HL_URL, 6)
                dashboard.set_state(market_snapshot=market_snapshot, stage="collecting_account")
                dashboard.render()

                account_snapshot = get_open_position_details(
                    HL_URL, GEN_PUB_KEY
                )
                dashboard.set_state(account_snapshot=account_snapshot, stage="llm_decision")
                dashboard.render()

                decision = llm_api.decide_from_market(
                    market_snapshot, account_snapshot, major_titles
                )
                dashboard.set_state(decision=decision, stage="decision_ready")
                dashboard.add_event(
                    f"Decision={decision.action.upper()} size={decision.size} lev={decision.leverage}"
                )
                dashboard.render()

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
                    dashboard.render()
                    time.sleep(INTERVAL)
                    continue

                order_args = {
                    "is_buy": decision.action == "buy",
                    "coin": COIN_TICKER,
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
                    dashboard.render()
                    time.sleep(INTERVAL)
                    continue

                available = get_withdrawable_balance(account_snapshot)
                current_price = market_snapshot.get("current_price", 0)
                leverage = decision.leverage if decision.leverage else 1
                required_margin = (decision.size * current_price) / leverage
                dashboard.set_state(
                    stage="risk_check",
                    required_margin=required_margin,
                    available_balance=available,
                )
                dashboard.render()

                if available is None or required_margin > available:
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
                    dashboard.render()
                    time.sleep(INTERVAL)
                    continue

                dashboard.set_state(stage="placing_order", order_status="submitting_order")
                dashboard.render()
                order_placed = place_order(
                    HL_URL,
                    API_PRIV_KEY,
                    decision.action == "buy",
                    COIN_TICKER,
                    decision.size,
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
                            f"{fmt_num(decision.size, 5)} {COIN_TICKER} @ lev {decision.leverage}"
                        ),
                        current_time,
                    )
                else:
                    dashboard.set_state(
                        stage="cycle_complete",
                        order_status="order_failed",
                    )
                    dashboard.add_event("Order placement failed", current_time)
                dashboard.render()
                time.sleep(INTERVAL)
            except Exception as e:
                logger.error("Loop error: %s", e, exc_info=True)
                dashboard.add_event(f"Loop error: {e}")
                dashboard.set_state(stage="error_state", order_status="error")
                dashboard.render()
                logger.info("Retrying in %d seconds", INTERVAL)
                time.sleep(INTERVAL)
    except KeyboardInterrupt:
        dashboard.add_event("Scheduler stopped by user")
        dashboard.set_state(stage="stopped", order_status="stopped")
        dashboard.render()
        logger.info("Scheduler stopped by user.")
    finally:
        if web_dashboard is not None:
            web_dashboard.stop()


if __name__ == "__main__":
    main()
