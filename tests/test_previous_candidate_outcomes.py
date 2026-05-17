from __future__ import annotations

import json

from screener.reporting.outcomes import build_previous_candidate_outcomes


def test_build_previous_candidate_outcomes_uses_latest_prior_daily_report(tmp_path) -> None:
    old_dir = tmp_path / "2026-04-29"
    previous_dir = tmp_path / "2026-04-30"
    current_dir = tmp_path / "2026-05-01"
    for path in (old_dir, previous_dir, current_dir):
        path.mkdir()
    (old_dir / "daily-report.json").write_text(
        json.dumps({"candidates": [{"ticker": "OLD", "close": 10.0}]}),
        encoding="utf-8",
    )
    (previous_dir / "daily-report.json").write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "ticker": "AAPL",
                        "name": "Apple Inc.",
                        "close": 100.0,
                        "score": 70,
                        "risk_adjusted_score": 68,
                        "tier": "buy-review",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (current_dir / "daily-report.json").write_text(
        json.dumps({"candidates": [{"ticker": "FUTURE", "close": 10.0}]}),
        encoding="utf-8",
    )

    outcomes = build_previous_candidate_outcomes(
        current_run_date="2026-05-01",
        current_closes={"AAPL": 103.25},
        daily_output_root=tmp_path,
    )

    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.ticker == "AAPL"
    assert outcome.absolute_return == 3.25
    assert outcome.percent_return == 3.25
    assert outcome.previous_risk_adjusted_score == 68
