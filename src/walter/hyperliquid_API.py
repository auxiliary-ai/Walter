import logging
from decimal import Decimal
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from eth_account import Account
import requests
import json

logger = logging.getLogger(__name__)


def get_open_position_details(base_url, general_public_key):
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


def place_order(base_url, api_wallet_private_key, is_buy, coin, size, leverage, tif):
    """Place a market order on Hyperliquid."""
    # =============================================================================
    # CONFIGURATION
    # =============================================================================
    ORDER_TYPE = "market"  # "market" or "limit"
    PRICE = 1146  # Used only for limit orders

    # =============================================================================
    # Setup
    # =============================================================================
    account = Account.from_key(api_wallet_private_key)
    base_url = base_url.removesuffix("/info")

    info = Info(base_url, skip_ws=True)
    exchange = Exchange(account, base_url)

    # =============================================================================
    # Get asset metadata
    # =============================================================================
    meta = info.meta()
    asset = next((a for a in meta["universe"] if a["name"] == coin), None)
    if not asset:
        raise ValueError(f"Coin {coin} not found")

    size_decimals = asset["szDecimals"]

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

    tick_size = _get_tick_size(asset)

    # Get live prices
    l2 = info.l2_snapshot(coin)
    bid = float(l2["levels"][0][0]["px"])
    ask = float(l2["levels"][1][0]["px"])
    mid = (bid + ask) / 2

    logger.info("=" * 60)
    logger.info("Asset: %s", coin)
    logger.info("Bid: $%,.2f, Ask: $%,.2f, Mid: $%,.2f", bid, ask, mid)

    # =============================================================================
    # Validate size
    # =============================================================================
    validated_size = round(size, size_decimals)

    # =============================================================================
    # Determine price
    # =============================================================================
    if ORDER_TYPE == "market":
        raw_price = ask * 1.02 if is_buy else bid * 0.98
        validated_price, note = _snap_to_tick(
            raw_price, tick_size, bias="up" if is_buy else "down"
        )
        if note:
            logger.info(note)
        order_type_payload = {"market": {}}
    else:
        raw_price = PRICE
        validated_price, note = _snap_to_tick(raw_price, tick_size)
        if note:
            logger.info("Limit price adjustment needed -> %s", note)
        order_type_payload = {"limit": {"tif": "Gtc"}}

    # =============================================================================
    # Display final order details
    # =============================================================================
    logger.info("-" * 60)
    logger.info("Final Order Details:")
    logger.info("  Coin:      %s", coin)
    logger.info("  Type:      %s", ORDER_TYPE.upper())
    logger.info("  Direction: %s", "BUY" if is_buy else "SELL")
    logger.info("  Size:      %s %s", validated_size, coin)
    logger.info("  Price:     $%,.2f", validated_price)
    logger.info("  Total:     $%,.2f", validated_size * float(validated_price.real))

    # =============================================================================
    # Place order
    # =============================================================================
    try:
        lev = exchange.update_leverage(leverage, coin)
        result = exchange.order(
            coin,
            is_buy,
            validated_size,
            float(validated_price.real),
            {"limit": {"tif": tif}},
            reduce_only=False,
        )
        logger.info("Leverage update: %s", lev)
        logger.info("✅ Order placed successfully!")
        logger.info("Result: %s", result)
        return True
    except Exception as e:
        logger.error("❌ Error placing order: %s", e)
        return False
