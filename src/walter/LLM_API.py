from __future__ import annotations

import logging
import re
import json
from dataclasses import dataclass
from typing import Any

import requests

from walter.db_utils import get_recent_decisions

logger = logging.getLogger(__name__)

# Stable system prompt — sent once per API call as the system role.
# Keeps instructions out of the user message to reduce per-call token usage.
SYSTEM_PROMPT = (
    "You are a crypto perpetual-futures trading assistant. "
    "Given market data, account state, news headlines, and recent decision history, "
    "decide whether to BUY, SELL, or HOLD.\n"
    "Rules:\n"
    "- Never propose an order whose required margin (size × price / leverage) "
    "exceeds the withdrawable balance. If balance is too low, respond HOLD.\n"
    "- Positive news may support BUY; negative news may support SELL or HOLD.\n"
    "Respond ONLY with valid JSON — no markdown, no commentary:\n"
    '{"THINKING":"<1 sentence>","ACTION":"BUY|SELL|HOLD",'
    '"ACTION_DETAILS":{"size":<float>,"leverage":<int>,"tif":"Ioc"}}\n'
    "Omit ACTION_DETAILS when ACTION is HOLD."
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
        """Compact history table: price | withdrawable | action | thinking."""
        rows = get_recent_decisions(self.history_length)
        if not rows:
            return ""

        lines = ["Recent decisions (oldest → newest):"]
        for i, r in enumerate(rows, 1):
            price = r.get("current_price", "?")
            avail = r.get("withdrawable", "?")
            action = r.get("decision_action", "?")
            thought = r.get("thinking") or "-"
            lines.append(f"  {i}. price={price} avail={avail} → {action} ({thought})")
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
        parts.append(f"Account: {open_positions}")

        if news_titles:
            parts.append(f"News: {', '.join(news_titles)}")
        else:
            parts.append("News: none")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def decide(self, response: Any) -> LLMDecision:
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

        execute = normalized_action != "hold"

        return LLMDecision(
            action=normalized_action,
            thinking=thinking,
            execute=execute,
            raw_response=raw_response,
            size=float(size) if size is not None else None,
            leverage=int(leverage) if leverage is not None else None,
            tif=tif,
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
        return self.decide(response)

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
