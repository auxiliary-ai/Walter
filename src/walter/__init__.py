"""Top-level package for the Walter trading toolkit."""

from .LLM_API import LLMAPI, LLMDecision
from .hyperliquid_API import GetOpenPositionDetails, PlaceOrder
from .market_data import GetMarketSnapshot
from .news_API_aggregator import CryptoNewsAggregator

__all__ = [
    "LLMAPI",
    "LLMDecision",
    "GetOpenPositionDetails",
    "PlaceOrder",
    "GetMarketSnapshot",
    "CryptoNewsAggregator",
]

__version__ = "0.1.0"
