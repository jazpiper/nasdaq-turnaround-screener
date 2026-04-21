from __future__ import annotations

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
    default_notes: list[str] = field(
        default_factory=lambda: [
            "Scaffold run: concrete data providers and scoring logic are attached later.",
        ]
    )


def get_settings(output_dir: str | Path | None = None) -> Settings:
    settings = Settings()
    if output_dir is not None:
        settings.output_dir = Path(output_dir)
    return settings
