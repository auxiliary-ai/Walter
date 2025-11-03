import requests
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Any, Dict, List

def _post(
    base_url: str, payload: Dict[str, Any]
) -> Dict[str, Any] | List[Dict[str, Any]]:
    """Send a POST request to the given base URL."""
    response = requests.post(base_url, json=payload, timeout=10)
    response.raise_for_status()
    return response.json()


def GetMarketSnapshot(
     coin : str , interval:str , history_hours=1, base_url="https://api.hyperliquid-testnet.xyz/info"
) -> Dict[str, Any]:
    """
    Collect a quick market overview for the requested coin.

    Returns a dictionary with price, volume, funding and trade information.
    """
    end_time = int(datetime.utcnow().timestamp() * 1000)
    start_time = end_time - history_hours * 3600 * 1000

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
                "interval": interval,
                "startTime": start_time,
                "endTime": end_time,
            },
        },
    )

    df = pd.DataFrame(candles)
    df["t"] = pd.to_datetime(df["t"], unit="ms")
    df["c"] = df["c"].astype(float)
    df["v"] = df["v"].astype(float)

    # 24 h subset (24 candles -> 24 h at 1 h interval)
    recent = df.tail(24)
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
    # # ------------------------------------------------
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

    # Return relevant information

    openInterest = (asset_ctx.get("openInterest"),)
    funding = (asset_ctx.get("funding"),)
    markPx = (asset_ctx.get("markPx"),)
    dayNtlVlm = (asset_ctx.get("dayNtlVlm"),)
    midPx = (asset_ctx.get("midPx"),)
    oraclePx = asset_ctx.get("oraclePx")

    # ------------------------------------------------
    # 5. Recent trades
    # ------------------------------------------------
    trades = _post(base_url, {"type": "recentTrades", "coin": coin})
    buy_volume = 0
    sell_volume = 0
    buy_count = 0
    sell_count = 0
    for trade in trades:
        size = float(trade['sz'])
        
        if trade['side'] == 'B':  # Buy (taker bought)
            buy_volume += size
            buy_count += 1
        else:  # Sell (taker sold)
            sell_volume += size
            sell_count += 1
    
    total_volume = buy_volume + sell_volume
    
    buy_pressure= (buy_volume / total_volume * 100) if total_volume > 0 else 0
    sell_pressure= (sell_volume / total_volume * 100) if total_volume > 0 else 0
    buy_volume= buy_volume
    sell_volume= sell_volume
    buy_count= buy_count
    sell_count= sell_count
    net_volume= buy_volume - sell_volume
    volume_delta= ((buy_volume - sell_volume) / total_volume * 100) if total_volume > 0 else 0

    # ------------------------------------------------
    # 6. Build final snapshot
    # ------------------------------------------------
    snapshot = {
        "coin": coin,
        "current_price": current_price,
        "ema10": round(ema10, 3),
        "ema20": round(ema20, 3),
        "funding_rate_latest": funding_latest,
        "funding_rate_avg": round(funding_avg, 6) if funding_avg is not None else None,
        "volatility_24h": round(volatility, 6),
        "volume_24h": round(vol24h, 3),
        "open_interest": openInterest,
        "buy_pressure":buy_pressure,
        "net_volume":net_volume
    }
 # TODO: metric below may be added to reponse as per ML engineer request
    return snapshot