# Contributing to Walter

Thank you for your interest! Walter is built to be simple and modular.

## 🚀 Getting Started

1. **Fork & Clone** the repo.
2. **Setup Env**:
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -e ".[dev]"
   pip install -r requirements.txt
   ```
3. **Configure**: Create a `.env` file (copy from README).

## 🛠️ Adding a Feature

1. **Create a branch**: `git checkout -b feature/my-new-thing`.
2. **Make it modular**: Add new logic as a module in `src/walter/`.
3. **Wire it up**: Add your logic to the main loop in `main.py`.
4. **Test**: Run `pytest` and `ruff check .` before pushing.
5. **PR**: Open a PR with a simple explanation of *why* this change helps.

## 📝 Guidelines

* **Keep it simple**: We prefer minimal code that is easy to read.
* **Update Docs**: If you change configuration, update the README.
* **Commit**: Use clear, short messages like `Add RSI indicator` or `Fix news clustering`.

---
*By contributing, you agree to license your work under the MIT License.*
