from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, Field


class ScoreBreakdown(BaseModel):
    oversold: float = 0.0
    bottom_context: float = 0.0
    reversal: float = 0.0
    volume: float = 0.0
    market_context: float = 0.0


class TickerInput(BaseModel):
    ticker: str
    name: str | None = None
    sector: str | None = None


class CandidateResult(BaseModel):
    ticker: str
    score: float
    subscores: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    close: float | None = None
    lower_bb: float | None = None
    rsi14: float | None = None
    distance_to_20d_low: float | None = None
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    generated_at: datetime


class RunMetadata(BaseModel):
    run_date: date
    generated_at: datetime
    universe: str = "NASDAQ-100"
    run_mode: str = "daily"
    dry_run: bool = False
    artifact_directory: Path
    data_failures: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ScreenRunResult(BaseModel):
    metadata: RunMetadata
    candidates: list[CandidateResult] = Field(default_factory=list)

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)


class PipelineContext(BaseModel):
    run_date: date
    generated_at: datetime
    dry_run: bool = False
    universe_name: str = "NASDAQ-100"
    output_dir: Path = Path("output")
    run_mode: str = "daily"


class RunArtifacts(BaseModel):
    markdown_path: Path | None = None
    json_report_path: Path | None = None
    metadata_path: Path | None = None
