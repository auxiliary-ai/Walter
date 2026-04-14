# Walter 🤖

<p align="center">
  <img src="walter_logo.svg" alt="Walter logo" width="220">
</p>

Walter is an automated crypto trading assistant for **Hyperliquid**. It uses AI to analyze market data and news narratives to decide whether to **BUY**, **SELL**, or **HOLD**.

## 🚀 Quick Start

1. **Setup**:
   ```bash
   git clone <repo_url>
   cd walter
   python -m venv .venv && source .venv/bin/activate
   pip install -e .
   ```
2. **Configure**: Create a `.env` file with your keys (see `src/walter/config.py` for all options):
   * `API_WALLET_PRIVATE_KEY` & `PUBLIC_KEY` (Hyperliquid)
   * `OPENROUTER_API_KEY` (for AI access)
3. **Run**:
   ```bash
   python main.py
   ```
   *Dashboard available at: `http://127.0.0.1:8765`*

## 🧠 How It Works

Walter runs a loop every few seconds:
1. **Context**: Fetches Hyperliquid prices and aggregates crypto news into "Narratives".
2. **Decision**: Sends the context to an AI (via OpenRouter). The AI returns a JSON decision with its "Thinking".
3. **Execution**: Walter checks your balance and places the order if the AI suggests a move.
4. **Memory**: Every decision and market snapshot is saved to `walter.db` (SQLite) for history.

## 🛠️ How to Build on Walter

* **New Data**: Add a fetcher in `src/walter/` and pass it to the AI in `main.py`.
* **New Strategy**: Edit the `SYSTEM_PROMPT` in `src/walter/LLM_API.py`.
* **New UI**: Add metrics to `TradingDashboard` in `src/walter/dashboard.py`.

---
*Disclaimer: This is a prototype. Use at your own risk.*
