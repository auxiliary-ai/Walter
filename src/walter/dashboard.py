from __future__ import annotations

import os
import shutil
from collections import deque
from datetime import datetime, timezone
from typing import Any

from walter.web_dashboard import WebDashboardServer


def to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fmt_money(value: float | None) -> str:
    return f"${value:,.2f}" if value is not None else "n/a"


def fmt_num(value: float | None, digits: int = 3) -> str:
    return f"{value:,.{digits}f}" if value is not None else "n/a"


def fmt_pct(value: float | None, digits: int = 2, *, scale_100: bool = False) -> str:
    if value is None:
        return "n/a"
    pct = value * 100 if scale_100 else value
    return f"{pct:,.{digits}f}%"


def extract_position_metrics(
    account_snapshot: dict, target_coin: str, current_price: float | None
) -> dict[str, float | None]:
    margin_summary = account_snapshot.get("marginSummary", {}) or {}
    withdrawable = to_float(account_snapshot.get("withdrawable"))
    account_value = to_float(margin_summary.get("accountValue"))
    total_ntl_pos = to_float(margin_summary.get("totalNtlPos"))

    size = None
    position_value = None
    entry_price = None
    unrealized = None

    for item in account_snapshot.get("assetPositions", []) or []:
        position = item.get("position", item) if isinstance(item, dict) else {}
        if not isinstance(position, dict):
            continue
        if str(position.get("coin", "")).upper() != target_coin.upper():
            continue
        size = to_float(position.get("szi"))
        position_value = to_float(position.get("positionValue"))
        entry_price = to_float(position.get("entryPx"))
        unrealized = to_float(position.get("unrealizedPnl"))
        break

    if position_value is None and size is not None and current_price is not None:
        position_value = size * current_price

    return {
        "withdrawable": withdrawable,
        "account_value": account_value,
        "total_ntl_pos": total_ntl_pos,
        "size": size,
        "position_value": position_value,
        "entry_price": entry_price,
        "unrealized": unrealized,
    }


