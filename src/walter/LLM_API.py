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
    "You are an elite crypto perpetual-futures trader whose SOLE objective is to "
    "maximise realised profit over the next {interval} seconds. "
    "You will be evaluated exclusively on the P&L generated between NOW and the "
    "next decision cycle — every decision you make must target the highest expected "
    "profit within that window.\n"
    "Given market data, account state (including any open position), news headlines, "
    "and recent decision history, decide whether to BUY, SELL, HOLD, or CLOSE.\n"
    "Strategy guidelines:\n"
    "- BUY when you expect price to rise enough within {interval}s to yield a net "
    "profit after fees. Size your position to maximise expected dollar gain.\n"
    "- SELL when you expect price to drop within {interval}s. Size accordingly.\n"
    "- CLOSE when you have an open position and want to realise profit (take-profit) "
    "or cut losses (stop-loss). The full position will be closed automatically.\n"
    "- HOLD only when neither direction offers a high-probability profitable trade "
    "within {interval}s, or when the withdrawable balance is too low and no "
    "position is open to close.\n"
    "Risk rules:\n"
    "- Never propose an order whose required margin (size × price / leverage) "
    "exceeds the withdrawable balance. If balance is too low, respond HOLD or CLOSE.\n"
    "- Use leverage aggressively when conviction is high, conservatively when it "
    "is low — always aim for the best risk-adjusted return within {interval}s.\n"
    "- Factor in recent decision history to avoid doubling down on losing streaks "
    "and to compound winning momentum.\n"
    "- Positive news may support BUY; negative news may support SELL, HOLD, or CLOSE.\n"
    "- If the open position has unrealised losses and you expect them to worsen, CLOSE.\n"
    "Respond ONLY with valid JSON — no markdown, no commentary:\n"
    '{{"THINKING":"<1 sentence>","ACTION":"BUY|SELL|HOLD|CLOSE",'
    '"ACTION_DETAILS":{{"size":<float>,"leverage":<int>,"tif":"Ioc"}}}}\n'
    "Omit ACTION_DETAILS when ACTION is HOLD or CLOSE."
).format(interval=SCHEDULER_INTERVAL_SECONDS)


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
    ) -> LLMDecision:
        """Invokes OpenRouter with generated prompt and parses the response."""
        prompt = self.get_prompt(market_snapshot, open_positions, news_titles)
        response = self._call_openrouter(prompt)
        return self.decide(response, llm_input=prompt)

    # ------------------------------------------------------------------
    # OpenRouter HTTP
    # ------------------------------------------------------------------

    def _call_openrouter(self, prompt: str) -> str:
        """Makes a request to OpenRouter API and returns the response text."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/auxiliary-ai/walter",
            "X-Title": "Walter Trading Bot",
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
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
