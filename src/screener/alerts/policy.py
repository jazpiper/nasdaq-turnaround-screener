from __future__ import annotations

from screener.models import CandidateResult, RunMetadata


def evaluate_daily_quality_gate(metadata: RunMetadata) -> str:
    if metadata.failed_ticker_count > 20 or metadata.bars_nonempty_count < 80 or metadata.latest_bar_date_mismatch_count > 10:
        return "block"
    if metadata.failed_ticker_count > 5 or metadata.latest_bar_date_mismatch_count > 0 or metadata.insufficient_history_count > 5:
        return "warn"
    return "pass"


def evaluate_intraday_quality_gate(
    *,
    collected_count: int,
    failed_count: int,
    skipped_due_to_credit_exhaustion_count: int,
) -> str:
    if collected_count < 20 or failed_count > 20 or skipped_due_to_credit_exhaustion_count > 0:
        return "block"
    if collected_count < 60 or failed_count > 5:
        return "warn"
    return "pass"


def headline_reason(candidate: CandidateResult) -> str:
    return candidate.reasons[0] if candidate.reasons else "n/a"


def headline_risk(candidate: CandidateResult) -> str:
    return candidate.risks[0] if candidate.risks else "n/a"


def material_signature(candidate: CandidateResult, *, rank: int) -> str:
    snapshot = candidate.indicator_snapshot or {}
    return "|".join(
        [
            headline_reason(candidate),
            headline_risk(candidate),
            str(snapshot.get("earnings_penalty", 0)),
            str(snapshot.get("volatility_penalty", 0)),
        ]
    )


def determine_change_status(
    candidate: CandidateResult,
    *,
    rank: int,
    phase: str,
    previous_state: dict[str, str] | None,
) -> str:
    if previous_state is None:
        return "new"

    previous_signature = previous_state["last_material_signature"]
    previous_tier = previous_state["last_delivery_tier"]
    current_signature = material_signature(candidate, rank=rank)

    if previous_tier == "digest" and rank <= 5 and candidate.score >= 60:
        return "upgraded"
    if previous_signature == current_signature:
        return "unchanged"
    return "material_change"


def classify_candidate(candidate: CandidateResult, *, rank: int, change_status: str) -> str:
    snapshot = candidate.indicator_snapshot or {}
    earnings_penalty = int(snapshot.get("earnings_penalty", 0) or 0)
    volatility_penalty = int(snapshot.get("volatility_penalty", 0) or 0)
    reason_count = len(candidate.reasons)

    if candidate.score < 45 or reason_count < 2 or earnings_penalty >= 8 or (volatility_penalty >= 4 and candidate.score < 60):
        return "suppressed"
    if candidate.score >= 60 and rank <= 5 and change_status in {"new", "upgraded", "material_change"}:
        return "single"
    if rank <= 10:
        return "digest"
    return "suppressed"
