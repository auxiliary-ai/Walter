import os
import time
from dotenv import load_dotenv
from src.market_data import GetMarketSnapshot
from src.hyperliquid_API import GetOpenPositionDetails, PlaceOrder

load_dotenv()
interval = int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "60"))
coin = str(os.getenv("COIN"))
hyperliquid_url = str(os.getenv("HYPERLIQUID_URL"))
general_public_key = str(os.getenv("GENERAL_PUBLIC_KEY"))
api_wallet_private_key = str(os.getenv("API_WALLET_PRIVATE_KEY"))


def main() -> None:
    print(f"Scheduler running every {interval} seconds.")
    try:
        while True:
            snapshot = GetMarketSnapshot(coin, "1h", hyperliquid_url, 1)
            print(snapshot)
            response = GetOpenPositionDetails(hyperliquid_url, general_public_key)
            print(response)
            ###################################
            # here goes getting the LLM's decision
            ###################################
            is_buy = True
            size = 0.5
            leverage = 1
            tif = "Ioc"
            PlaceOrder(
                hyperliquid_url,
                api_wallet_private_key,
                is_buy,
                coin,
                size,
                leverage,
                tif,
            )
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nScheduler stopped.")


if __name__ == "__main__":
    main()
