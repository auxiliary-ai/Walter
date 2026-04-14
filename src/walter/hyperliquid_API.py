import json
import logging
from decimal import Decimal

import requests
from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info

logger = logging.getLogger(__name__)


def _get_tick_size(asset_meta: dict) -> Decimal:
    raw_tick = asset_meta.get("szDecimals")
    if raw_tick is None:
        px_decimals = asset_meta.get("pxDecimals")
        if px_decimals is None:
            raise ValueError(f"No tick size info for {asset_meta['name']}")
        raw_tick = Decimal(1).scaleb(-px_decimals)
    return Decimal(str(raw_tick))


def _snap_to_tick(
    price: float, tick: Decimal, bias: str = "nearest"
) -> tuple[Decimal, str | None]:
    px = Decimal(str(price))
    remainder = px % tick
    if remainder == 0:
        return px, None

    lower = (px // tick) * tick
    upper = lower + tick

    if bias == "up":
        return upper, f"Price {px} rounded up to next tick {upper}"
    if bias == "down":
        return lower, f"Price {px} rounded down to previous tick {lower}"

    midpoint = lower + tick / 2
    snapped = upper if px >= midpoint else lower
    direction = "up" if snapped == upper else "down"
    return (
        snapped,
        f"Price {px} snapped {direction} to tick {snapped} (valid choices: {lower}, {upper})",
    )


def get_open_position_details(base_url: str, general_public_key: str) -> dict:
    """Fetch clearinghouse state for the given public key."""
    payload = json.dumps(
        {"type": "clearinghouseState", "user": general_public_key, "dex": ""}
    )
    headers = {"Content-Type": "application/json"}

    response = requests.request("POST", base_url, headers=headers, data=payload)
    return response.json()


def get_withdrawable_balance(account_snapshot: dict) -> float | None:
    """Return the withdrawable (available) balance from a clearinghouseState snapshot.

    The Hyperliquid ``clearinghouseState`` response contains a ``withdrawable``
    field (string) representing the USD amount available for new positions after
    accounting for existing margin requirements.

    Returns ``None`` when the value is missing or cannot be parsed so callers
    can treat it as "unknown" and refuse the order.
    """
    try:
        return float(account_snapshot.get("withdrawable", 0))
    except (TypeError, ValueError):
        return None


def place_order(
    base_url: str,
    api_wallet_private_key: str,
    is_buy: bool,
    coin: str,
    size: float,
    leverage: int,
    tif: str | None,
    order_type: str = "market",
    limit_price: float | None = None,
) -> bool:
    """Place a market or limit order on Hyperliquid."""
    account = Account.from_key(api_wallet_private_key)
    base_url = base_url.removesuffix("/info")

    info = Info(base_url, skip_ws=True, spot_meta={"universe": [], "tokens": []})
    exchange = Exchange(account, base_url, spot_meta={"universe": [], "tokens": []})

    meta = info.meta()
    asset = next((a for a in meta["universe"] if a["name"] == coin), None)
    if not asset:
        raise ValueError(f"Coin {coin} not found")

    size_decimals = asset["szDecimals"]
    tick_size = _get_tick_size(asset)

    l2 = info.l2_snapshot(coin)
    bid = float(l2["levels"][0][0]["px"])
    ask = float(l2["levels"][1][0]["px"])
    mid = (bid + ask) / 2

    logger.info("=" * 60)
    logger.info("Asset: %s", coin)
    logger.info(
        "Bid: $%s, Ask: $%s, Mid: $%s",
        f"{bid:,.2f}",
        f"{ask:,.2f}",
        f"{mid:,.2f}",
    )

    validated_size = round(size, size_decimals)
    if order_type == "market":
        raw_price = ask * 1.02 if is_buy else bid * 0.98
        validated_price, note = _snap_to_tick(
            raw_price,
            tick_size,
            bias="up" if is_buy else "down",
        )
        order_params = {"limit": {"tif": tif or "Ioc"}}
        order_params = {"limit": {"tif": tif or "Ioc"}}
    else:
        raw_price = limit_price if limit_price is not None else mid
        validated_price, note = _snap_to_tick(raw_price, tick_size)
        order_params = {"limit": {"tif": tif or "Gtc"}}

    if note:
        logger.info(note)
        order_params = {"limit": {"tif": tif or "Gtc"}}

    if note:
        logger.info(note)

    logger.info("-" * 60)
    logger.info(
        "Final %s order: %s %s %s @ $%s (%s)",
        order_type.upper(),
        "BUY" if is_buy else "SELL",
        validated_size,
        coin,
        f"{float(validated_price):,.2f}",
        order_params["limit"]["tif"],
    )

    try:
        exchange.update_leverage(leverage, coin)
        exchange.update_leverage(leverage, coin)
        result = exchange.order(
            coin,
            is_buy,
            validated_size,
            float(validated_price),
            order_params,
            reduce_only=False,
        )
        logger.info("Order placed successfully. Result: %s", result)
        return True
    except Exception as e:
        logger.error("Error placing order: %s", e)
        return False


def close_position(
    base_url: str,
    api_wallet_private_key: str,
    general_public_key: str,
    coin: str,
) -> bool:
    """Close the entire open position for *coin* using a reduce-only market order.

    Returns True if the close order was placed, False if there was no position
    to close or the order failed.
    """
    account = get_open_position_details(base_url, general_public_key)
    asset_positions = account.get("assetPositions", [])
    position = None
    for ap in asset_positions:
        item = ap.get("position", ap)
        if item.get("coin") == coin:
            position = item
            break

    if position is None:
        logger.info("No open %s position to close.", coin)
        return False

    szi = float(position.get("szi", 0))
    if szi == 0:
        logger.info("Open %s position has zero size; nothing to close.", coin)
        return False

    is_buy = szi < 0
    close_size = abs(szi)

    acct = Account.from_key(api_wallet_private_key)
    exchange_base = base_url.removesuffix("/info")
    info = Info(exchange_base, skip_ws=True, spot_meta={"universe": [], "tokens": []})
    exchange = Exchange(acct, exchange_base, spot_meta={"universe": [], "tokens": []})

    meta = info.meta()
    asset = next((a for a in meta["universe"] if a["name"] == coin), None)
    if not asset:
        logger.error("Coin %s not found in universe; cannot close.", coin)
        return False

    size_decimals = asset["szDecimals"]
    validated_size = round(close_size, size_decimals)

    l2 = info.l2_snapshot(coin)
    bid = float(l2["levels"][0][0]["px"])
    ask = float(l2["levels"][1][0]["px"])
    raw_price = ask * 1.02 if is_buy else bid * 0.98

    tick_size = _get_tick_size(asset)
    validated_price, note = _snap_to_tick(
        raw_price,
        tick_size,
        bias="up" if is_buy else "down",
    )
    if note:
        logger.info(note)

    logger.info("-" * 60)
    logger.info(
        "Closing %s position: %s %.6f @ ~$%.2f",
        coin,
        "BUY-to-close" if is_buy else "SELL-to-close",
        validated_size,
        float(validated_price),
    )

    try:
        result = exchange.order(
            coin,
            is_buy,
            validated_size,
            float(validated_price),
            {"limit": {"tif": "Ioc"}},
            reduce_only=True,
        )
        logger.info("Close order placed: %s", result)
        return True
    except Exception as e:
        logger.error("Error closing position: %s", e)
        return False
