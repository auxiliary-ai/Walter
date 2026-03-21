import logging
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _post(
    base_url: str, payload: Dict[str, Any]
) -> Dict[str, Any] | List[Dict[str, Any]]:
    """Send a POST request to the given base URL."""
    response = requests.post(base_url, json=payload, timeout=10)
    response.raise_for_status()
    return response.json()


def _get_hyperliquid_interval(interval_seconds: int) -> tuple[str, int]:
    """Returns the hyperliquid string interval and the corresponding duration in ms."""
    if interval_seconds <= 60:
        return "1m", 60 * 1000
    elif interval_seconds <= 300:
        return "5m", 300 * 1000
    elif interval_seconds <= 900:
        return "15m", 900 * 1000
    elif interval_seconds <= 1800:
        return "30m", 1800 * 1000
    elif interval_seconds <= 3600:
        return "1h", 3600 * 1000
    elif interval_seconds <= 14400:
        return "4h", 14400 * 1000
    elif interval_seconds <= 28800:
        return "8h", 28800 * 1000
    elif interval_seconds <= 43200:
        return "12h", 43200 * 1000
    else:
        return "1d", 86400 * 1000


def get_market_snapshot(
    coin: str, interval_seconds: int, base_url: str, target_candles: int = 24
) -> Dict[str, Any]:
    """
    Collect a quick market overview for the requested coin.

    Returns a dictionary with price, volume, funding and trade information.
    """
    interval_str, duration_ms = _get_hyperliquid_interval(interval_seconds)
    end_time = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_time = end_time - (target_candles * duration_ms)

    # ------------------------------------------------
    # 1. Current price
    # ------------------------------------------------
    mids = _post(base_url, {"type": "allMids"})
    current_price = float(mids.get(coin, 0))

    # ------------------------------------------------
    # 2. Candle data
    # ------------------------------------------------
    candles = _post(
        base_url,
        {
            "type": "candleSnapshot",
            "req": {
                "coin": coin,
                "interval": interval_str,
                "startTime": start_time,
                "endTime": end_time,
            },
        },
    )

    df = pd.DataFrame(candles)
    df["t"] = pd.to_datetime(df["t"], unit="ms")
    df["c"] = df["c"].astype(float)
    df["v"] = df["v"].astype(float)

    # Target subset based on target_candles
    recent = df.tail(target_candles)
    ema10 = recent["c"].ewm(span=10).mean().iloc[-1]
    ema20 = recent["c"].ewm(span=20).mean().iloc[-1]
    volatility = recent["c"].pct_change().std()
    vol24h = recent["v"].sum()

    # ------------------------------------------------
    # 3. Funding history
    # ------------------------------------------------
    funding = _post(
        base_url, {"type": "fundingHistory", "coin": coin, "startTime": start_time}
    )
    rates = [float(x["fundingRate"]) for x in funding]
    funding_latest = rates[-1] if rates else None
    funding_avg = float(np.mean(rates)) if rates else None

    # ------------------------------------------------
    # 4. Open interest
    # ------------------------------------------------
    oi_resp = _post(base_url, {"type": "metaAndAssetCtxs", "coin": coin})
    universe = oi_resp[0]["universe"]
    asset_contexts = oi_resp[1]

    # Find the index of the coin
    coin_index = None
    for idx, asset in enumerate(universe):
        if asset["name"] == coin:
            coin_index = idx
            break

    if coin_index is None:
        return {"error": f"Coin '{coin}' not found"}

    # Get the corresponding asset context
    asset_ctx = asset_contexts[coin_index]

    open_interest = asset_ctx.get("openInterest")

    # ------------------------------------------------
    # 5. Recent trades
    # ------------------------------------------------
    trades = _post(base_url, {"type": "recentTrades", "coin": coin})
    buy_volume = 0
    sell_volume = 0
    for trade in trades:
        size = float(trade["sz"])
        if trade["side"] == "B":  # Buy (taker bought)
            buy_volume += size
        else:  # Sell (taker sold)
            sell_volume += size

    total_volume = buy_volume + sell_volume
    buy_pressure = (buy_volume / total_volume * 100) if total_volume > 0 else 0
    net_volume = buy_volume - sell_volume

    # ------------------------------------------------
    # 6. Build final snapshot
    # ------------------------------------------------
    # Trend signal from EMA crossover
    if ema10 > ema20:
        trend_signal = "bullish"
    elif ema10 < ema20:
        trend_signal = "bearish"
    else:
        trend_signal = "neutral"

    snapshot = {
        "coin": coin,
        "current_price": current_price,
        "ema10": round(ema10, 3),
        "ema20": round(ema20, 3),
        "trend_signal": trend_signal,
        "funding_rate_latest": funding_latest,
        "funding_rate_avg": round(funding_avg, 6) if funding_avg is not None else None,
        "volatility_24h": round(volatility, 6),
        "volume_24h": round(vol24h, 3),
        "open_interest": open_interest,
        "buy_pressure": buy_pressure,
        "net_volume": net_volume,
    }
    return snapshot
