from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


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
    default_notes: list[str] = field(
        default_factory=lambda: [
            "Scaffold run: concrete data providers and scoring logic are attached later.",
        ]
    )


def get_settings(
    output_dir: str | Path | None = None,
    market_data_provider: str | None = None,
    twelve_data_api_key: str | None = None,
) -> Settings:
    settings = Settings(
        market_data_provider=market_data_provider or os.getenv("SCREENER_MARKET_DATA_PROVIDER", "yfinance"),
        twelve_data_api_key=twelve_data_api_key or os.getenv("TWELVE_DATA_API_KEY"),
        twelve_data_base_url=os.getenv("TWELVE_DATA_BASE_URL", Settings.twelve_data_base_url),
    )
    if output_dir is not None:
        settings.output_dir = Path(output_dir)
    return settings
