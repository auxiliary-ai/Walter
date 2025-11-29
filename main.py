import os
import time

from dotenv import load_dotenv

from walter.market_data import GetMarketSnapshot
from walter.hyperliquid_API import GetOpenPositionDetails, PlaceOrder
from walter.LLM_API import LLMAPI
from walter.db_utils import ensure_schema, save_snapshot, save_order_attempt
from datetime import datetime, timezone

for dotenv_file in (".env.local", ".env"):
    load_dotenv(dotenv_path=dotenv_file, override=False)
interval = int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "60"))
coin = str(os.getenv("COIN"))
hyperliquid_url = str(os.getenv("HYPERLIQUID_URL"))
general_public_key = str(os.getenv("GENERAL_PUBLIC_KEY"))
api_wallet_private_key = str(os.getenv("API_WALLET_PRIVATE_KEY"))
gemini_key = os.getenv("GEMINI_API_KEY")
llm_api = LLMAPI(api_key=gemini_key)
ensure_schema()


def main() -> None:
    print(f"Scheduler running every {interval} seconds.")
    try:
        while True:
            snapshot = GetMarketSnapshot(coin, "1h", hyperliquid_url, 6)
            print(snapshot)
            response = GetOpenPositionDetails(hyperliquid_url, general_public_key)
            print(response)
            decision = llm_api.decide_from_market(snapshot, response)
            print(decision)
            if not decision.execute:
                print(
                    f"LLM decision '{decision.action}' below confidence threshold. Skipping order."
                )
                current_time = datetime.now(timezone.utc)
                snapshot_id = save_snapshot(snapshot, captured_at=current_time)
                save_order_attempt(
                    created_at=current_time,
                    coin=coin,
                    is_buy=False,
                    size=None,
                    leverage=None,
                    tif=None,
                    decision_action="hold",
                    decision_confidence=decision.confidence,
                    snapshot_id=snapshot_id,
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
                current_time = datetime.now(timezone.utc)
                snapshot_id = save_snapshot(snapshot, captured_at=current_time)
                save_order_attempt(
                    created_at=current_time,
                    coin=coin,
                    is_buy=order_args["is_buy"],
                    size=order_args["size"],
                    leverage=order_args["leverage"],
                    tif=order_args["tif"],
                    decision_action=decision.action,
                    decision_confidence=decision.confidence,
                    snapshot_id=snapshot_id,
                    order_payload=order_args,
                    order_placed=order_placed,
                )
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nScheduler stopped.")


if __name__ == "__main__":
    main()
