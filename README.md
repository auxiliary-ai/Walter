# Walter 🤖

<p align="center">
  <img src="walter_logo.svg" alt="Walter logo" width="220">
</p>

<p align="center">
    <img src="https://img.shields.io/badge/Status-Prototype-orange" alt="Status: Prototype" />
    <img src="https://img.shields.io/badge/Version-0.1.0-blue" alt="Version: 0.1.0" />
    <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python: 3.10+" />
    <img src="https://img.shields.io/badge/License-MIT-green" alt="License: MIT" />
</p>

Walter is an automated crypto trading assistant for Hyperliquid. It combines market data, account state, and aggregated news narratives, then asks an LLM whether to buy, sell, hold, or close. Every cycle is persisted to SQLite for later analysis. This is a prototype for supervised strategy experimentation, not unattended production trading.

## Quick Start

1. Clone the repo and install dependencies:
   ```bash
   git clone <your fork or repo url>
   cd walter
   python -m venv .venv && source .venv/bin/activate
   pip install -e .
   ```
2. Create a `.env` file with your secrets. See `src/walter/config.py` for the full set of supported variables.
3. Run the scheduler:
   ```bash
   python main.py
   ```

The web dashboard is available by default at `http://127.0.0.1:8765`.

## How It Works

Walter runs a loop every few seconds:

1. It fetches Hyperliquid market data and aggregates crypto news into major narratives.
2. It sends market context, account state, recent history, and narratives to the LLM.
3. It validates the returned decision and places or closes orders when appropriate.
4. It stores account snapshots, market snapshots, news summaries, and order attempts in `walter.db`.

## Features

- Aggregates Hyperliquid mid prices, candles, volume, funding, open interest, and trade pressure into a concise market snapshot.
- Fetches crypto news from CryptoPanic and CryptoCompare, then clusters articles into market narratives using TF-IDF vectors and DBSCAN.
- Feeds market data, account state, news summaries, and recent decision history to a LLM that returns a structured JSON decision with action, size, leverage, and time-in-force.
- Places market or limit orders through the Hyperliquid SDK with tick-size snapping and leverage updates.
- Supports position closing flows in addition to buy, sell, and hold decisions.
- Persists snapshots and order attempts to a local SQLite database for auditability and review.
- Serves a localhost web dashboard with price and account charts, news context, and decision traceability.

## Requirements

- Python 3.10+
- Hyperliquid API access with a funded execution wallet
- OpenRouter API key
- Optional CryptoPanic and CryptoCompare API keys for richer news coverage

## Installation

```bash
git clone <your fork or repo url>
cd walter
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

If you prefer the requirements file:

```bash
pip install -r requirements.txt
```

## Configuration

Walter reads configuration from two places:

1. Defaults in `src/walter/config.py`
2. Environment variables loaded from `.env` or `.env.local`

### Secrets

| Variable | Purpose |
| --- | --- |
| `API_WALLET_PRIVATE_KEY` | Private key that signs Hyperliquid orders. |
| `API_WALLET_PUBLIC_KEY` | Public key for the API wallet. |
| `GENERAL_PUBLIC_KEY` | Public key used when fetching existing positions. |
| `SQLITE_DB_PATH` | Path to the SQLite database file. Defaults to `walter.db`. |
| `OPENROUTER_API_KEY` | OpenRouter API key for LLM access. |
| `CP_CRYPTOPANIC_KEY` | Optional CryptoPanic API key. |
| `CC_CRYPTOCOMPARE_KEY` | Optional CryptoCompare API key. |

### Key Defaults

| Constant | Default | Purpose |
| --- | --- | --- |
| `SCHEDULER_INTERVAL_SECONDS` | `4` | Seconds between decision cycles. |
| `COIN` | `ETH` | Hyperliquid asset ticker. |
| `HYPERLIQUID_URL` | `https://api.hyperliquid-testnet.xyz/info` | Base URL for the Hyperliquid info endpoint. |
| `LLM_MODEL` | `openai/gpt-oss-20b:free` | OpenRouter model ID. |
| `LLM_HISTORY_LENGTH` | `5` | Number of recent decisions fed back to the LLM. |
| `EPS` | `0.3` | DBSCAN epsilon for narrative clustering. |

Order size, leverage, and time-in-force are determined by the LLM on each decision cycle.

## Usage

```bash
python main.py
```

The script prints market snapshots, news summaries, LLM decisions, and order status. Stop the loop with `Ctrl+C`.

Walter also serves a browser dashboard by default:

- URL: `http://127.0.0.1:8765`
- API: `http://127.0.0.1:8765/api/state`

To configure or disable the web dashboard:

```bash
WALTER_ENABLE_WEB_DASHBOARD=0 python main.py
WALTER_WEB_HOST=127.0.0.1 WALTER_WEB_PORT=9000 python main.py
```

## Development

Core modules in `src/walter/`:

- `config.py` for configuration and secret loading
- `dashboard.py` for terminal and web dashboard state publishing
- `market_data.py` for Hyperliquid market snapshot collection
- `LLM_API.py` for prompt construction, API calls, and response parsing
- `hyperliquid_API.py` for position queries and order placement
- `news_aggregator.py` for CryptoPanic and CryptoCompare ingestion
- `news_summarizer.py` for TF-IDF vectorization and DBSCAN clustering
- `db_utils.py` for SQLite schema initialization and persistence

## Extending Walter

- Add new data sources in `src/walter/` and pass them into the LLM flow in `main.py`.
- Adjust strategy behavior by editing the system prompt in `src/walter/LLM_API.py`.
- Extend the dashboard by adding metrics to `TradingDashboard` in `src/walter/dashboard.py`.

Disclaimer: use at your own risk.