def sparkline(values: list[float], width: int = 60) -> str:
    if not values:
        return "n/a"
    subset = values[-width:]
    lo = min(subset)
    hi = max(subset)
    ramp = " .:-=+*#%@"
    if hi == lo:
        return ramp[len(ramp) // 2] * len(subset)
    chars: list[str] = []
    for value in subset:
        idx = int((value - lo) / (hi - lo) * (len(ramp) - 1))
        chars.append(ramp[idx])
    return "".join(chars)


class TradingDashboard:
    _UNSET = object()

    def __init__(
        self,
        target_coin: str,
        web_dashboard: WebDashboardServer | None = None,
    ) -> None:
        self.coin = target_coin
        self.web_dashboard = web_dashboard
        self.stage = "starting"
        self.cycle = 0
        self.last_time: datetime | None = None
        self.market_snapshot: dict[str, Any] = {}
        self.account_snapshot: dict[str, Any] = {}
        self.major_titles: list[str] = []
        self.decision: Any | None = None
        self.order_status = "n/a"
        self.required_margin: float | None = None
        self.available_balance: float | None = None
        self.events: deque[str] = deque(maxlen=10)
        self.action_markers: deque[str] = deque(maxlen=16)
        self.prices: deque[float] = deque(maxlen=80)
        self.history_timestamps: deque[str] = deque(maxlen=720)
        self.history_prices: deque[float | None] = deque(maxlen=720)
        self.history_account_values: deque[float | None] = deque(maxlen=720)
        self.history_withdrawables: deque[float | None] = deque(maxlen=720)
        self.history_position_values: deque[float | None] = deque(maxlen=720)
        self.decision_markers: deque[dict[str, Any]] = deque(maxlen=720)
        self._last_marker_key: tuple[str, str] | None = None

    def _push_history_point(
        self,
        *,
        ts: datetime,
        price: float | None,
        account_value: float | None,
        withdrawable: float | None,
        position_value: float | None,
    ) -> None:
        ts_key = ts.astimezone(timezone.utc).isoformat()
        if self.history_timestamps and self.history_timestamps[-1] == ts_key:
            self.history_prices[-1] = price
            self.history_account_values[-1] = account_value
            self.history_withdrawables[-1] = withdrawable
            self.history_position_values[-1] = position_value
            return

        self.history_timestamps.append(ts_key)
        self.history_prices.append(price)
        self.history_account_values.append(account_value)
        self.history_withdrawables.append(withdrawable)
        self.history_position_values.append(position_value)

    def add_event(self, message: str, timestamp: datetime | None = None) -> None:
        ts = (timestamp or datetime.now(timezone.utc)).strftime("%H:%M:%S")
        self.events.appendleft(f"{ts} | {message}")

    def set_state(
        self,
        *,
        stage: str | None = None,
        cycle: int | None = None,
        current_time: datetime | None = None,
        market_snapshot: dict[str, Any] | None = None,
        account_snapshot: dict[str, Any] | None = None,
        major_titles: list[str] | None = None,
        decision: Any | None = None,
        order_status: str | None = None,
        required_margin: float | None | object = _UNSET,
        available_balance: float | None | object = _UNSET,
    ) -> None:
        if stage is not None:
            self.stage = stage
        if cycle is not None:
            self.cycle = cycle
        if current_time is not None:
            self.last_time = current_time
        if market_snapshot is not None:
            self.market_snapshot = market_snapshot
            price = to_float(market_snapshot.get("current_price"))
            if price is not None:
                self.prices.append(price)
        if account_snapshot is not None:
            self.account_snapshot = account_snapshot
        if major_titles is not None:
            self.major_titles = major_titles
        if decision is not None:
            self.decision = decision
            action = str(getattr(decision, "action", "hold")).upper()
            marker_time = (
                self.last_time.strftime("%H:%M:%S")
                if self.last_time is not None
                else datetime.now(timezone.utc).strftime("%H:%M:%S")
            )
            self.action_markers.appendleft(f"{marker_time} {action}")
            if self.last_time is not None:
                marker_ts = self.last_time.astimezone(timezone.utc).isoformat()
                marker_price = to_float(self.market_snapshot.get("current_price"))
                marker_key = (marker_ts, action.lower())
                if marker_price is not None and marker_key != self._last_marker_key:
                    self.decision_markers.append(
                        {
                            "timestamp": marker_ts,
                            "action": action.lower(),
                            "price": marker_price,
                            "thinking": getattr(decision, "thinking", None),
                            "llm_input": getattr(decision, "llm_input", None),
                            "size": to_float(getattr(decision, "size", None)),
                            "leverage": getattr(decision, "leverage", None),
                            "tif": getattr(decision, "tif", None),
                        }
                    )
                    self._last_marker_key = marker_key
        if order_status is not None:
            self.order_status = order_status
        if required_margin is not self._UNSET:
            self.required_margin = required_margin
        if available_balance is not self._UNSET:
            self.available_balance = available_balance

    def render(self) -> None:
        columns = shutil.get_terminal_size((140, 40)).columns
        line = "=" * min(columns, 140)

        price = to_float(self.market_snapshot.get("current_price"))
        ema10 = to_float(self.market_snapshot.get("ema10"))
        ema20 = to_float(self.market_snapshot.get("ema20"))
        funding_latest = to_float(self.market_snapshot.get("funding_rate_latest"))
        funding_avg = to_float(self.market_snapshot.get("funding_rate_avg"))
        volatility = to_float(self.market_snapshot.get("volatility_24h"))
        buy_pressure = to_float(self.market_snapshot.get("buy_pressure"))
        volume_24h = to_float(self.market_snapshot.get("volume_24h"))
        open_interest = to_float(self.market_snapshot.get("open_interest"))

        metrics = extract_position_metrics(self.account_snapshot, self.coin, price)
        if self.last_time is not None:
            self._push_history_point(
                ts=self.last_time,
                price=price,
                account_value=metrics["account_value"],
                withdrawable=metrics["withdrawable"],
                position_value=metrics["position_value"],
            )

        decision_action = (
            str(getattr(self.decision, "action", "n/a")).upper()
            if self.decision is not None
            else "n/a"
        )
        decision_thinking = (
            str(getattr(self.decision, "thinking", "n/a"))
            if self.decision is not None
            else "n/a"
        )
        decision_size = (
            to_float(getattr(self.decision, "size", None))
            if self.decision is not None
            else None
        )
        decision_leverage = (
            getattr(self.decision, "leverage", None) if self.decision is not None else None
        )

        now_label = (
            self.last_time.strftime("%Y-%m-%d %H:%M:%S UTC")
            if self.last_time is not None
            else datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        )
        news_preview = self.major_titles[:3] if self.major_titles else ["no major titles"]
        trend = sparkline(list(self.prices), width=70)
        action_history = " | ".join(self.action_markers) if self.action_markers else "n/a"

        rows = [
            line,
            f"WALTER LIVE TRADING DASHBOARD | {self.coin} | cycle {self.cycle} | stage: {self.stage}",
            f"timestamp: {now_label}",
            line,
            "MARKET",
            (
                f"price={fmt_money(price)}  ema10={fmt_num(ema10)}  ema20={fmt_num(ema20)}  "
                f"ema_gap={fmt_num((ema10 - ema20) if ema10 is not None and ema20 is not None else None)}"
            ),
            (
                f"funding_latest={fmt_pct(funding_latest, 4, scale_100=True)}  "
                f"funding_avg={fmt_pct(funding_avg, 4, scale_100=True)}  "
                f"volatility_24h={fmt_pct(volatility, 2, scale_100=True)}"
            ),
            (
                f"buy_pressure={fmt_pct(buy_pressure, 2)}  volume_24h={fmt_num(volume_24h)}  "
                f"open_interest={fmt_num(open_interest)}"
            ),
            f"price_trend(last {len(self.prices)}): {trend}",
            line,
            "ACCOUNT",
            (
                f"account_value={fmt_money(metrics['account_value'])}  withdrawable={fmt_money(metrics['withdrawable'])}  "
                f"total_ntl_pos={fmt_money(metrics['total_ntl_pos'])}"
            ),
            (
                f"position_size={fmt_num(metrics['size'], 5)} {self.coin}  "
                f"position_value={fmt_money(metrics['position_value'])}  "
                f"entry_price={fmt_money(metrics['entry_price'])}  "
                f"unrealized_pnl={fmt_money(metrics['unrealized'])}"
            ),
            line,
            "DECISION",
            (
                f"action={decision_action}  size={fmt_num(decision_size, 5)} {self.coin}  "
                f"leverage={decision_leverage if decision_leverage is not None else 'n/a'}  "
                f"required_margin={fmt_money(self.required_margin)}  available_for_order={fmt_money(self.available_balance)}"
            ),
            f"order_status={self.order_status}",
            f"thinking={decision_thinking}",
            f"action_timeline={action_history}",
            line,
            "NEWS (top)",
            f"1) {news_preview[0] if len(news_preview) > 0 else 'n/a'}",
            f"2) {news_preview[1] if len(news_preview) > 1 else 'n/a'}",
            f"3) {news_preview[2] if len(news_preview) > 2 else 'n/a'}",
            line,
            "RECENT EVENTS",
        ]

        if self.events:
            rows.extend(list(self.events))
        else:
            rows.append("no events yet")

        if os.name == "nt":
            os.system("cls")
            print("\n".join(rows), flush=True)
        else:
            print(f"\033[2J\033[H{'\n'.join(rows)}", flush=True)

        if self.web_dashboard is not None:
            self.web_dashboard.update(
                {
                    "coin": self.coin,
                    "updated_at": now_label,
                    "timestamps": list(self.history_timestamps),
                    "prices": list(self.history_prices),
                    "account_values": list(self.history_account_values),
                    "withdrawables": list(self.history_withdrawables),
                    "position_values": list(self.history_position_values),
                    "decision_markers": list(self.decision_markers),
                    "events": list(self.events),
                    "latest": {
                        "stage": self.stage,
                        "order_status": self.order_status,
                        "required_margin": self.required_margin,
                        "available_balance": self.available_balance,
                        "market": {
                            "current_price": price,
                            "ema10": ema10,
                            "ema20": ema20,
                            "funding_rate_latest": funding_latest,
                            "funding_rate_avg": funding_avg,
                            "volatility_24h": volatility,
                            "buy_pressure": buy_pressure,
                            "volume_24h": volume_24h,
                            "open_interest": open_interest,
                        },
                        "account": metrics,
                        "decision": {
                            "action": decision_action,
                            "size": decision_size,
                            "leverage": decision_leverage,
                            "thinking": decision_thinking,
                            "llm_input": (
                                str(getattr(self.decision, "llm_input", "n/a"))
                                if self.decision is not None
                                else "n/a"
                            ),
                        },
                        "news_titles": self.major_titles[:5],
                    },
                }
            )
