from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, Field


class ScoreBreakdown(BaseModel):
    oversold: int = 0
    bottom_context: int = 0
    reversal: int = 0
    volume: int = 0
    market_context: int = 0


class TickerInput(BaseModel):
    ticker: str
    name: str | None = None
    sector: str | None = None


class CandidateResult(BaseModel):
    ticker: str
    name: str | None = None
    score: int
    subscores: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    tier: str = "watchlist"
    tier_reasons: list[str] = Field(default_factory=list)
    close: float | None = None
    lower_bb: float | None = None
    rsi14: float | None = None
    distance_to_20d_low: float | None = None
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    indicator_snapshot: dict[str, object] | None = None
    snapshot_schema_version: int = 2
    generated_at: datetime


class RunMetadata(BaseModel):
    run_date: date
    generated_at: datetime
    universe: str = "NASDAQ-100"
    run_mode: str = "daily"
    dry_run: bool = False
    artifact_directory: Path
    planned_ticker_count: int = 0
    successful_ticker_count: int = 0
    failed_ticker_count: int = 0
    bars_nonempty_count: int = 0
    latest_bar_date_mismatch_count: int = 0
    insufficient_history_count: int = 0
    planned_tickers: list[str] = Field(default_factory=list)
    data_failures: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ScreenRunResult(BaseModel):
    metadata: RunMetadata
    candidates: list[CandidateResult] = Field(default_factory=list)

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)


@dataclass(slots=True)
class PipelineContext:
    run_date: date
    generated_at: datetime
    universe_name: str = "NASDAQ-100"
    output_dir: Path = Path("output")
    dry_run: bool = False
    run_mode: str = "daily"


@dataclass(slots=True)
class RunArtifacts:
    markdown_path: Path | None = None
    json_report_path: Path | None = None
    metadata_path: Path | None = None
    alert_events_path: Path | None = None
    stable_alert_events_path: Path | None = None
