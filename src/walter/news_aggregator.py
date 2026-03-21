import logging
import requests
from typing import List, Dict, Optional
from datetime import datetime

from walter.config import (
    CP_URL,
    CP_CRYPTOPANIC_KEY,
    CP_CURRENCIES,
    CP_FILTER,
    CP_KIND,
    CC_URL,
    CC_CATEGORIES,
    CC_LANG,
    CC_LIMIT,
)

logger = logging.getLogger(__name__)


class CryptoNewsAPI:
    """Base class for crypto news API clients."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.session = requests.Session()

    def _make_request(self, url: str, params: Optional[Dict] = None) -> Dict:
        """Make HTTP GET request with error handling."""
        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error("Error fetching data: %s", e)
            return {}


class CryptoPanicNews(CryptoNewsAPI):
    """Fetch news from CryptoPanic API."""

    BASE_URL = CP_URL

    def __init__(self, api_key: str):
        super().__init__(api_key)

    def get_news(
        self, currencies: Optional[str], filter_type: str, kind: str
    ) -> List[Dict]:
        try:
            params = {
                "auth_token": self.api_key,
                "filter": filter_type,
                "public": "true",
                "kind": kind,
            }
            if currencies:
                params["currencies"] = currencies

            data = self._make_request(self.BASE_URL, params)
            results = data.get("results", [])

            articles = []
            for article in results:
                try:
                    articles.append(self._format_article(article))
                except Exception as e:
                    logger.warning("[CryptoPanic] Skipping article: %s", e)
            logger.info("[CryptoPanic] Fetched %d articles", len(articles))
            return articles

        except Exception as e:
            logger.error("[CryptoPanic] Fatal error: %s", e)
            return []

    def _format_article(self, article: Dict) -> Dict:
        """Format CryptoPanic article data."""
        try:
            return {
                "source": "CryptoPanic",
                "title": article.get("title", ""),
                "url": article.get("url", ""),
                "published_at": article.get("published_at", ""),
                "body": article.get("description") or "",
                "domain": article.get("domain", ""),
                "currencies": [c.get("code") for c in article.get("currencies", [])],
                "votes": article.get("votes", {}),
            }
        except Exception as e:
            logger.warning("[CryptoPanic] Skipping article: %s", e)
            return {}


class CryptoCompareNews(CryptoNewsAPI):
    """Fetch news from CoinDesk / CryptoCompare data API."""

    BASE_URL = CC_URL

    def __init__(self):
        super().__init__(api_key=None)
        self.session.headers.update(
            {"Content-type": "application/json; charset=UTF-8"}
        )

    def get_news(
        self,
        categories: Optional[str] = None,
        lang: str = "EN",
        limit: int = 10,
    ) -> List[Dict]:
        """
        Fetch news from CoinDesk data API.

        Args:
            categories: Comma-separated categories (e.g., 'ETH')
            lang: Language code (default 'EN')
            limit: Max articles to return

        Returns:
            List of news articles
        """
        try:
            params: Dict = {"lang": lang, "limit": limit}
            if categories:
                params["categories"] = categories

            data = self._make_request(self.BASE_URL, params)
            results = data.get("Data", [])
            logger.info("[CryptoCompare] Fetched %d articles", len(results))
            return [self._format_article(article) for article in results]
        except Exception as e:
            logger.error("[CryptoCompare] Error fetching news: %s", e)
            return []

    def _format_article(self, article: Dict) -> Dict:
        """Format CoinDesk article data (uppercase field names)."""
        try:
            source_data = article.get("SOURCE_DATA", {})
            category_data = article.get("CATEGORY_DATA", [])
            categories = [c.get("CATEGORY", "") for c in category_data]

            return {
                "source": "CryptoCompare",
                "title": article.get("TITLE", ""),
                "url": article.get("URL", ""),
                "published_at": datetime.fromtimestamp(
                    article.get("PUBLISHED_ON", 0)
                ).isoformat(),
                "body": article.get("BODY") or "",
                "categories": categories,
                "source_name": source_data.get("NAME", ""),
                "sentiment": article.get("SENTIMENT", ""),
            }
        except Exception as e:
            logger.warning("[CryptoCompare] Skipping article: %s", e)
            return {}


class CryptoNewsAggregator:
    """Aggregate news from multiple sources."""

    def __init__(
        self,
        cryptopanic_key: Optional[str] = None,
    ):
        self.cryptopanic_key = cryptopanic_key

    def get_all_news(
        self,
        cp_currencies: Optional[str],
        cp_filter: str,
        cp_kind: str,
        cc_categories: Optional[str],
        cc_lang: str = "EN",
        cc_limit: int = 10,
    ) -> List[Dict]:
        """
        Fetch news from all configured sources.

        Args:
            cp_currencies: CryptoPanic currencies (e.g., 'BTC,ETH')
            cp_filter: CryptoPanic filter type
            cp_kind: CryptoPanic kind
            cc_categories: CoinDesk categories (e.g., 'ETH')
            cc_lang: CoinDesk language code
            cc_limit: CoinDesk max articles

        Returns:
            Combined list of news articles
        """
        all_news = []

        # Fetch from CryptoPanic
        if self.cryptopanic_key:
            logger.info("=== Fetching from CryptoPanic ===")
            cp = CryptoPanicNews(self.cryptopanic_key)
            cp_news = cp.get_news(
                currencies=cp_currencies,
                filter_type=cp_filter,
                kind=cp_kind,
            )
            all_news.extend(cp_news)

        # Fetch from CoinDesk / CryptoCompare (no API key needed)
        logger.info("=== Fetching from CoinDesk ===")
        cc = CryptoCompareNews()
        cc_news = cc.get_news(
            categories=cc_categories,
            lang=cc_lang,
            limit=cc_limit,
        )
        all_news.extend(cc_news)

        # Sort by published date (newest first)
        all_news.sort(key=lambda x: x.get("published_at", ""), reverse=True)

        return all_news

    @staticmethod
    def get_aggregated_news():
        """Convenience method to fetch aggregated news using config values."""
        logger.info("=== Aggregated News ===")
        aggregator = CryptoNewsAggregator(
            cryptopanic_key=CP_CRYPTOPANIC_KEY,
        )
        all_news = aggregator.get_all_news(
            cp_currencies=CP_CURRENCIES,
            cp_filter=CP_FILTER,
            cp_kind=CP_KIND,
            cc_categories=CC_CATEGORIES,
            cc_lang=CC_LANG,
            cc_limit=CC_LIMIT,
        )
        return all_news
