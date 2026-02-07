# Contributing to Walter

Thanks for your interest in contributing to Walter! This document covers the guidelines and workflow for contributing to the project.

## Getting Started

1. **Fork the repository** and clone your fork locally.
2. **Create a virtual environment** and install the project in editable mode with dev dependencies:

   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -e ".[dev]"
   pip install -r requirements.txt
   ```

3. **Set up your environment** — copy `.env.local.example` (or create `.env.local`) and fill in the required secrets. See the README for the full list of configuration variables.

## Development Workflow

1. Create a feature branch from `main`:

   ```bash
   git checkout -b feature/your-feature-name
   ```

2. Make your changes in small, focused commits.
3. Run linting and tests before pushing:

   ```bash
   ruff check .
   pytest
   ```

4. Push your branch and open a pull request against `main`. Fill out the PR template checklist.

## Code Style

- **Linter / Formatter:** We use [Ruff](https://docs.astral.sh/ruff/) for linting. Run `ruff check .` before committing.
- **Type hints:** Use type annotations for function signatures where practical.
- **Naming conventions:** Follow existing patterns in the codebase — `PascalCase` for classes, `snake_case` for functions and variables.

## Project Structure

All source code lives under `src/walter/`. Key modules:

| Module                  | Responsibility                                      |
| ----------------------- | --------------------------------------------------- |
| `config.py`             | Centralised configuration and secret loading.       |
| `market_data.py`        | Hyperliquid market snapshot builder.                 |
| `LLM_API.py`            | OpenRouter prompt construction and response parsing. |
| `hyperliquid_API.py`    | Position queries and order placement.                |
| `news_API_aggregator.py`| CryptoPanic and CryptoCompare news fetching.         |
| `news_summerizer.py`    | Sentence-transformer embedding + DBSCAN clustering. |
| `db_utils.py`           | PostgreSQL schema initialisation and persistence.    |

## Adding Configuration

If your change introduces a new configuration option:

1. Add the default value or `os.getenv()` call to `src/walter/config.py`.
2. Import it from `config.py` wherever it's used — don't scatter `os.getenv()` calls across modules.
3. Document the variable in the README configuration table.
4. Check the corresponding box in the PR template.

## Commit Messages

Write clear, concise commit messages. Prefer the imperative mood:

- **Good:** `Add news clustering with DBSCAN`
- **Avoid:** `Added stuff` / `changes`

## Pull Requests

- Keep PRs focused — one feature or fix per PR.
- Fill out the [PR checklist](/.github/pull_request_template.md) completely.
- Link any related issues in the PR description.
- Make sure CI checks (lint + tests) pass before requesting review.

## Reporting Issues

Open a GitHub issue with:

- A clear title and description.
- Steps to reproduce (if applicable).
- Expected vs. actual behaviour.
- Relevant logs or screenshots.

## License

By contributing to Walter, you agree that your contributions will be licensed under the [MIT License](LICENSE).
