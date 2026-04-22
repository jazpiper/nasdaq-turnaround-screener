from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from screener.alerts.builder import build_daily_alert_document
from screener.alerts.policy import material_signature
from screener.alerts.state import AlertState
from screener.models import CandidateResult, RunMetadata, ScoreBreakdown, ScreenRunResult


def make_candidate(*, ticker: str = "AAPL", score: int = 64) -> CandidateResult:
    return CandidateResult(
        ticker=ticker,
        name="Apple Inc.",
        score=score,
        subscores=ScoreBreakdown(oversold=20, bottom_context=15, reversal=18, volume=6, market_context=5),
        reasons=["BB 하단 근처 또는 재진입 구간", "5일선 회복 또는 회복 시도"],
        risks=["중기 추세는 아직 하락 압력일 수 있음"],
        indicator_snapshot={
            "earnings_penalty": 0,
            "volatility_penalty": 0,
        },
        generated_at=datetime(2026, 4, 22, 7, 30, tzinfo=timezone.utc),
    )


def make_result(
    candidates: list[CandidateResult],
    *,
    bars_nonempty_count: int,
    failed_ticker_count: int = 0,
    latest_bar_date_mismatch_count: int = 0,
    insufficient_history_count: int = 0,
) -> ScreenRunResult:
    return ScreenRunResult(
        metadata=RunMetadata(
            run_date=date(2026, 4, 22),
            generated_at=datetime(2026, 4, 22, 20, 5, tzinfo=timezone.utc),
            artifact_directory=Path("output/daily/2026-04-22"),
            planned_ticker_count=100,
            successful_ticker_count=100 - failed_ticker_count,
            failed_ticker_count=failed_ticker_count,
            bars_nonempty_count=bars_nonempty_count,
            latest_bar_date_mismatch_count=latest_bar_date_mismatch_count,
            insufficient_history_count=insufficient_history_count,
        ),
        candidates=candidates,
    )


def test_build_daily_alert_document_marks_single_events_warning_and_includes_source_ref() -> None:
    document, next_state = build_daily_alert_document(
        make_result([make_candidate()], bars_nonempty_count=95),
        state=AlertState(),
        artifact_directory="output/daily/2026-04-22",
        report_path="output/daily/2026-04-22/daily-report.json",
        metadata_path="output/daily/2026-04-22/run-metadata.json",
    )

    assert document.summary.quality_gate == "pass"
    assert len(document.events) == 1
    assert document.events[0].severity == "warning"
    assert document.events[0].payload["source_candidate_ref"] == "#/candidates/0"
    assert next_state.tickers["AAPL"].last_delivery_tier == "single"


def test_build_daily_alert_document_keeps_prior_state_when_quality_gate_blocks() -> None:
    prior_state = AlertState(
        run_date="2026-04-22",
        tickers={
            "AAPL": {
                "last_delivery_tier": "single",
                "last_material_signature": "old-signature",
                "last_phase": "provisional",
                "last_emitted_at": "2026-04-22T15:30:00+00:00",
                "last_dedupe_key": "old-key",
            }
        },
    )

    document, next_state = build_daily_alert_document(
        make_result([make_candidate()], bars_nonempty_count=10),
        state=prior_state,
        artifact_directory="output/daily/2026-04-22",
        report_path="output/daily/2026-04-22/daily-report.json",
        metadata_path="output/daily/2026-04-22/run-metadata.json",
    )

    assert document.summary.quality_gate == "block"
    assert document.summary.individual_event_count == 0
    assert document.summary.digest_event_count == 0
    assert document.events == []
    assert next_state.run_date == "2026-04-22"
    assert next_state.tickers["AAPL"].last_dedupe_key == "old-key"


def test_build_daily_alert_document_upgrades_digest_candidate_to_single() -> None:
    document, _ = build_daily_alert_document(
        make_result([make_candidate(score=68)], bars_nonempty_count=95),
        state=AlertState(
            run_date="2026-04-22",
            tickers={
                "AAPL": {
                    "last_delivery_tier": "digest",
                    "last_material_signature": "52|4|BB 하단 근처 또는 재진입 구간|중기 추세는 아직 하락 압력일 수 있음|0|0",
                    "last_phase": "provisional",
                    "last_emitted_at": "2026-04-22T15:30:00+00:00",
                    "last_dedupe_key": "old-key",
                }
            },
        ),
        artifact_directory="output/daily/2026-04-22",
        report_path="output/daily/2026-04-22/daily-report.json",
        metadata_path="output/daily/2026-04-22/run-metadata.json",
    )

    assert document.events[0].change_status == "upgraded"


def test_build_daily_alert_document_routes_unchanged_final_single_to_digest_only() -> None:
    candidate = make_candidate(score=64)
    document, _ = build_daily_alert_document(
        make_result([candidate], bars_nonempty_count=95),
        state=AlertState(
            run_date="2026-04-22",
            tickers={
                "AAPL": {
                    "last_delivery_tier": "single",
                    "last_material_signature": material_signature(candidate, rank=1),
                    "last_phase": "provisional",
                    "last_emitted_at": "2026-04-22T15:30:00+00:00",
                    "last_dedupe_key": "old-key",
                    "last_score": 64,
                    "last_rank": 1,
                    "last_headline_reason": "BB 하단 근처 또는 재진입 구간",
                    "last_headline_risk": "중기 추세는 아직 하락 압력일 수 있음",
                    "last_earnings_penalty": 0,
                    "last_volatility_penalty": 0,
                }
            },
        ),
        artifact_directory="output/daily/2026-04-22",
        report_path="output/daily/2026-04-22/daily-report.json",
        metadata_path="output/daily/2026-04-22/run-metadata.json",
    )

    assert [event.event_type for event in document.events] == ["digest_alert"]
