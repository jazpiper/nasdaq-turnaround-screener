from __future__ import annotations

from pydantic import BaseModel, Field


class AlertSource(BaseModel):
    artifact_directory: str
    report_path: str
    metadata_path: str
    window_index: int | None = None
    window_number: int | None = None
    total_windows: int | None = None


class AlertSummary(BaseModel):
    eligible_candidate_count: int
    individual_event_count: int
    digest_event_count: int
    suppressed_candidate_count: int
    quality_gate: str
    regime_gate: str = "unknown"
    regime_watchlist_cap: int | None = None
    regime_gate_reason: str | None = None
    sector_concentration_gate: str = "pass"
    sector_concentration_cap: int | None = None
    suppressed_by_sector_concentration_count: int = 0
    correlation_gate: str = "pass"
    correlation_group_cap: int | None = None
    suppressed_by_correlation_count: int = 0
    market_data_reliability: str | None = None
    market_data_provider_status: list[dict[str, object]] = Field(default_factory=list)
    regime_context_available: bool = False
    sector_signal_populated_count: int = 0
    sector_signal_coverage_ratio: float = 0.0
    correlation_signal_populated_count: int = 0
    correlation_signal_coverage_ratio: float = 0.0
    conservative_shadow: dict[str, object] | None = None


class AlertEvent(BaseModel):
    event_type: str
    phase: str
    delivery_mode: str
    delivery_priority: str
    severity: str
    dedupe_key: str
    group_key: str
    change_status: str
    change_reason_codes: list[str]
    message_summary: str
    payload: dict[str, object]


class AlertDocument(BaseModel):
    schema_version: int
    delivery_contract: str
    run_date: str
    generated_at: str
    run_mode: str
    phase: str
    source: AlertSource
    summary: AlertSummary
    events: list[AlertEvent]
