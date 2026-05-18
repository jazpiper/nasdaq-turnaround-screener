from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from screener.models import CandidateResult, PreviousCandidateOutcome, RunMetadata, ScreenRunResult, ScoreBreakdown
from screener.reporting.markdown import build_markdown_report


def test_markdown_report_includes_risk_adjusted_score() -> None:
    generated_at = datetime(2026, 4, 30, 20, 0, tzinfo=timezone.utc)
    result = ScreenRunResult(
        metadata=RunMetadata(
            run_date=date(2026, 4, 30),
            generated_at=generated_at,
            artifact_directory=Path("output/daily/2026-04-30"),
        ),
        candidates=[
            CandidateResult(
                ticker="EA",
                score=65,
                risk_adjusted_score=62,
                subscores=ScoreBreakdown(reversal=25),
                tier="buy-review",
                tier_reasons=["score, reversal, volume, and risk profile qualify for buy review"],
                reasons=["5일선 회복 또는 회복 시도"],
                risks=["최근 20일 기준 시장 대비 상대약세가 큼"],
                generated_at=generated_at,
            )
        ],
    )

    report = build_markdown_report(result)

    assert "- **Score**: 65" in report
    assert "- **Risk-adjusted score**: 62" in report


def test_markdown_report_puts_previous_candidate_outcomes_near_top() -> None:
    generated_at = datetime(2026, 5, 1, 20, 0, tzinfo=timezone.utc)
    result = ScreenRunResult(
        metadata=RunMetadata(
            run_date=date(2026, 5, 1),
            generated_at=generated_at,
            artifact_directory=Path("output/daily/2026-05-01"),
        ),
        previous_candidate_outcomes=[
            PreviousCandidateOutcome(
                ticker="AAPL",
                name="Apple Inc.",
                previous_close=100.0,
                current_close=103.25,
                absolute_return=3.25,
                percent_return=3.25,
                previous_score=70,
                previous_tier="buy-review",
            )
        ],
    )

    report = build_markdown_report(result)

    assert report.index("## Previous Candidate T+1 Outcomes") < report.index("## Review Candidates")
    assert "- **AAPL (Apple Inc.)**: T+1 +3.25% (+3.25)" in report


def test_markdown_report_includes_reliability_label_without_provider_status() -> None:
    generated_at = datetime(2026, 5, 1, 20, 0, tzinfo=timezone.utc)
    result = ScreenRunResult(
        metadata=RunMetadata(
            run_date=date(2026, 5, 1),
            generated_at=generated_at,
            artifact_directory=Path("output/daily/2026-05-01"),
            reliability_label="stale",
        ),
    )

    report = build_markdown_report(result)

    assert "## Market Data Reliability" in report
    assert "- **Reliability label**: stale" in report
