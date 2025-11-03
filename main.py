import os
import time
from typing import Callable, List
from dotenv import load_dotenv  
from src.market_data import GetMarketSnapshot

load_dotenv()
SCHEDULER_INTERVAL_SECONDS = "SCHEDULER_INTERVAL_SECONDS"
interval = int(os.getenv(SCHEDULER_INTERVAL_SECONDS, "60"))

def task_example() -> None:
    """Example scheduled task."""
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Running scheduled placeholder task.")
    snapshot = GetMarketSnapshot('ETH','1h')
    print(snapshot)


# Add your functions here
TASKS: List[Callable[[], None]] = [
    task_example,
    # e.g. execute_trading_strategy,
]


def main() -> None:
    print(f"Scheduler running every {interval} seconds. Press Ctrl+C to stop.")
    try:
        while True:
            for task in TASKS:
                task()
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nScheduler stopped.")


if __name__ == "__main__":
    main()
