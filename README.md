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


Walter is an automated trading assistant that pulls real-time market context from Hyperliquid, asks a Gemini-powered LLM to decide whether to buy, sell, or hold, and optionally routes market orders when the model is confident enough. It is designed for fast strategy prototyping, not unattended production trading.

## Features
- Aggregates Hyperliquid mid prices, candles, volume, funding, and trade pressure into a concise market snapshot.
- Evaluates open positions and market context with a Gemini 1.5 Flash model and enforces a configurable confidence threshold before executing.
- Places market or limit orders through the official Hyperliquid SDK with automatic tick-size snapping and leverage updates.
- Runs as a simple scheduler loop (configurable interval) so you can monitor output and interrupt with `Ctrl+C`.

## Requirements
- Python 3.10+
- Hyperliquid API access (public key plus a funded wallet private key for execution).
- Google Gemini API key with access to `gemini-1.5-flash`.

## Installation
```bash
git clone <your fork or repo url>
cd walter
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

## Configuration
Create a `.env` or `.env.local` file (both are loaded if present) and provide at least:

| Variable | Purpose |
| --- | --- |
| `SCHEDULER_INTERVAL_SECONDS` | Seconds between decision cycles (default `60`). |
| `COIN` | Hyperliquid asset ticker, e.g. `BTC`. |
| `HYPERLIQUID_URL` | Base URL for the Hyperliquid info endpoint. |
| `GENERAL_PUBLIC_KEY` | Public key used when fetching existing positions. |
| `API_WALLET_PRIVATE_KEY` | Private key that signs orders. |
| `ORDER_SIZE` | Position size in coin terms (default `0.5`). |
| `ORDER_LEVERAGE` | Leverage passed to Hyperliquid before each order. |
| `ORDER_TIF` | Time-in-force for limit payloads, e.g. `Ioc` or `Gtc`. |
| `GEMINI_API_KEY` | Google Gemini API key used by the LLM client. |

You can also override the default Gemini model or token lists by editing `walter/LLM_API.py`.

## Usage
```bash
python main.py
```

The script prints each market snapshot, open position payload, the LLM decision, and order status. Stop the loop with `Ctrl+C`.

## Development
- Run tests: `pytest`
- Format/lint: `ruff check .`
- The core modules live in `src/walter/` (`market_data.py`, `LLM_API.py`, `hyperliquid_API.py`, `utils.py`).
