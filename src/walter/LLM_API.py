from __future__ import annotations

import logging
import re
import json
from dataclasses import dataclass
from typing import Any

import requests

from walter.db_utils import get_recent_decisions
from walter.config import SCHEDULER_INTERVAL_SECONDS

logger = logging.getLogger(__name__)

# Stable system prompt — sent once per API call as the system role.
# Keeps instructions out of the user message to reduce per-call token usage.
SYSTEM_PROMPT = (
    "You are a disciplined ETH perpetual-futures trader managing a {total_session_hours}-hour session. "
    "We check in every {interval_minutes} minutes. "
    "You are at check-in #{current_cycle} of {total_cycles}. "
    "Your objective is to maximize total REALISED profit by the end of the session, not to avoid emotional pain, not to defend past decisions, and not to always be in a trade.\n\n"

    "You receive:\n"
    "- market data for ETH\n"
    "- current account state\n"
    "- current open position, if any\n"
    "- recent decision history\n"
    "- recent news headlines/summaries\n\n"

    "You must decide exactly one action:\n"
    "- BUY: open a long only when long conditions are valid\n"
    "- SELL: open a short only when short conditions are valid\n"
    "- HOLD: take no new action\n"
    "- CLOSE: close the full current open position\n\n"

    "Primary principle:\n"
    "- Price structure and order-flow matter more than narrative.\n"
    "- Do NOT fight the tape with weak news-based opinions.\n"
    "- Do NOT HOLD a losing trade merely to avoid realizing a loss.\n"
    "- Do NOT force a reversal trade without clear evidence.\n"
    "- Your job is to choose the highest expected-value action over the next {interval_minutes} minutes.\n\n"

    "Decision framework:\n"
    "1. First determine regime from market structure.\n"
    "2. Then evaluate whether you are flat, long, or short.\n"
    "3. Then choose the highest-EV action after fees.\n"
    "4. Prefer strong directional trades over weak mean-reversion guesses.\n\n"

    "Regime rules:\n"
    "- Strong bull regime when price > ema10 > ema20 AND net_volume > 0.\n"
    "- Strong bear regime when price < ema10 < ema20 AND net_volume < 0.\n"
    "- Mixed regime otherwise.\n"
    "- In strong bull regime, SELL is strongly disfavored unless there is a clear reversal signal.\n"
    "- In strong bear regime, BUY is strongly disfavored unless there is a clear reversal signal.\n"
    "- A 'clear reversal signal' requires more than one weak clue. Do not invent reversals from hope.\n\n"

    "Flat-position rules:\n"
    "- If no position is open:\n"
    "  - In strong bull regime: choose BUY or HOLD.\n"
    "  - In strong bear regime: choose SELL or HOLD.\n"
    "  - In mixed regime: HOLD unless expected edge is clearly positive after fees.\n"
    "- Never BUY in a strong bear regime just because price already fell.\n"
    "- Never SELL in a strong bull regime just because price already rose.\n"
    "- HOLD is correct when the edge is unclear or too small after costs.\n\n"

    "Open long rules:\n"
    "- If you are long:\n"
    "  - CLOSE when the long thesis is invalidated.\n"
    "  - CLOSE when price is below ema10 and sell pressure is negative enough to suggest worsening downside.\n"
    "  - CLOSE when the market shifts into a strong bear regime unless there is strong contrary evidence.\n"
    "  - CLOSE profitable longs when momentum stalls and further upside within the next {interval_minutes} minutes is not attractive.\n"
    "- Do not HOLD a long only because you hope it will recover.\n\n"

    "Open short rules:\n"
    "- If you are short:\n"
    "  - CLOSE when the short thesis is invalidated.\n"
    "  - CLOSE when price reclaims ema10 with sustained buying pressure.\n"
    "  - CLOSE when the market shifts into a strong bull regime unless there is strong contrary evidence.\n"
    "  - CLOSE profitable shorts when downside momentum stalls and further downside within the next {interval_minutes} minutes is not attractive.\n\n"

    "News handling rules:\n"
    "- Use only ETH-relevant, market-relevant, recent news.\n"
    "- Ignore irrelevant headlines, low-signal headlines, generic crypto noise, predictions, sponsored content, and non-ETH stories.\n"
    "- News may support a trade only when it aligns with market structure or meaningfully changes expected short-term volatility.\n"
    "- Never override clear bearish structure with weak bullish headlines.\n"
    "- Never override clear bullish structure with weak bearish headlines.\n\n"

    "History handling rules:\n"
    "- Use recent decision history to avoid repeating failed trade logic.\n"
    "- After a losing long in a bear regime, do not immediately re-enter another long without strong new evidence.\n"
    "- After a losing short in a bull regime, do not immediately re-enter another short without strong new evidence.\n"
    "- Do not revenge trade.\n\n"

    "Sizing and leverage rules:\n"
    "- Never propose an order whose required margin exceeds withdrawable balance.\n"
    "- Size should reflect conviction and expected move after fees.\n"
    "- Use larger size only when regime is strong and alignment is high.\n"
    "- Use smaller size or HOLD when signal quality is weaker.\n"
    "- Do not use aggressive leverage on mixed or low-conviction setups.\n"
    "- Take no trade when expected edge after fees is too small.\n\n"

    "Anti-bias rules:\n"
    "- You must actively consider SELL as a valid profit-seeking action.\n"
    "- You are not a long-only trader.\n"
    "- You are not rewarded for activity; HOLD is acceptable.\n"
    "- You are not rewarded for being optimistic; you are rewarded only for realized profit.\n\n"

    "Output rules:\n"
    "- Respond ONLY with valid JSON.\n"
    "- No markdown.\n"
    "- No explanation outside JSON.\n"
    "- THINKING must be exactly one sentence and must mention the main market reason for the action.\n"
    "- ACTION must be one of BUY, SELL, HOLD, CLOSE.\n"
    '- Include ACTION_DETAILS only for BUY or SELL.\n'
    '- ACTION_DETAILS must contain: {{"size": <float>, "leverage": <int>, "tif": "Ioc"}}.\n'
    '- Omit ACTION_DETAILS for HOLD and CLOSE.\n\n'

    'Return exactly this shape:\n'
    '{{"THINKING":"<1 sentence>","ACTION":"BUY|SELL|HOLD|CLOSE","ACTION_DETAILS":{{"size":<float>,"leverage":<int>,"tif":"Ioc"}}}}'

)


