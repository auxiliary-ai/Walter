import logging
import time
from typing import Any

from walter.market_data import get_market_snapshot
from walter.hyperliquid_api import (
    get_open_position_details,
    place_order,
    get_withdrawable_balance,
)
from walter.llm_api import LLMAPI
from walter.db_utils import (
    initialize_database,
    save_market_snapshot,
    save_order_attempt,
    save_account_snapshot,
    save_news_snapshot,
)
from datetime import datetime, timezone
from walter.news_aggregator import CryptoNewsAggregator
from walter.news_summarizer import get_summaries_from_news

from walter.config import (
    SCHEDULER_INTERVAL_SECONDS,
    COIN,
    HYPERLIQUID_URL,
    GENERAL_PUBLIC_KEY,
    API_WALLET_PRIVATE_KEY,
    LLM_MODEL,
    OPENROUTER_API_KEY,
    LLM_HISTORY_LENGTH,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
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
initialize_database()


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
    try:
        while True:
            try:
                news = CryptoNewsAggregator.get_aggregated_news()
                summary = get_summaries_from_news(news)
                major_titles = [
                    n.get("title", "") for n in summary.get("major_narratives", [])
                ]
                current_time = datetime.now(timezone.utc)
                market_snapshot = get_market_snapshot(coin, "1h", hyperliquid_url, 6)
                logger.info("Market snapshot: %s", market_snapshot)
                account_snapshot = get_open_position_details(
                    hyperliquid_url, general_public_key
                )
                logger.info("Account snapshot: %s", account_snapshot)
                decision = llm_api.decide_from_market(
                    market_snapshot, account_snapshot, major_titles
                )
                logger.info("Thinking: %s", decision.thinking)
                logger.info("Decision: %s", decision)

                if decision.action == "hold":
                    logger.info(
                        "LLM decision '%s'. Skipping placing order.", decision.action
                    )
                    _persist_cycle(
                        current_time,
                        account_snapshot,
                        market_snapshot,
                        major_titles,
                        decision,
                        order_placed=None,
                    )
                    time.sleep(interval)
                    continue

                order_args = {
                    "is_buy": decision.action == "buy",
                    "coin": coin,
                    "size": decision.size,
                    "leverage": decision.leverage,
                    "tif": decision.tif or "Ioc",
                }

                # ── Balance guard (applies to both buy and sell orders) ──
                available = get_withdrawable_balance(account_snapshot)
                current_price = market_snapshot.get("current_price", 0)
                leverage = decision.leverage if decision.leverage else 1
                required_margin = (decision.size * current_price) / leverage

                if available is None or required_margin > available:
                    available_str = (
                        f"${available:,.2f}" if available is not None else "unknown"
                    )
                    logger.warning(
                        "Order rejected (%s): required margin $%,.2f "
                        "exceeds available balance %s",
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
                    time.sleep(interval)
                    continue

                order_placed = place_order(
                    hyperliquid_url,
                    api_wallet_private_key,
                    decision.action == "buy",
                    coin,
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
                time.sleep(interval)
            except Exception as e:
                logger.error("Loop error: %s", e, exc_info=True)
                logger.info("Retrying in %d seconds", interval)
                time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user.")


if __name__ == "__main__":
    main()
