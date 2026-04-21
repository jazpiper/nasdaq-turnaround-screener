from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from screener.secrets import default_openclaw_secrets_path, load_openclaw_secrets


@dataclass(slots=True)
class Settings:
    project_name: str = "nasdaq-turnaround-screener"
    universe_name: str = "NASDAQ-100"
    output_dir: Path = Path("output")
    markdown_report_name: str = "daily-report.md"
    json_report_name: str = "daily-report.json"
    metadata_report_name: str = "run-metadata.json"
    default_run_mode: str = "daily"
    market_data_provider: str = "yfinance"
    twelve_data_api_key: str | None = None
    twelve_data_base_url: str = "https://api.twelvedata.com/time_series"
    openclaw_secrets_path: Path = default_openclaw_secrets_path()
    default_notes: list[str] = field(
        default_factory=lambda: [
            "Signals are generated from recent daily price history and technical ranking rules.",
        ]
    )


def get_settings(
    output_dir: str | Path | None = None,
    market_data_provider: str | None = None,
    twelve_data_api_key: str | None = None,
    openclaw_secrets_path: str | Path | None = None,
) -> Settings:
    resolved_secrets_path = Path(openclaw_secrets_path).expanduser() if openclaw_secrets_path is not None else default_openclaw_secrets_path()
    secrets = load_openclaw_secrets(resolved_secrets_path)
    resolved_twelve_data_api_key = twelve_data_api_key or os.getenv("TWELVE_DATA_API_KEY") or _coerce_optional_string(secrets.get("/twelveData/apiKey") if secrets else None)
    resolved_market_data_provider = market_data_provider or os.getenv("SCREENER_MARKET_DATA_PROVIDER") or _default_market_data_provider(resolved_twelve_data_api_key)

    settings = Settings(
        market_data_provider=resolved_market_data_provider,
        twelve_data_api_key=resolved_twelve_data_api_key,
        twelve_data_base_url=os.getenv("TWELVE_DATA_BASE_URL", Settings.twelve_data_base_url),
        openclaw_secrets_path=resolved_secrets_path,
    )
    if output_dir is not None:
        settings.output_dir = Path(output_dir)
    return settings


def _default_market_data_provider(twelve_data_api_key: str | None) -> str:
    return "twelve-data" if twelve_data_api_key else "yfinance"


def _coerce_optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
