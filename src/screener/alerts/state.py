from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from screener.storage.files import write_json_atomic


class TickerAlertState(BaseModel):
    last_delivery_tier: str | None = None
    last_material_signature: str | None = None
    last_phase: str | None = None
    last_emitted_at: datetime | None = None
    last_dedupe_key: str | None = None
    last_score: int | None = None
    last_risk_adjusted_score: int | None = None
    last_rank: int | None = None
    last_headline_reason: str | None = None
    last_headline_risk: str | None = None
    last_earnings_penalty: int | None = None
    last_volatility_penalty: int | None = None


class DigestAlertState(BaseModel):
    last_digest_signature: str | None = None
    last_digest_dedupe_key: str | None = None


class AlertState(BaseModel):
    run_date: str | None = None
    tickers: dict[str, TickerAlertState] = Field(default_factory=dict)
    digest: DigestAlertState | None = None


def load_alert_state(path: Path) -> AlertState:
    if not path.exists():
        return AlertState()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return AlertState.model_validate(payload)


def save_alert_state(path: Path, state: AlertState) -> Path:
    return write_json_atomic(path, state.model_dump(mode="json", exclude_none=True))
