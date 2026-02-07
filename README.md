# Walter

<p align="center">
  <img src="walter_logo.svg" alt="Walter logo" width="220">
</p>

<p align="center">
    <img src="https://img.shields.io/badge/Status-Prototype-orange" alt="Status: Prototype" />
    <img src="https://img.shields.io/badge/Version-0.1.0-blue" alt="Version: 0.1.0" />
    <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python: 3.10+" />
    <img src="https://img.shields.io/badge/License-MIT-green" alt="License: MIT" />
</p>

Walter is an automated trading assistant that pulls real-time market context from Hyperliquid, aggregates crypto news from multiple sources, and asks a LLM to decide whether to buy, sell, or hold. It persists every decision, market snapshot, and news summary to PostgreSQL for analysis. Designed for fast strategy prototyping, not unattended production trading.

## Features

- Aggregates Hyperliquid mid prices, candles, volume, funding, open interest, and trade pressure into a concise market snapshot.
- Fetches crypto news from CryptoPanic and CryptoCompare, then clusters articles into market narratives using sentence-transformer embeddings and DBSCAN.
- Feeds market data, account state, news summaries, and recent decision history to a LLM that returns a structured JSON decision (action, size, leverage, TIF).
- Places market or limit orders through the official Hyperliquid SDK with automatic tick-size snapping and leverage updates.
- Persists market snapshots, account snapshots, news summaries, and order attempts to a PostgreSQL database for auditability and review.
- Runs as a simple scheduler loop (configurable interval) so you can monitor output and interrupt with `Ctrl+C`.

## Requirements

- Python 3.10+
- PostgreSQL database (connection string provided via `PG_CONN_STR`).
- Hyperliquid API access (public key plus a funded wallet private key for execution).
- OpenRouter API key.
- (Optional) CryptoPanic API key and/or CryptoCompare API key for news aggregation. CryptoCompare works without an API key.

## Installation

```bash
git clone <your fork or repo url>
cd walter
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

> **Note:** Some dependencies (`psycopg`, `sentence-transformers`, `scikit-learn`) are listed in `requirements.txt` but not in `pyproject.toml`. If you need them, also run `pip install -r requirements.txt`.

## Configuration

Walter reads configuration from two places:

1. **Hardcoded defaults** in `src/walter/config.py` — scheduler interval, coin, Hyperliquid URL, LLM model, news API settings, etc.
2. **Environment variables** loaded from `.env` / `.env.local` files — secrets and connection strings.

### Secrets (`.env` / `.env.local`)

| Variable               | Purpose                                             |
| ---------------------- | --------------------------------------------------- |
| `API_WALLET_PRIVATE_KEY` | Private key that signs Hyperliquid orders.          |
| `API_WALLET_PUBLIC_KEY`  | Public key for the API wallet.                      |
| `GENERAL_PUBLIC_KEY`     | Public key used when fetching existing positions.   |
| `PG_CONN_STR`           | PostgreSQL connection string (e.g. `postgresql://user:pass@host/db`). |
| `OPENROUTER_API_KEY`     | OpenRouter API key for unified LLM access.          |
| `CP_CRYPTOPANIC_KEY`     | (Optional) CryptoPanic API key.                     |
| `CC_CRYPTOCOMPARE_KEY`   | (Optional) CryptoCompare API key.                   |

### Defaults in `config.py`

| Constant                     | Default                                          | Purpose                                        |
| ---------------------------- | ------------------------------------------------ | ---------------------------------------------- |
| `SCHEDULER_INTERVAL_SECONDS` | `4`                                              | Seconds between decision cycles.               |
| `COIN`                       | `ETH`                                            | Hyperliquid asset ticker.                       |
| `HYPERLIQUID_URL`            | `https://api.hyperliquid-testnet.xyz/info`       | Base URL for the Hyperliquid info endpoint.     |
| `LLM_MODEL`                  | `openai/gpt-oss-20b:free`                       | OpenRouter model (short name or full ID).       |
| `LLM_HISTORY_LENGTH`         | `5`                                              | Number of recent decisions fed back to the LLM. |
| `SENTENCE_TRANSFORMER_MODEL` | `all-MiniLM-L6-v2`                              | Model used for news embedding and clustering.   |
| `EPS`                        | `0.3`                                            | DBSCAN epsilon for narrative clustering.         |

Order size, leverage, and time-in-force are no longer configured statically — they are determined by the LLM on each decision cycle.

Walter uses OpenRouter to access a wide range of free and paid models. See `src/walter/LLM_API.py` for a list of popular free models you can reference by short name.

## Usage

```bash
python main.py
```

The script prints each market snapshot, open position payload, news summaries, the LLM decision (including its reasoning), and order status. Stop the loop with `Ctrl+C`.

## Development

- Core modules in `src/walter/`:
  - `config.py` — centralised configuration and secret loading.
  - `market_data.py` — Hyperliquid market snapshot builder.
  - `LLM_API.py` — OpenRouter prompt construction, API call, and response parsing.
  - `hyperliquid_API.py` — position queries and order placement.
  - `news_API_aggregator.py` — CryptoPanic and CryptoCompare news fetching.
  - `news_summerizer.py` — sentence-transformer embedding + DBSCAN narrative clustering.
  - `db_utils.py` — PostgreSQL schema initialisation and data persistence.
