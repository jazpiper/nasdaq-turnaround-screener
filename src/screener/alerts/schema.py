from __future__ import annotations

from pydantic import BaseModel


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
