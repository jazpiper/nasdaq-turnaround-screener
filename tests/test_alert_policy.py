from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from screener.alerts.policy import (
    classify_candidate,
    determine_change_status,
    evaluate_daily_quality_gate,
    evaluate_intraday_quality_gate,
)
from screener.models import CandidateResult, RunMetadata, ScoreBreakdown


def make_candidate(
    *,
    ticker: str = "AAPL",
    score: int = 64,
    reasons: list[str] | None = None,
    risks: list[str] | None = None,
) -> CandidateResult:
    return CandidateResult(
        ticker=ticker,
        name="Apple Inc.",
        score=score,
        subscores=ScoreBreakdown(oversold=20, bottom_context=15, reversal=18, volume=6, market_context=5),
        reasons=reasons or ["BB 하단 근처 또는 재진입 구간", "5일선 회복 또는 회복 시도"],
        risks=risks or ["중기 추세는 아직 하락 압력일 수 있음"],
        indicator_snapshot={
            "earnings_penalty": 0,
            "volatility_penalty": 0,
        },
        generated_at=datetime(2026, 4, 22, 7, 30, tzinfo=timezone.utc),
    )


def test_evaluate_daily_quality_gate_blocks_large_data_failure() -> None:
    metadata = RunMetadata(
        run_date=datetime(2026, 4, 22, tzinfo=timezone.utc).date(),
        generated_at=datetime(2026, 4, 22, 7, 30, tzinfo=timezone.utc),
        artifact_directory=Path("output/daily/2026-04-22"),
        failed_ticker_count=21,
        bars_nonempty_count=79,
        latest_bar_date_mismatch_count=0,
        insufficient_history_count=0,
    )

    assert evaluate_daily_quality_gate(metadata) == "block"


def test_classify_candidate_marks_high_score_state_change_as_single() -> None:
    candidate = make_candidate()

    assert classify_candidate(candidate, rank=1, change_status="new") == "single"


def test_classify_candidate_suppresses_high_earnings_penalty() -> None:
    candidate = make_candidate(score=72)
    candidate.indicator_snapshot["earnings_penalty"] = 8

    assert classify_candidate(candidate, rank=1, change_status="new") == "suppressed"


def test_determine_change_status_marks_small_recompute_as_unchanged() -> None:
    candidate = make_candidate(score=64)
    previous = {
        "last_delivery_tier": "single",
        "last_material_signature": "BB 하단 근처 또는 재진입 구간|중기 추세는 아직 하락 압력일 수 있음|0|0",
        "last_phase": "provisional",
        "last_emitted_at": "2026-04-22T15:30:00+00:00",
        "last_dedupe_key": "key-aapl",
    }

    assert determine_change_status(candidate, rank=1, phase="final", previous_state=previous) == "unchanged"


def test_determine_change_status_keeps_small_score_and_rank_nudge_unchanged() -> None:
    candidate = make_candidate(score=65)
    previous = {
        "last_delivery_tier": "single",
        "last_material_signature": "BB 하단 근처 또는 재진입 구간|중기 추세는 아직 하락 압력일 수 있음|0|0",
        "last_phase": "provisional",
        "last_emitted_at": "2026-04-22T15:30:00+00:00",
        "last_dedupe_key": "key-aapl",
    }

    assert determine_change_status(candidate, rank=2, phase="final", previous_state=previous) == "unchanged"


def test_evaluate_intraday_quality_gate_warns_on_partial_collection() -> None:
    assert evaluate_intraday_quality_gate(
        collected_count=50,
        failed_count=2,
        skipped_due_to_credit_exhaustion_count=0,
    ) == "warn"
