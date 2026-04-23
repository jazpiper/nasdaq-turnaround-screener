# Repository Guidelines

## Project Structure & Module Organization
- `src/screener/` contains the application package. `cli/main.py` is the Typer entrypoint, `pipeline.py` is the public facade, `_pipeline/` holds internal daily-run modules, and domain code is split across `data/`, `indicators/`, `scoring/`, `reporting/`, `storage/`, `universe/`, and `models/`.
- `scripts/run_daily.py` and `scripts/run_intraday_window.py` are cron-friendly wrappers around the CLI.
- `tests/` covers CLI, pipeline, storage, indicators, and provider behavior.
- `docs/` contains the current-state docs: architecture, operations, and signals. Artifacts belong under `output/`.

## Build, Test, and Development Commands
- `uv sync --extra dev` creates/updates `.venv` from `uv.lock` with development dependencies.
- `uv run python -m screener.cli.main run --date 2026-04-21 --dry-run` runs the daily screener without writing artifacts.
- `uv run python scripts/run_daily.py --date 2026-04-21 --skip-install` runs the daily wrapper and updates `output/daily/latest`.
- `uv run python -m screener.cli.main collect-window --date 2026-04-21 --window-index 0` executes an intraday collection window.
- `uv run python -m screener.cli.main init-oracle-schema` initializes Oracle tables before persistence is enabled.
- `uv run python -m screener.cli.main backtest --start-date 2026-03-01 --end-date 2026-04-21` replays historical candidate generation and writes forward-return artifacts.
- `uv run pytest` runs the full suite; use `uv run pytest tests/test_cli.py -q` for targeted iteration.

## Coding Style & Naming Conventions
- Target Python 3.11+ and follow the existing style: 4-space indentation, explicit type hints, and `from __future__ import annotations` in module headers.
- Use `snake_case` for modules, functions, variables, and test names. Use `PascalCase` for classes and Pydantic models.
- Keep imports grouped as standard library, third-party, then local package imports.
- Prefer deterministic functions; isolate filesystem and Oracle writes behind `storage/` and runner boundaries.

## Testing Guidelines
- Use pytest with files named `test_*.py` and test functions named `test_<behavior>`.
- Mirror the production surface area when adding tests: CLI changes go in `tests/test_cli.py`, pipeline logic in `tests/test_pipeline.py`, and provider/storage work in the matching module test.
- Prefer stubs and `monkeypatch` over live API or Oracle dependencies. Cover artifact paths, CLI output, and persistence toggles.

## Commit & Pull Request Guidelines
- Follow the repository’s existing commit style: `feat: ...`, `docs: ...`, written in the imperative mood.
- Keep each commit focused on one logical change. Mention the affected area when useful, for example `feat: refine candle reversal signals`.
- PRs should summarize behavior changes, note config or secret impacts, and list verification steps such as `uv run pytest` or a dry-run CLI command.

## Security & Configuration Tips
- Never commit API keys, Oracle credentials, or local secret files.
- Use `TWELVE_DATA_API_KEY` and `ORACLE_DB_*`, or the OpenClaw secrets integration described in `docs/operations.md`.
- Treat `output/` as generated data; regenerate artifacts instead of editing them manually.
