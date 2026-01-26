from __future__ import annotations

import os
import re
import json
from dataclasses import dataclass
from typing import Any, Iterable

import requests


from walter.db_utils import get_recent_decisions

# Popular free models on OpenRouter
POPULAR_MODELS = {
    # Google (Free)
    "gemini-flash": "google/gemini-2.0-flash-exp:free",
    "gemini-pro": "google/gemini-exp-1206:free",
    "gemma-2-9b": "google/gemma-2-9b-it:free",
    # DeepSeek (Free)
    "deepseek-r1": "deepseek/deepseek-r1:free",
    "deepseek-v3": "deepseek/deepseek-v3:free",
    # Meta Llama (Free)
    "llama-3.2-3b": "meta-llama/llama-3.2-3b-instruct:free",
    "llama-3.2-1b": "meta-llama/llama-3.2-1b-instruct:free",
    "llama-3.1-8b": "meta-llama/llama-3.1-8b-instruct:free",
    "llama-3.1-70b": "meta-llama/llama-3.1-70b-instruct:free",
    # Qwen (Free)
    "qwen-2.5-coder-32b": "qwen/qwen-2.5-coder-32b-instruct:free",
    "qwen-2.5-7b": "qwen/qwen-2.5-7b-instruct:free",
    # Mistral (Free)
    "mistral-7b": "mistralai/mistral-7b-instruct:free",
    # Microsoft (Free)
    "phi-3-mini": "microsoft/phi-3-mini-128k-instruct:free",
    "phi-3-medium": "microsoft/phi-3-medium-128k-instruct:free",
}


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
        model: str = "gemini-flash",
        buy_tokens: Iterable[str] | None = None,
        sell_tokens: Iterable[str] | None = None,
        request_timeout: float = 30.0,
        temperature: float = 0.2,
        history_length: int = 5,
    ) -> None:
        """
        Initialize the LLM API client using OpenRouter.

        Args:
            api_key: OpenRouter API key (or set OPENROUTER_API_KEY env var)
            model: Model name. Can be a short name from POPULAR_MODELS or full OpenRouter model ID
                  Examples: "gemini-flash", "gpt-4o-mini", "google/gemini-2.5-flash"
            buy_tokens: Tokens that indicate a buy action
        """
        self.buy_tokens = tuple(
            token.lower() for token in (buy_tokens or ("buy", "long"))
        )
        self.sell_tokens = tuple(
            token.lower() for token in (sell_tokens or ("sell", "short"))
        )
        self.request_timeout = request_timeout
        self.temperature = temperature

        # Get API key from parameter or environment
        from walter.config import OPENROUTER_API_KEY

        key = api_key or OPENROUTER_API_KEY
        if not key:
            raise ValueError(
                "OpenRouter API key missing. Provide api_key or set OPENROUTER_API_KEY."
            )
        self.api_key = key

        # Resolve model name (support both short names and full IDs)
        self.model = POPULAR_MODELS.get(model, model)

        # OpenRouter endpoint
        self.endpoint = "https://openrouter.ai/api/v1/chat/completions"

        # History length for recent decisions
        self.history_length = history_length

    def get_prompt(self, market_snapshot: Any, open_positions: Any) -> str:
        """Builds a concise instruction prompt for the LLM."""

        recent_decisions = get_recent_decisions(self.history_length)
        history_text = ""
        if recent_decisions:
            history_text = "History of recent decisions (newest last):\n"
            for i, entry in enumerate(recent_decisions, 1):
                # Handle cases where snapshot might be None if fetching failed or partial data
                m_snap = entry.get("market_snapshot", "N/A")
                a_pos = entry.get("account_snapshot", "N/A")
                action = entry.get("decision_action", "unknown")
                thinking = entry.get("thinking", "N/A")

                history_text += (
                    f"[{i}] Market: {m_snap} | "
                    f"Positions: {a_pos} -> "
                    f"Thinking: {thinking} | "
                    f"Decision: {action}\n"
                )
            history_text += "\n"

        return (
            "You are a trading assistant. Given the following market snapshot and "
            "open positions, first provide a short thinking process (max 1 sentence) "
            "starting with 'THINKING:', then the decision.\n\n"
            "Respond with BUY, SELL, or HOLD. "
            "If ACTION is not HOLD, include desired position size, leverage and tif "
            "If ACTION is BUY or SELL, provide ACTION_DETAILS with size, leverage and tif"
            f"{history_text}"
            f"Current Market Snapshot: {market_snapshot}\n"
            f"Current Open Positions: {open_positions}\n"
            "Answer in JSON format (example below):\n"
            f"""{{
            "THINKING": "Short reasoning here...",
            "ACTION": "BUY or SELL or HOLD",
            "ACTION_DETAILS": {{ 
                "size": 1.0,
                "leverage": 1,
                "tif": "Ioc"
            }}
            }}"""
        )

    def decide(self, response: Any) -> LLMDecision:
        """Converts an arbitrary LLM response into an actionable decision."""

        raw_response = str(response)
        response_data = {}

        if isinstance(response, dict):
            response_data = response
        else:
            # Clean up potential markdown formatting
            clean_text = raw_response.strip()
            if clean_text.startswith("```"):
                # Remove opening backticks and optional language identifier
                clean_text = re.sub(r"^```\w*\s*", "", clean_text)
                # Remove closing backticks
                clean_text = re.sub(r"\s*```$", "", clean_text)

            try:
                response_data = json.loads(clean_text)
            except json.JSONDecodeError:
                # If JSON parsing fails, we could fallback to regex, but for now let's rely on the prompt being strict
                # Or provide a minimal fallback
                pass

        thinking = response_data.get("THINKING")
        action = response_data.get("ACTION", "HOLD").upper()

        details = response_data.get("ACTION_DETAILS", {})
        size = details.get("size")
        leverage = details.get("leverage")
        tif = details.get("tif")

        # Normalize action
        # The prompt asks for BUY, SELL, HOLD.
        # Check against configured tokens just in case, or just map standard ones.
        # But since we switched to strict JSON, let's respect the JSON value.
        # However, to be safe with existing logic which might expect "buy", "sell":
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

    def decide_from_market(
        self, market_snapshot: Any, open_positions: Any
    ) -> LLMDecision:
        """Invokes OpenRouter with generated prompt and parses the response."""

        prompt = self.get_prompt(market_snapshot, open_positions)
        response = self._call_openrouter(prompt)
        return self.decide(response)

    def _call_openrouter(self, prompt: str) -> str:
        """Makes a request to OpenRouter API and returns the response text."""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/auxiliary-ai/walter",  # Optional: for OpenRouter rankings
            "X-Title": "Walter Trading Bot",  # Optional: app name for OpenRouter
        }

        payload = {
            "model": self.model,
            "messages": [
                # {"role": "system", "content": "You are a trading assistant."},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
        }

        response = requests.post(
            self.endpoint, headers=headers, json=payload, timeout=self.request_timeout
        )
        if not response.ok:
            print(f"OpenRouter Error: {response.status_code} - {response.text}")
        response.raise_for_status()
        return self._parse_response(response.json())

    def _parse_response(self, payload: dict) -> str:
        """Parses OpenRouter response (OpenAI-compatible format)."""

        if not isinstance(payload, dict):
            return str(payload).strip()

        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return str(payload).strip()

        choice = choices[0]
        if not isinstance(choice, dict):
            return str(payload).strip()

        # Try to get message content
        message = choice.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()

        # Fallback: try text field
        text = choice.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()

        return str(payload).strip()

    def _infer_action(self, response_text: str) -> str:
        # Simple heuristic to look for action keywords, prioritising the format "ACTION (..."
        # We search specifically in the part AFTER "THINKING:" if possible, or generally

        # Try to split by lines and look for the last ACTION line if thinking is present
        lines = response_text.lower().split("\n")
        for line in reversed(lines):
            for token in self.buy_tokens:
                if token in line:
                    return "buy"
            for token in self.sell_tokens:
                if token in line:
                    return "sell"
            if "hold" in line:
                return "hold"

        # Fallback to general search
        text = response_text.lower()
        for token in self.buy_tokens:
            if token in text:
                return "buy"
        for token in self.sell_tokens:
            if token in text:
                return "sell"
        return "hold"

    def _extract_numeric_value(self, response_text: str, key: str) -> float | None:
        pattern = rf"{re.escape(key)}\s*=\s*(-?\d+(?:\.\d+)?)"
        match = re.search(pattern, response_text, flags=re.IGNORECASE)
        if not match:
            return None
        try:
            return float(match.group(1))
        except (TypeError, ValueError):
            return None

    def _extract_tif(self, response_text: str) -> str | None:
        match = re.search(r"tif\s*=\s*([A-Za-z]+)", response_text, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            if value:
                return value[0].upper() + value[1:].lower()
        return None
