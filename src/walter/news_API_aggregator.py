import os
import requests
from typing import List, Dict, Optional
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
for dotenv_file in (".env.local", ".env"):
    load_dotenv(dotenv_path=dotenv_file, override=False)

CP_URL = os.getenv("CP_URL")
CP_CRYPTOPANIC_KEY = os.getenv("CP_CRYPTOPANIC_KEY")
CP_CURRENCIES = os.getenv("CP_CURRENCIES")
CP_FILTER = os.getenv("CP_FILTER")
CP_KIND = os.getenv("CP_KIND")
CC_URL = os.getenv("CC_URL")
CC_CRYPTOCOMPARE_KEY = os.getenv("CC_CRYPTOCOMPARE_KEY")
CC_CATEGORIES = os.getenv("CC_CATEGORIES")
CC_FEEDS = os.getenv("CC_FEEDS")
CC_SORT = os.getenv("CC_SORT")


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
            print(f"Error fetching data: {e}")
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
                    print(f"[CryptoPanic] Skipping article: {e}")
            print(f"[CryptoPanic] Fetched {len(articles)} articles")
            return articles

        except Exception as e:
            print(f"[CryptoPanic] Fatal error: {e}")
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
            print(f"[CryptoPanic] Skipping article: {e}")
            return {}


class CryptoCompareNews(CryptoNewsAPI):
    """Fetch news from CryptoCompare API."""

    BASE_URL = CC_URL

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key)
        if api_key:
            self.session.headers.update({"authorization": f"Apikey {api_key}"})

    def get_news(
        self,
        feeds: Optional[str] = None,
        categories: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> List[Dict]:
        """
        Fetch news from CryptoCompare.

        Args:
            feeds: Comma-separated feed names (e.g., 'cointelegraph,coindesk')
            categories: Comma-separated categories (e.g., 'BTC,ETH,Trading')
            sort_order: 'latest' or 'popular'
            limit: Number of results (max 100)

        Returns:
            List of news articles
        """
        try:
            params = {}

            if feeds:
                params["feeds"] = feeds
            if categories:
                params["categories"] = categories
            if sort_order:
                params["sortOrder"] = sort_order

            data = self._make_request(self.BASE_URL, params)
            results = data.get("Data", [])
            print(f"[CryptoCompare] Fetched {len(results)} articles")
            return [self._format_article(article) for article in results]
        except Exception as e:
            print(f"[CryptoCompare] Error fetching news: {e}")
            return []

    def _format_article(self, article: Dict) -> Dict:
        """Format CryptoCompare article data."""
        try:
            return {
                "source": "CryptoCompare",
                "title": article.get("title", ""),
                "url": article.get("url", ""),
                "published_at": datetime.fromtimestamp(
                    article.get("published_on", 0)
                ).isoformat(),
                "body": article.get("body") or "",
                "categories": article.get("categories", "").split("|"),
                "source_name": article.get("source", ""),
            }
        except Exception as e:
            print(f"[CryptoCompare] Skipping article: {e}")
            return {}


class CryptoNewsAggregator:
    """Aggregate news from multiple sources."""

    def __init__(
        self,
        cryptopanic_key: Optional[str] = None,
        cryptocompare_key: Optional[str] = None,
    ):
        self.cryptopanic_key = cryptopanic_key
        self.cryptocompare_key = cryptocompare_key

    def get_all_news(
        self,
        cp_currencies: Optional[str],
        cp_filter: str,
        cp_kind: str,
        cc_categories: Optional[str],
        cc_feeds: Optional[str],
        cc_sort: str,
    ) -> List[Dict]:
        """
        Fetch news from all configured sources.

        Args:
            cp_currencies: CryptoPanic currencies (e.g., 'BTC,ETH')
            cp_filter: CryptoPanic filter type
            cp_kind: CryptoPanic kind
            cc_categories: CryptoCompare categories (e.g., 'BTC,ETH')
            cc_feeds: CryptoCompare feeds (e.g., 'cointelegraph,coindesk')
            cc_sort: CryptoCompare sort order ('latest' or 'popular')

        Returns:
            Combined list of news articles
        """
        all_news = []

        # Fetch from CryptoPanic
        if self.cryptopanic_key:
            print("=== Fetching from CryptoPanic ===")
            cp = CryptoPanicNews(self.cryptopanic_key)
            cp_news = cp.get_news(
                currencies=cp_currencies,
                filter_type=cp_filter,
                kind=cp_kind,
            )
            all_news.extend(cp_news)

        # Fetch from CryptoCompare
        if self.cryptocompare_key or True:  # CryptoCompare works without key
            print("\n=== Fetching from CryptoCompare ===")
            cc = CryptoCompareNews(self.cryptocompare_key)
            cc_news = cc.get_news(
                categories=cc_categories,
                feeds=cc_feeds,
                sort_order=cc_sort,
            )
            all_news.extend(cc_news)

        # Sort by published date (newest first)
        all_news.sort(key=lambda x: x.get("published_at", ""), reverse=True)

        return all_news

    def getAggregatedNews():
        print("\n=== Aggregated News ===")
        aggregator = CryptoNewsAggregator(
            cryptopanic_key=CP_CRYPTOPANIC_KEY, cryptocompare_key=CC_CRYPTOCOMPARE_KEY
        )
        all_news = aggregator.get_all_news(
            cp_currencies=CP_CURRENCIES,
            cp_filter=CP_FILTER,
            cp_kind=CP_KIND,
            cc_categories=CC_CATEGORIES,
            cc_feeds=CC_FEEDS,
            cc_sort=CC_SORT,
        )
        return all_news
