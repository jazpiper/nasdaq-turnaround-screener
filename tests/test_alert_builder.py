from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from screener.alerts.builder import build_daily_alert_document
from screener.alerts.policy import material_signature
from screener.alerts.state import AlertState, TickerAlertState
from screener.models import CandidateResult, RunMetadata, ScoreBreakdown, ScreenRunResult
from screener.scoring import BUY_REVIEW_TIER


def make_candidate(
    *,
    ticker: str = "AAPL",
    score: int = 64,
    sector: str | None = None,
    correlation_group: str | None = None,
) -> CandidateResult:
    indicator_snapshot = {
        "earnings_penalty": 0,
        "volatility_penalty": 0,
        "volume_ratio_20d": 1.1,
    }
    if sector is not None:
        indicator_snapshot["sector"] = sector
    if correlation_group is not None:
        indicator_snapshot["correlation_group"] = correlation_group
    return CandidateResult(
        ticker=ticker,
        name="Apple Inc.",
        score=score,
        subscores=ScoreBreakdown(oversold=20, bottom_context=15, reversal=18, volume=6, market_context=5),
        tier=BUY_REVIEW_TIER,
        tier_reasons=["score, reversal, volume, and risk profile qualify for buy review"],
        reasons=["BB 하단 근처 또는 재진입 구간", "5일선 회복 또는 회복 시도"],
        risks=["중기 추세는 아직 하락 압력일 수 있음"],
        indicator_snapshot=indicator_snapshot,
        generated_at=datetime(2026, 4, 22, 7, 30, tzinfo=timezone.utc),
    )


