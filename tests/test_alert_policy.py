from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from screener.alerts.policy import (
    classify_candidate,
    determine_change_status,
    evaluate_daily_quality_gate,
    evaluate_intraday_quality_gate,
    evaluate_regime_gate,
    material_signature,
)
from screener.alerts.state import TickerAlertState
from screener.models import CandidateResult, RunMetadata, ScoreBreakdown
from screener.scoring import BUY_REVIEW_TIER


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
        tier=BUY_REVIEW_TIER,
        tier_reasons=["score, reversal, volume, and risk profile qualify for buy review"],
        reasons=reasons or ["BB 하단 근처 또는 재진입 구간", "5일선 회복 또는 회복 시도"],
        risks=risks or ["중기 추세는 아직 하락 압력일 수 있음"],
        indicator_snapshot={
            "earnings_penalty": 0,
            "volatility_penalty": 0,
            "volume_ratio_20d": 1.1,
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


def test_material_signature_includes_score_and_rank() -> None:
    candidate = make_candidate(score=66)

    assert material_signature(candidate, rank=3).startswith("66|3|")


def test_classify_candidate_requires_reversal_and_bottom_reason_mix() -> None:
    candidate = make_candidate(reasons=["BB 하단 근처 또는 재진입 구간", "최근 20일 저점 부근"])

    assert classify_candidate(candidate, rank=1, change_status="new") == "digest"


def test_classify_candidate_accepts_actual_scorer_reversal_phrase() -> None:
    candidate = make_candidate(
        reasons=["하단 꼬리 이후 종가가 일중 상단에서 마감", "최근 20일 저점 부근"],
    )

    assert classify_candidate(candidate, rank=1, change_status="new") == "single"


def test_classify_candidate_suppresses_high_earnings_penalty() -> None:
    candidate = make_candidate(score=72)
    candidate.tier = "avoid/high-risk"
    candidate.indicator_snapshot["earnings_penalty"] = 8

    assert classify_candidate(candidate, rank=1, change_status="new") == "suppressed"


def test_classify_candidate_routes_watchlist_to_digest_not_single() -> None:
    candidate = make_candidate(score=72)
    candidate.tier = "watchlist"

    assert classify_candidate(candidate, rank=1, change_status="new") == "digest"


def test_determine_change_status_marks_small_recompute_as_unchanged() -> None:
    candidate = make_candidate(score=64)
    previous = {
        "last_delivery_tier": "single",
        "last_material_signature": "BB 하단 근처 또는 재진입 구간|중기 추세는 아직 하락 압력일 수 있음|0|0",
        "last_score": "64",
        "last_rank": "1",
        "last_headline_reason": "BB 하단 근처 또는 재진입 구간",
        "last_headline_risk": "중기 추세는 아직 하락 압력일 수 있음",
        "last_earnings_penalty": "0",
        "last_volatility_penalty": "0",
        "last_phase": "provisional",
        "last_emitted_at": "2026-04-22T15:30:00+00:00",
        "last_dedupe_key": "key-aapl",
    }

    assert determine_change_status(candidate, rank=1, phase="final", previous_state=previous) == "unchanged"


def test_determine_change_status_handles_partial_previous_state() -> None:
    candidate = make_candidate(score=64)
    previous = {
        "last_delivery_tier": "single",
    }

    assert determine_change_status(candidate, rank=1, phase="final", previous_state=previous) == "unchanged"


def test_determine_change_status_keeps_legacy_sparse_state_unchanged() -> None:
    candidate = make_candidate(score=64)
    previous = {
        "last_delivery_tier": "single",
        "last_material_signature": "BB 하단 근처 또는 재진입 구간|중기 추세는 아직 하락 압력일 수 있음|0|0",
        "last_phase": "final",
        "last_emitted_at": "2026-04-22T15:30:00+00:00",
        "last_dedupe_key": "key-aapl",
    }

    assert determine_change_status(candidate, rank=1, phase="final", previous_state=previous) == "unchanged"


def test_determine_change_status_keeps_round_tripped_legacy_state_unchanged() -> None:
    candidate = make_candidate(score=64)
    previous = TickerAlertState.model_validate(
        {
            "last_delivery_tier": "single",
            "last_material_signature": "BB 하단 근처 또는 재진입 구간|중기 추세는 아직 하락 압력일 수 있음|0|0",
            "last_phase": "final",
            "last_emitted_at": "2026-04-22T15:30:00+00:00",
            "last_dedupe_key": "key-aapl",
        }
    ).model_dump(mode="json")

    assert previous["last_score"] is None
    assert determine_change_status(candidate, rank=1, phase="final", previous_state=previous) == "unchanged"


def test_determine_change_status_keeps_small_score_and_rank_nudge_unchanged() -> None:
    candidate = make_candidate(score=65)
    previous = {
        "last_delivery_tier": "single",
        "last_material_signature": "BB 하단 근처 또는 재진입 구간|중기 추세는 아직 하락 압력일 수 있음|0|0",
        "last_score": "64",
        "last_rank": "1",
        "last_headline_reason": "BB 하단 근처 또는 재진입 구간",
        "last_headline_risk": "중기 추세는 아직 하락 압력일 수 있음",
        "last_earnings_penalty": "0",
        "last_volatility_penalty": "0",
        "last_phase": "provisional",
        "last_emitted_at": "2026-04-22T15:30:00+00:00",
        "last_dedupe_key": "key-aapl",
    }

    assert determine_change_status(candidate, rank=2, phase="final", previous_state=previous) == "unchanged"


def test_determine_change_status_marks_tier_only_signature_change_as_material_change() -> None:
    candidate = make_candidate(score=64)
    previous_candidate = make_candidate(score=64)
    previous_candidate.tier = "watchlist"
    previous = {
        "last_delivery_tier": "single",
        "last_material_signature": material_signature(previous_candidate, rank=1),
        "last_score": "64",
        "last_rank": "1",
        "last_headline_reason": "BB 하단 근처 또는 재진입 구간",
        "last_headline_risk": "중기 추세는 아직 하락 압력일 수 있음",
        "last_earnings_penalty": "0",
        "last_volatility_penalty": "0",
        "last_phase": "provisional",
        "last_emitted_at": "2026-04-22T15:30:00+00:00",
        "last_dedupe_key": "key-aapl",
    }

    assert determine_change_status(candidate, rank=1, phase="final", previous_state=previous) == "material_change"


def test_determine_change_status_marks_large_score_delta_as_material_change() -> None:
    candidate = make_candidate(score=70)
    previous = {
        "last_delivery_tier": "single",
        "last_material_signature": "BB 하단 근처 또는 재진입 구간|중기 추세는 아직 하락 압력일 수 있음|0|0",
        "last_score": "64",
        "last_rank": "1",
        "last_headline_reason": "BB 하단 근처 또는 재진입 구간",
        "last_headline_risk": "중기 추세는 아직 하락 압력일 수 있음",
        "last_earnings_penalty": "0",
        "last_volatility_penalty": "0",
        "last_phase": "provisional",
        "last_emitted_at": "2026-04-22T15:30:00+00:00",
        "last_dedupe_key": "key-aapl",
    }

    assert determine_change_status(candidate, rank=1, phase="final", previous_state=previous) == "material_change"


def test_determine_change_status_marks_large_rank_delta_as_material_change() -> None:
    candidate = make_candidate(score=64)
    previous = {
        "last_delivery_tier": "single",
        "last_material_signature": "BB 하단 근처 또는 재진입 구간|중기 추세는 아직 하락 압력일 수 있음|0|0",
        "last_score": "64",
        "last_rank": "1",
        "last_headline_reason": "BB 하단 근처 또는 재진입 구간",
        "last_headline_risk": "중기 추세는 아직 하락 압력일 수 있음",
        "last_earnings_penalty": "0",
        "last_volatility_penalty": "0",
        "last_phase": "provisional",
        "last_emitted_at": "2026-04-22T15:30:00+00:00",
        "last_dedupe_key": "key-aapl",
    }

    assert determine_change_status(candidate, rank=3, phase="final", previous_state=previous) == "material_change"


def test_evaluate_intraday_quality_gate_warns_on_partial_collection() -> None:
    assert evaluate_intraday_quality_gate(
        collected_count=50,
        failed_count=2,
        skipped_due_to_credit_exhaustion_count=0,
    ) == "warn"


def test_evaluate_regime_gate_returns_pass_when_above_ma() -> None:
    decision = evaluate_regime_gate(qqq_below_20d_ma=False, qqq_return_20d=-8.0)

    assert decision.status == "pass"
    assert decision.is_bearish is False
    assert decision.watchlist_cap is None
    assert decision.reason == "conditions_not_met"


def test_evaluate_regime_gate_returns_capped_when_below_ma_and_return_below_threshold() -> None:
    decision = evaluate_regime_gate(qqq_below_20d_ma=True, qqq_return_20d=-6.0)

    assert decision.status == "capped"
    assert decision.is_bearish is True
    assert decision.watchlist_cap == 3
    assert decision.reason == "bearish_qqq_regime"


def test_evaluate_regime_gate_returns_unknown_on_missing_data() -> None:
    decision = evaluate_regime_gate(qqq_below_20d_ma=None, qqq_return_20d=None)

    assert decision.status == "unknown"
    assert decision.is_bearish is False
    assert decision.watchlist_cap is None
    assert decision.reason == "missing_benchmark_context"


def test_evaluate_regime_gate_does_not_cap_when_close_equals_ma() -> None:
    decision = evaluate_regime_gate(qqq_below_20d_ma=False, qqq_return_20d=-6.0)

    assert decision.status == "pass"
    assert decision.is_bearish is False
    assert decision.watchlist_cap is None
    assert decision.reason == "conditions_not_met"