@dataclass(frozen=True)
class LLMDecision:
    """Represents the trading decision returned by the LLM."""

    action: str
    thinking: str | None
    execute: bool
    raw_response: str
    size: float | None
    leverage: int | None
    tif: str | None
    llm_input: str | None


class LLMAPI:
    """Utility class for creating prompts and parsing LLM responses via OpenRouter."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str,
        request_timeout: float = 30.0,
        temperature: float = 0.2,
        history_length: int = 5,
    ) -> None:
        """
        Initialize the LLM API client using OpenRouter.

        Args:
            api_key: OpenRouter API key (or set OPENROUTER_API_KEY env var)
            model: Full OpenRouter model ID (e.g. "openai/gpt-oss-20b:free")
            request_timeout: HTTP request timeout in seconds
            temperature: Sampling temperature for the LLM
            history_length: Number of recent decisions to include in context
        """
        self.request_timeout = request_timeout
        self.temperature = temperature

        from walter.config import OPENROUTER_API_KEY

        key = api_key or OPENROUTER_API_KEY
        if not key:
            raise ValueError(
                "OpenRouter API key missing. Provide api_key or set OPENROUTER_API_KEY."
            )
        self.api_key = key

        self.model = model
        self.endpoint = "https://openrouter.ai/api/v1/chat/completions"
        self.history_length = history_length

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------

    def _build_history_block(self) -> str:
        """Compact history table with price deltas for P&L feedback."""
        rows = get_recent_decisions(self.history_length)
        if not rows:
            return ""

        lines = ["Recent decisions (oldest → newest):"]
        prev_price = None
        for i, r in enumerate(rows, 1):
            price = r.get("current_price")
            avail = r.get("withdrawable", "?")
            action = r.get("decision_action", "?")
            thought = r.get("thinking") or "-"

            # Price delta vs previous decision
            if price is not None and prev_price is not None and prev_price != 0:
                delta_pct = (price - prev_price) / prev_price * 100
                delta_str = f"Δ={delta_pct:+.2f}%"
            else:
                delta_str = "Δ=n/a"

            lines.append(
                f"  {i}. price={price or '?'} {delta_str} avail={avail} → {action} ({thought})"
            )
            if price is not None:
                prev_price = price
        return "\n".join(lines)

    @staticmethod
    def _format_account_summary(account_snapshot: dict) -> str:
        """Format the raw clearinghouse state into a concise, LLM-friendly string."""
        margin = account_snapshot.get("marginSummary", {})
        account_value = margin.get("accountValue", "?")
        withdrawable = account_snapshot.get("withdrawable", "?")

        lines = [f"Account: value={account_value} withdrawable={withdrawable}"]

        # Format each open position
        positions = account_snapshot.get("assetPositions", [])
        if not positions:
            lines.append("Open positions: none")
        else:
            for ap in positions:
                pos = ap.get("position", ap)
                coin = pos.get("coin", "?")
                szi = pos.get("szi", "0")
                entry_px = pos.get("entryPx", "?")
                unrealised_pnl = pos.get("unrealizedPnl", "?")
                leverage_info = pos.get("leverage", {})
                lev_val = leverage_info.get("value", "?") if isinstance(leverage_info, dict) else leverage_info
                liq_px = pos.get("liquidationPx", "?")

                try:
                    size_f = float(szi)
                    side = "LONG" if size_f > 0 else "SHORT" if size_f < 0 else "FLAT"
                    size_str = f"{abs(size_f)}"
                except (ValueError, TypeError):
                    side = "?"
                    size_str = str(szi)

                lines.append(
                    f"  Position: {side} {size_str} {coin} @ entry={entry_px} "
                    f"unrealised_pnl={unrealised_pnl} lev={lev_val} liq={liq_px}"
                )

        return "\n".join(lines)

    def get_prompt(
        self,
        market_snapshot: Any,
        open_positions: Any,
        news_titles: list[str] | None = None,
    ) -> str:
        """Build a token-efficient user prompt with only variable data."""
        parts: list[str] = []

        history = self._build_history_block()
        if history:
            parts.append(history)

        parts.append(f"Market: {market_snapshot}")

        if isinstance(open_positions, dict):
            parts.append(self._format_account_summary(open_positions))
        else:
            parts.append(f"Account: {open_positions}")

        if news_titles:
            parts.append(f"News: {', '.join(news_titles)}")
        else:
            parts.append("News: none")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def decide(self, response: Any, llm_input: str | None = None) -> LLMDecision:
        """Converts an arbitrary LLM response into an actionable decision."""
        raw_response = str(response)
        response_data: dict = {}

        if isinstance(response, dict):
            response_data = response
        else:
            clean_text = raw_response.strip()
            # Strip markdown code fences if present
            if clean_text.startswith("```"):
                clean_text = re.sub(r"^```\w*\s*", "", clean_text)
                clean_text = re.sub(r"\s*```$", "", clean_text)

            try:
                response_data = json.loads(clean_text)
            except json.JSONDecodeError:
                logger.warning(
                    "Failed to parse LLM response as JSON: %s", clean_text[:200]
                )

        thinking = response_data.get("THINKING")
        action = response_data.get("ACTION", "HOLD").upper()

        details = response_data.get("ACTION_DETAILS", {})
        size = details.get("size")
        leverage = details.get("leverage")
        tif = details.get("tif")

        normalized_action = "hold"
        if action in ("BUY", "LONG"):
            normalized_action = "buy"
        elif action in ("SELL", "SHORT"):
            normalized_action = "sell"
        elif action == "CLOSE":
            normalized_action = "close"

        execute = normalized_action not in ("hold",)

        return LLMDecision(
            action=normalized_action,
            thinking=thinking,
            execute=execute,
            raw_response=raw_response,
            size=float(size) if size is not None else None,
            leverage=int(leverage) if leverage is not None else None,
            tif=tif,
            llm_input=llm_input,
        )

    # ------------------------------------------------------------------
    # End-to-end flow
    # ------------------------------------------------------------------

    def decide_from_market(
        self,
        market_snapshot: Any,
        open_positions: Any,
        news_titles: list[str] | None = None,
        current_cycle: int = 1,
        total_cycles: int = 1,
    ) -> LLMDecision:
        """Invokes OpenRouter with generated prompt and parses the response."""
        prompt = self.get_prompt(market_snapshot, open_positions, news_titles)
        response = self._call_openrouter(prompt, current_cycle=current_cycle, total_cycles=total_cycles)
        return self.decide(response, llm_input=prompt)

    # ------------------------------------------------------------------
    # OpenRouter HTTP
    # ------------------------------------------------------------------

    def _call_openrouter(self, prompt: str, current_cycle: int = 1, total_cycles: int = 1) -> str:
        """Makes a request to OpenRouter API and returns the response text."""
        from walter.config import TOTAL_SESSION_HOURS, SCHEDULER_INTERVAL_SECONDS
        
        interval_minutes = SCHEDULER_INTERVAL_SECONDS // 60
        formatted_system_prompt = SYSTEM_PROMPT.format(
            total_session_hours=TOTAL_SESSION_HOURS,
            interval_minutes=interval_minutes,
            current_cycle=current_cycle,
            total_cycles=total_cycles,
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/auxiliary-ai/walter",
            "X-Title": "Walter Trading Bot",
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": formatted_system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
        }

        response = requests.post(
            self.endpoint, headers=headers, json=payload, timeout=self.request_timeout
        )
        if not response.ok:
            logger.error(
                "OpenRouter Error: %d - %s", response.status_code, response.text
            )
        response.raise_for_status()
        return self._parse_response(response.json())

    @staticmethod
    def _parse_response(payload: dict) -> str:
        """Parses OpenRouter response (OpenAI-compatible format)."""
        if not isinstance(payload, dict):
            return str(payload).strip()

        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return str(payload).strip()

        choice = choices[0]
        if not isinstance(choice, dict):
            return str(payload).strip()

        message = choice.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()

        text = choice.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()

        return str(payload).strip()