def make_watchlist_candidate(
    *, ticker: str, score: int = 52, sector: str | None = None, correlation_group: str | None = None
) -> CandidateResult:
    from screener.scoring import WATCHLIST_TIER

    return make_candidate(
        ticker=ticker,
        score=score,
        sector=sector,
        correlation_group=correlation_group,
    ).model_copy(
        update={"tier": WATCHLIST_TIER, "tier_reasons": ["score below buy-review threshold"]}
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
    assert document.events[0].payload["tier"] == BUY_REVIEW_TIER
    assert next_state.tickers["AAPL"].last_delivery_tier == "single"


def test_build_daily_alert_document_marks_regime_unknown_when_benchmark_context_missing() -> None:
    document, _ = build_daily_alert_document(
        make_result([make_candidate()], bars_nonempty_count=95),
        state=AlertState(),
        artifact_directory="output/daily/2026-04-22",
        report_path="output/daily/2026-04-22/daily-report.json",
        metadata_path="output/daily/2026-04-22/run-metadata.json",
    )

    assert document.summary.regime_gate == "unknown"
    assert document.summary.regime_watchlist_cap is None
    assert document.summary.regime_gate_reason == "missing_benchmark_context"


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


def test_build_daily_alert_document_suppresses_repeated_digest_noise() -> None:
    candidate = make_candidate(score=64)
    document, next_state = build_daily_alert_document(
        make_result([candidate], bars_nonempty_count=95),
        state=AlertState(
            run_date="2026-04-22",
            tickers={
                "AAPL": TickerAlertState(
                    last_delivery_tier="digest",
                    last_material_signature=material_signature(candidate, rank=1),
                    last_phase="final",
                    last_emitted_at=datetime(2026, 4, 22, 15, 30, tzinfo=timezone.utc),
                    last_dedupe_key="old-digest-key",
                    last_score=64,
                    last_risk_adjusted_score=64,
                    last_rank=1,
                    last_headline_reason="BB 하단 근처 또는 재진입 구간",
                    last_headline_risk="중기 추세는 아직 하락 압력일 수 있음",
                    last_earnings_penalty=0,
                    last_volatility_penalty=0,
                )
            },
        ),
        artifact_directory="output/daily/2026-04-22",
        report_path="output/daily/2026-04-22/daily-report.json",
        metadata_path="output/daily/2026-04-22/run-metadata.json",
    )

    assert document.events == []
    assert document.summary.individual_event_count == 0
    assert document.summary.digest_event_count == 0
    assert next_state.tickers["AAPL"].last_delivery_tier == "digest"

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


def test_build_daily_alert_caps_watchlist_in_bearish_regime() -> None:
    buy_review_digest = make_candidate(ticker="BR0", score=55)
    candidates = [
        make_watchlist_candidate(ticker="W00"),
        make_watchlist_candidate(ticker="W01"),
        buy_review_digest,
        make_watchlist_candidate(ticker="W02"),
        make_watchlist_candidate(ticker="W03"),
        make_watchlist_candidate(ticker="W04"),
        make_watchlist_candidate(ticker="W05"),
    ]
    result = make_result(candidates, bars_nonempty_count=95)
    bearish_context = {"qqq_below_20d_ma": True, "qqq_return_20d": -7.0}

    document, next_state = build_daily_alert_document(
        result,
        state=AlertState(),
        artifact_directory="output/daily/2026-04-22",
        report_path="output/daily/2026-04-22/daily-report.json",
        metadata_path="output/daily/2026-04-22/run-metadata.json",
        benchmark_context=bearish_context,
    )

    assert document.summary.regime_gate == "capped"
    assert document.summary.regime_watchlist_cap == 3
    assert document.summary.regime_gate_reason == "bearish_qqq_regime"
    assert document.summary.eligible_candidate_count == 4
    assert document.summary.suppressed_candidate_count == 3
    digest_events = [e for e in document.events if e.event_type == "digest_alert"]
    assert len(digest_events) == 1
    assert digest_events[0].payload["member_count"] == 4
    assert [member["ticker"] for member in digest_events[0].payload["members"]] == [
        "W00",
        "W01",
        "BR0",
        "W02",
    ]
    assert set(next_state.tickers) == {"W00", "W01", "BR0", "W02"}


def test_build_daily_alert_does_not_cap_watchlist_in_normal_regime() -> None:
    candidates = [make_watchlist_candidate(ticker=f"T{i:02d}") for i in range(6)]
    result = make_result(candidates, bars_nonempty_count=95)
    normal_context = {"qqq_below_20d_ma": False, "qqq_return_20d": 1.0}

    document, next_state = build_daily_alert_document(
        result,
        state=AlertState(),
        artifact_directory="output/daily/2026-04-22",
        report_path="output/daily/2026-04-22/daily-report.json",
        metadata_path="output/daily/2026-04-22/run-metadata.json",
        benchmark_context=normal_context,
    )

    assert document.summary.regime_gate == "pass"
    assert document.summary.regime_watchlist_cap is None
    assert document.summary.suppressed_candidate_count == 0
    digest_events = [e for e in document.events if e.event_type == "digest_alert"]
    assert len(digest_events) == 1
    assert digest_events[0].payload["member_count"] == 6
    assert set(next_state.tickers) == {f"T{i:02d}" for i in range(6)}


def test_build_daily_alert_does_not_cap_when_close_equals_ma() -> None:
    candidates = [make_watchlist_candidate(ticker=f"T{i:02d}") for i in range(6)]
    result = make_result(candidates, bars_nonempty_count=95)
    equal_ma_context = {"qqq_below_20d_ma": False, "qqq_return_20d": -7.0}

    document, next_state = build_daily_alert_document(
        result,
        state=AlertState(),
        artifact_directory="output/daily/2026-04-22",
        report_path="output/daily/2026-04-22/daily-report.json",
        metadata_path="output/daily/2026-04-22/run-metadata.json",
        benchmark_context=equal_ma_context,
    )

    assert document.summary.regime_gate == "pass"
    assert document.summary.regime_watchlist_cap is None
    assert document.summary.suppressed_candidate_count == 0
    digest_events = [e for e in document.events if e.event_type == "digest_alert"]
    assert len(digest_events) == 1
    assert digest_events[0].payload["member_count"] == 6
    assert set(next_state.tickers) == {f"T{i:02d}" for i in range(6)}


def test_build_daily_alert_document_propagates_market_data_reliability_context() -> None:
    result = make_result([make_candidate()], bars_nonempty_count=95)
    result.metadata.reliability_label = "stale"
    result.metadata.market_data_provider_status = [
        {
            "provider": "twelve-data",
            "role": "primary",
            "status": "partial_success",
            "attempted_ticker_count": 100,
            "successful_ticker_count": 95,
            "failed_ticker_count": 5,
            "error_kind": "rate_limited",
        }
    ]

    document, _ = build_daily_alert_document(
        result,
        state=AlertState(),
        artifact_directory="output/daily/2026-04-22",
        report_path="output/daily/2026-04-22/daily-report.json",
        metadata_path="output/daily/2026-04-22/run-metadata.json",
    )

    assert document.summary.market_data_reliability == "stale"
    assert document.summary.market_data_provider_status == result.metadata.market_data_provider_status
    assert document.events[0].payload["market_data_reliability"] == "stale"


def test_build_daily_alert_limits_sector_concentration_in_bearish_regime() -> None:
    candidates = [
        make_watchlist_candidate(ticker="S0", sector="Technology"),
        make_watchlist_candidate(ticker="S1", sector="Technology"),
        make_watchlist_candidate(ticker="S2", sector="Technology"),
        make_watchlist_candidate(ticker="H0", sector="Healthcare"),
    ]

    document, next_state = build_daily_alert_document(
        make_result(candidates, bars_nonempty_count=95),
        state=AlertState(),
        artifact_directory="output/daily/2026-04-22",
        report_path="output/daily/2026-04-22/daily-report.json",
        metadata_path="output/daily/2026-04-22/run-metadata.json",
        benchmark_context={"qqq_below_20d_ma": True, "qqq_return_20d": -7.0},
    )

    assert document.summary.sector_concentration_gate == "capped"
    assert document.summary.sector_concentration_cap == 2
    assert document.summary.suppressed_by_sector_concentration_count == 1
    digest_event = [e for e in document.events if e.event_type == "digest_alert"][0]
    assert [member["ticker"] for member in digest_event.payload["members"]] == ["S0", "S1", "H0"]
    assert set(next_state.tickers) == {"S0", "S1", "H0"}


def test_build_daily_alert_limits_correlated_candidates_in_bearish_regime() -> None:
    candidates = [
        make_watchlist_candidate(ticker="C0", correlation_group="mega-cap-ai"),
        make_watchlist_candidate(ticker="C1", correlation_group="mega-cap-ai"),
        make_watchlist_candidate(ticker="C2", correlation_group="mega-cap-ai"),
        make_watchlist_candidate(ticker="U0", correlation_group="software"),
    ]

    document, next_state = build_daily_alert_document(
        make_result(candidates, bars_nonempty_count=95),
        state=AlertState(),
        artifact_directory="output/daily/2026-04-22",
        report_path="output/daily/2026-04-22/daily-report.json",
        metadata_path="output/daily/2026-04-22/run-metadata.json",
        benchmark_context={"qqq_below_20d_ma": True, "qqq_return_20d": -7.0},
    )

    assert document.summary.correlation_gate == "capped"
    assert document.summary.correlation_group_cap == 2
    assert document.summary.suppressed_by_correlation_count == 1
    digest_event = [e for e in document.events if e.event_type == "digest_alert"][0]
    assert [member["ticker"] for member in digest_event.payload["members"]] == ["C0", "C1", "U0"]
    assert set(next_state.tickers) == {"C0", "C1", "U0"}


def test_build_daily_alert_limits_single_candidate_sector_concentration_in_bearish_regime() -> None:
    candidates = [
        make_candidate(ticker="B0", sector="Technology"),
        make_candidate(ticker="B1", sector="Technology"),
        make_candidate(ticker="B2", sector="Technology"),
    ]

    document, next_state = build_daily_alert_document(
        make_result(candidates, bars_nonempty_count=95),
        state=AlertState(),
        artifact_directory="output/daily/2026-04-22",
        report_path="output/daily/2026-04-22/daily-report.json",
        metadata_path="output/daily/2026-04-22/run-metadata.json",
        benchmark_context={"qqq_below_20d_ma": True, "qqq_return_20d": -7.0},
    )

    assert document.summary.sector_concentration_gate == "capped"
    assert document.summary.suppressed_by_sector_concentration_count == 1
    assert [event.payload["ticker"] for event in document.events] == ["B0", "B1"]
    assert set(next_state.tickers) == {"B0", "B1"}
