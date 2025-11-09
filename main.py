import os
import time

from dotenv import load_dotenv

from walter.market_data import GetMarketSnapshot
from walter.hyperliquid_API import GetOpenPositionDetails, PlaceOrder
from walter.LLM_API import LLMAPI


for dotenv_file in (".env.local", ".env"):
    load_dotenv(dotenv_path=dotenv_file, override=False)
interval = int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "60"))
coin = str(os.getenv("COIN"))
hyperliquid_url = str(os.getenv("HYPERLIQUID_URL"))
general_public_key = str(os.getenv("GENERAL_PUBLIC_KEY"))
api_wallet_private_key = str(os.getenv("API_WALLET_PRIVATE_KEY"))
default_size = float(os.getenv("ORDER_SIZE", "0.5"))
default_leverage = float(os.getenv("ORDER_LEVERAGE", "1"))
default_tif = str(os.getenv("ORDER_TIF", "Ioc"))
gemini_key = os.getenv("GEMINI_API_KEY")
llm_api = LLMAPI(api_key=gemini_key)

def main() -> None:
    print(f"Scheduler running every {interval} seconds.")
    try:
        while True:
            snapshot = GetMarketSnapshot(coin, "1h", hyperliquid_url, 1)
            print(snapshot)
            response = GetOpenPositionDetails(hyperliquid_url, general_public_key)
            print(response)
            decision = llm_api.decide_from_market(snapshot, response)
            print(decision)
            if not decision.execute:
                print(
                    f"LLM decision '{decision.action}' below confidence threshold. Skipping order."
                )
                time.sleep(interval)
                continue

            PlaceOrder(
                hyperliquid_url,
                api_wallet_private_key,
                decision.action == "buy",
                coin,
                default_size,
                default_leverage,
                default_tif,
            )
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nScheduler stopped.")


if __name__ == "__main__":
    main()
