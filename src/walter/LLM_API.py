from __future__ import annotations

import os
import re
from collections import deque
from dataclasses import dataclass
from typing import Any, Iterable

from google import genai


@dataclass(frozen=True)
class MemoryEntry:
    """Stores a past interaction for context."""
    market_snapshot: Any
    open_positions: Any
    decision: LLMDecision


@dataclass(frozen=True)
class MemoryEntry:
    """Stores a past interaction for context."""
    market_snapshot: Any
    open_positions: Any
    decision: LLMDecision


@dataclass(frozen=True)
class LLMDecision:
    """Represents the trading decision returned by the LLM."""

    action: str
    confidence: float
    execute: bool
    raw_response: str


class LLMAPI:
    """Utility class for creating prompts and parsing LLM responses."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gemini-flash-latest",
        buy_tokens: Iterable[str] | None = None,
        sell_tokens: Iterable[str] | None = None,
        confidence_threshold: float = 0.55,
    ) -> None:
        self.buy_tokens = tuple(
            token.lower() for token in (buy_tokens or ("buy", "long"))
        )
        self.sell_tokens = tuple(
            token.lower() for token in (sell_tokens or ("sell", "short"))
        )
        self.confidence_threshold = confidence_threshold
        self.request_timeout = request_timeout
        self.temperature = temperature
        self.history: deque[MemoryEntry] = deque(maxlen=10)
        
        # Get API key from parameter or environment
        key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not key:
            raise ValueError(
                "Gemini API key missing. Provide api_key or set GEMINI_API_KEY."
            )
        self.model = model
        self._client = genai.Client(api_key=key)

    def get_prompt(self, market_snapshot: Any, open_positions: Any) -> str:
        """Builds a concise instruction prompt for the LLM."""
        
        history_text = ""
        if self.history:
            history_text = "History of recent decisions (newest last):\n"
            for i, entry in enumerate(self.history, 1):
                history_text += (
                    f"[{i}] Market: {entry.market_snapshot} | "
                    f"Positions: {entry.open_positions} -> "
                    f"Decision: {entry.decision.action} (conf={entry.decision.confidence})\n"
                )
            history_text += "\n"

        return (
            "You are a trading assistant. Given the following market snapshot and "
            "open positions, respond with BUY, SELL, or HOLD plus an optional "
            "confidence value between 0 and 1. Include desired position size "
            "(in contracts), leverage (integer), and TIF (time-in-force) code.\n\n"
            f"{history_text}"
            f"Current Market Snapshot: {market_snapshot}\n"
            f"Current Open Positions: {open_positions}\n"
            "Answer in the format: ACTION (confidence=0.0, size=1.0, leverage=1, tif=Ioc)."
        )

    def decide(self, response: Any) -> LLMDecision:
        """Converts an arbitrary LLM response into an actionable decision."""

        response_text = self._normalize_response(response)
        action = self._infer_action(response_text)
        confidence = self._extract_confidence(response_text, action)
        execute = action != "hold" and confidence >= self.confidence_threshold
        return LLMDecision(
            action=action,
            confidence=confidence,
            execute=execute,
            raw_response=response_text,
        )

    def decide_from_market(
        self, market_snapshot: Any, open_positions: Any
    ) -> LLMDecision:
        """Calls Gemini with generated prompt and parses the response."""

        prompt = self.get_prompt(market_snapshot, open_positions)
        response = self._call_openrouter(prompt)
        decision = self.decide(response)
        
        self.history.append(
            MemoryEntry(
                market_snapshot=market_snapshot,
                open_positions=open_positions,
                decision=decision
            )
        )
        return decision

    def _normalize_response(self, response: Any) -> str:
        if isinstance(response, str):
            return response.strip()
        if isinstance(response, (dict, list, tuple)):
            return str(response)
        return str(response)

    def _infer_action(self, response_text: str) -> str:
        text = response_text.lower()
        for token in self.buy_tokens:
            if token in text:
                return "buy"
        for token in self.sell_tokens:
            if token in text:
                return "sell"
        return "hold"

    def _extract_confidence(self, response_text: str, action: str) -> float:
        match = re.search(
            r"confidence\s*=\s*(0?\.\d+|1(?:\.0+)?)", response_text.lower()
        )
        if match:
            return min(1.0, max(0.0, float(match.group(1))))
        match = re.search(r"(\d{1,3})%", response_text)
        if match:
            percentage = float(match.group(1))
            return min(1.0, max(0.0, percentage / 100))
        return 1.0 if action != "hold" else 0.0

    def _call_gemini(self, prompt: str) -> str:
        """Executes a fast Gemini API call and returns the combined text output."""

        result = self._client.models.generate_content(
            model=self.model,
            contents=prompt,
        )
        return self._collapse_response(result)

    def _collapse_response(self, result: Any) -> str:
        text = getattr(result, "text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()
        parts = getattr(result, "candidates", None)
        if isinstance(parts, list):
            chunks: list[str] = []
            for candidate in parts:
                chunk = getattr(candidate, "content", None)
                if chunk and getattr(chunk, "parts", None):
                    for part in chunk.parts:
                        part_text = getattr(part, "text", None)
                        if isinstance(part_text, str):
                            chunks.append(part_text)
            if chunks:
                return " ".join(chunks).strip()
        return str(result).strip()
