from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from screener.models import CandidateResult, RunMetadata, ScoreBreakdown, ScreenRunResult
from screener.reporting.json_report import build_json_report


def test_daily_json_report_schema_has_version_and_deterministic_sample() -> None:
    result = ScreenRunResult(
        metadata=RunMetadata(
            run_date=date(2026, 4, 22),
            generated_at=datetime(2026, 4, 22, 20, 5, tzinfo=timezone.utc),
            universe="unit-test-universe",
            dry_run=False,
            artifact_directory=Path("output/daily/2026-04-22"),
            planned_ticker_count=2,
            successful_ticker_count=1,
            failed_ticker_count=1,
            bars_nonempty_count=1,
            latest_bar_date_mismatch_count=0,
            insufficient_history_count=0,
            planned_tickers=["AAPL", "MSFT"],
            data_failures=["MSFT: no rows"],
            reliability_label="partial",
            run_status="success",
            quality_gate="warn",
            quality_gate_reasons=["1 data failure"],
        ),
        candidates=[
            CandidateResult(
                ticker="AAPL",
                name="Apple Inc.",
                score=74,
                risk_adjusted_score=68,
                subscores=ScoreBreakdown(
                    oversold=20,
                    bottom_context=15,
                    reversal=18,
                    volume=11,
                    market_context=10,
                ),
                tier="buy-review",
                tier_reasons=["high score"],
                close=180.25,
                lower_bb=175.1,
                rsi14=31.4,
                distance_to_20d_low=0.08,
                reasons=["RSI near oversold", "volume confirmed"],
                risks=["earnings in 7 days"],
                indicator_snapshot={"close": 180.25, "rsi14": 31.4},
                snapshot_schema_version=2,
                generated_at=datetime(2026, 4, 22, 20, 5, tzinfo=timezone.utc),
            )
        ],
    )

    report = build_json_report(result)

    assert report["schema_version"] == 1
    assert list(report) == [
        "schema_version",
        "date",
        "generated_at",
        "universe",
        "run_mode",
        "dry_run",
        "planned_ticker_count",
        "successful_ticker_count",
        "failed_ticker_count",
        "bars_nonempty_count",
        "latest_bar_date_mismatch_count",
        "insufficient_history_count",
        "planned_tickers",
        "candidate_count",
        "data_failures",
        "market_data_provider_status",
        "reliability_label",
        "market_data_reliability",
        "run_started_at",
        "run_completed_at",
        "run_duration_seconds",
        "run_status",
        "quality_gate",
        "quality_gate_reasons",
        "observability",
        "notes",
        "previous_candidate_outcomes",
        "candidates",
    ]
    assert report["candidates"] == [
        {
            "ticker": "AAPL",
            "name": "Apple Inc.",
            "score": 74,
            "risk_adjusted_score": 68,
            "subscores": {
                "oversold": 20,
                "bottom_context": 15,
                "reversal": 18,
                "volume": 11,
                "market_context": 10,
            },
            "tier": "buy-review",
            "tier_reasons": ["high score"],
            "close": 180.25,
            "lower_bb": 175.1,
            "rsi14": 31.4,
            "distance_to_20d_low": 0.08,
            "reasons": ["RSI near oversold", "volume confirmed"],
            "risks": ["earnings in 7 days"],
            "indicator_snapshot": {"close": 180.25, "rsi14": 31.4},
            "snapshot_schema_version": 2,
            "generated_at": "2026-04-22T20:05:00Z",
        }
    ]
