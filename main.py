import os
import time

from dotenv import load_dotenv

from walter.market_data import GetMarketSnapshot
from walter.hyperliquid_API import GetOpenPositionDetails, PlaceOrder
from walter.LLM_API import LLMAPI
from walter.db_utils import (
    ensure_schema,
    save_market_snapshot,
    save_order_attempt,
    save_account_snapshot,
)
from datetime import datetime, timezone
from walter.news_API_aggregator import CryptoNewsAggregator
from walter.news_summerizer import get_summaries_from_news

for dotenv_file in (".env.local", ".env"):
    load_dotenv(dotenv_path=dotenv_file, override=False)
interval = int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "60"))
coin = str(os.getenv("COIN"))
hyperliquid_url = str(os.getenv("HYPERLIQUID_URL"))
general_public_key = str(os.getenv("GENERAL_PUBLIC_KEY"))
api_wallet_private_key = str(os.getenv("API_WALLET_PRIVATE_KEY"))
llm_model = os.getenv("LLM_MODEL")
openrouter_key = os.getenv("OPENROUTER_API_KEY")
history_length = int(os.getenv("LLM_HISTORY_LENGTH", "5"))
llm_api = LLMAPI(
    api_key=openrouter_key,
    model=llm_model or "gemini-flash",
    history_length=history_length,
)
ensure_schema()


def main() -> None:
    print(f"Scheduler running every {interval} seconds.")
    try:
        while True:
            try:
                news = CryptoNewsAggregator.getAggregatedNews()
                summary = get_summaries_from_news(news)
                major_titles = [n.get("title", "") for n in summary.get("major_narratives", [])]                
                current_time = datetime.now(timezone.utc)
                marketSnapshot = GetMarketSnapshot(coin, "1h", hyperliquid_url, 6)
                print(marketSnapshot)
                accountSnapshot = GetOpenPositionDetails(hyperliquid_url, general_public_key)
                print(accountSnapshot)
                decision = llm_api.decide_from_market(marketSnapshot, accountSnapshot)
                print(f"Thinking: {decision.thinking}")
                print(decision)
                if not decision.execute:
                    print(
                        f"LLM decision '{decision.action}' below confidence threshold. Skipping order."
                    )
                    account_snapshot_id = save_account_snapshot(current_time, accountSnapshot)
                    snapshot_id = save_market_snapshot(marketSnapshot, captured_at=current_time)
                    save_order_attempt(
                        created_at=current_time,
                        coin=coin,
                        is_buy=False,
                        size=None,
                        leverage=None,
                        tif=None,
                        decision_action="hold",
                        decision_confidence=decision.confidence,
                        thinking=decision.thinking,
                        snapshot_id=snapshot_id,
                        account_snapshot_id=account_snapshot_id,
                        order_payload=None,
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

                order_placed = PlaceOrder(
                    hyperliquid_url,
                    api_wallet_private_key,
                    decision.action == "buy",
                    coin,
                    decision.size,
                    decision.leverage,
                    decision.tif,
                )
                if order_placed:
                    account_snapshot_id = save_account_snapshot(current_time, accountSnapshot)
                    snapshot_id = save_market_snapshot(marketSnapshot, captured_at=current_time)
                    save_order_attempt(
                        created_at=current_time,
                        coin=coin,
                        is_buy=order_args["is_buy"],
                        size=order_args["size"],
                        leverage=order_args["leverage"],
                        tif=order_args["tif"],
                        decision_action=decision.action,
                        decision_confidence=decision.confidence,
                        thinking=decision.thinking,
                        snapshot_id=snapshot_id,
                        account_snapshot_id=account_snapshot_id,
                        order_payload=order_args,
                        order_placed=order_placed,
                    )
                time.sleep(interval)
            except Exception as e:
                print(f"[{datetime.now(timezone.utc).isoformat()}] loop error: {e}")
                print(f"Retrying in {interval} seconds")
                time.sleep(interval)
    except KeyboardInterrupt:
        print("Scheduler stopped by user.")


if __name__ == "__main__":
    main()
