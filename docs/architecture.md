# Walter Architecture

Walter is a modular Python application that automates trading decisions. Think of it as a single-process bot that cycles through **Gathering**, **Deciding**, and **Executing**.

## The Trading Cycle

Every loop (default 4s) in `main.py` performs these 4 steps:

1. **Context Gathering**  
   * `news_aggregator.py` & `news_summarizer.py`: Fetches raw crypto news and clusters them into "Major Narratives".
   * `market_data.py`: Pulls price, volume, funding, and indicators from Hyperliquid.
   * `hyperliquid_API.py`: Checks your current account balance and open positions.

2. **AI Decisioning**  
   * `LLM_API.py`: Takes all the data above and asks an AI (OpenRouter) for a decision.  
   * **Output**: A JSON object containing an `ACTION` (BUY/SELL/HOLD), `SIZE`, `LEVERAGE`, and the AI's `THINKING`.

3. **Execution & Risk Check**  
   * Walter checks if your withdrawable balance can cover the required margin for the suggested size.
   * If OK, `hyperliquid_API.py` places the order via the Hyperliquid SDK.

4. **Persistence & UI**  
   * `db_utils.py`: Saves everything (market context, AI thoughts, and order results) to `walter.db`.
   * `dashboard.py`: Updates the terminal and the web UI (`web_dashboard.py`) with the latest state.

## Core Modules

| Module | What it does |
| --- | --- |
| `main.py` | Orchestrates the cycle and enforces risk guardrails. |
| `config.py` | Loads secrets and defaults. |
| `LLM_API.py` | Builds the prompt and parses the AI's response. |
| `db_utils.py` | Manages the SQLite database for history. |
| `hyperliquid_API.py` | Communicates with the exchange to check balance and trade. |

---
*Walter is designed for fast strategy prototyping, not unattended production trading.*
