import os
from dotenv import load_dotenv

# Load environment variables (secrets)
for dotenv_file in (".env.local", ".env"):
    load_dotenv(dotenv_path=dotenv_file, override=False)

# Configuration Constants
SCHEDULER_INTERVAL_SECONDS = 900
COIN = "ETH"
HYPERLIQUID_URL = "https://api.hyperliquid-testnet.xyz/info"

# LLM Configuration
LLM_MODEL = "openai/gpt-5.4"
LLM_HISTORY_LENGTH = 5

# CryptoPanic Configuration
CP_URL = "https://cryptopanic.com/api/developer/v2/posts/"
CP_CURRENCIES = "ETH"
CP_FILTER = "important"
CP_KIND = "news"

# CryptoCompare / CoinDesk Configuration
CC_URL = "https://data-api.coindesk.com/news/v1/article/list"
CC_CATEGORIES = "ETH"
CC_LANG = "EN"
CC_LIMIT = 10

# News Summarizer Configuration
SENTENCE_TRANSFORMER_MODEL = "all-MiniLM-L6-v2"
EPS = 0.5

# Secrets (read from env)
API_WALLET_PRIVATE_KEY = os.getenv("API_WALLET_PRIVATE_KEY")
API_WALLET_PUBLIC_KEY = os.getenv("API_WALLET_PUBLIC_KEY")
GENERAL_PUBLIC_KEY = os.getenv("GENERAL_PUBLIC_KEY")

SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "walter.db")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

CP_CRYPTOPANIC_KEY = os.getenv("CP_CRYPTOPANIC_KEY")
CC_CRYPTOCOMPARE_KEY = os.getenv("CC_CRYPTOCOMPARE_KEY")
