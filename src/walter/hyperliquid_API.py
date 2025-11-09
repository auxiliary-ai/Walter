from decimal import Decimal
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants
from eth_account import Account
import requests
import json


def GetOpenPositionDetails(base_url, general_public_key):

    payload = json.dumps(
        {"type": "clearinghouseState", "user": general_public_key, "dex": ""}
    )
    headers = {"Content-Type": "application/json"}

    response = requests.request("POST", base_url, headers=headers, data=payload)
    return response.json()
    # TODO: very long response, check with ML engineer what to keep of it


def PlaceOrder(base_url, api_wallet_private_key, is_buy, coin, size, leverage, tif):
    # =============================================================================
    # CONFIGURATION - EDIT THESE
    # =============================================================================

    ORDER_TYPE = "market"  # "market" or "limit"
    PRICE = 1146  # Used only for limit orders
    # TODO add stop-loss
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

    def get_tick_size(asset_meta: dict) -> Decimal:
        raw_tick = asset_meta.get("szDecimals")
        if raw_tick is None:
            px_decimals = asset_meta.get("pxDecimals")
            if px_decimals is None:
                raise ValueError(f"No tick size info for {asset_meta['name']}")
            raw_tick = Decimal(1).scaleb(-px_decimals)
        return Decimal(str(raw_tick))

    def snap_to_tick(
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

    tick_size = get_tick_size(asset)

    # Get live prices
    l2 = info.l2_snapshot(coin)
    bid = float(l2["levels"][0][0]["px"])
    ask = float(l2["levels"][1][0]["px"])
    mid = (bid + ask) / 2

    print(f"{'='*60}")
    print(f"Asset: {coin}")
    print(f"Bid: ${bid:,.2f}, Ask: ${ask:,.2f}, Mid: ${mid:,.2f}")
    print(f"{'='*60}\n")

    # =============================================================================
    # Validate size
    # =============================================================================

    validated_size = round(size, size_decimals)

    # =============================================================================
    # Determine price
    # =============================================================================

    if ORDER_TYPE == "market":
        raw_price = ask * 1.02 if is_buy else bid * 0.98
        validated_price, note = snap_to_tick(
            raw_price, tick_size, bias="up" if is_buy else "down"
        )
        if note:
            print(note)
        order_type_payload = {"market": {}}
    else:
        raw_price = PRICE
        validated_price, note = snap_to_tick(raw_price, tick_size)
        if note:
            print(f"Limit price adjustment needed -> {note}")
        order_type_payload = {"limit": {"tif": "Gtc"}}

    # =============================================================================
    # Display final order details
    # =============================================================================

    print(f"{'─'*60}")
    print(f"Final Order Details:")
    print(f"  Coin:      {coin}")
    print(f"  Type:      {ORDER_TYPE.upper()}")
    print(f"  Direction: {'BUY' if is_buy else 'SELL'}")
    print(f"  Size:      {validated_size} {coin}")
    print(f"  Price:     ${validated_price:,.2f}")
    print(f"  Total:     ${validated_size * float(validated_price.real):,.2f}")
    print(f"{'─'*60}\n")

    # =============================================================================
    # Place order
    # =============================================================================

    try:
        lev = exchange.update_leverage(
            leverage, coin
        )  # third arg stays True for cross; pass False for isolated
        result = exchange.order(
            coin,
            is_buy,
            validated_size,
            float(validated_price.real),
            {"limit": {"tif": tif}},
            reduce_only=False,
        )
        print(lev)
        print("✅ Order placed successfully!")
        print(result)

    except Exception as e:
        print(f"❌ Error placing order: {e}")
