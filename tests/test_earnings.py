from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from screener.data.earnings import FileBackedEarningsCalendarProvider
from screener.scoring.ranking import score_candidate


def test_file_backed_earnings_provider_computes_day_offsets(tmp_path: Path) -> None:
    path = tmp_path / "earnings-calendar.json"
    path.write_text(
        json.dumps(
            {
                "AAPL": {
                    "next_earnings_date": "2026-04-25",
                    "last_earnings_date": "2026-01-30"
                },
                "MSFT": {
                    "days_to_next_earnings": 8,
                    "days_since_last_earnings": 80
                }
            }
        ),
        encoding="utf-8",
    )

    provider = FileBackedEarningsCalendarProvider(path)
    result = provider.fetch(["AAPL", "MSFT", "NVDA"], date(2026, 4, 21))

    assert result["AAPL"].days_to_next_earnings == 4
    assert result["AAPL"].days_since_last_earnings == 81
    assert result["MSFT"].days_to_next_earnings == 8
    assert "NVDA" not in result


def test_score_candidate_applies_earnings_penalty_and_risk() -> None:
    candidate = score_candidate(
        {
            "ticker": "AAPL",
            "bars_available": 90,
            "average_volume_20d": 2_000_000,
            "close": 100.0,
            "low": 98.0,
            "bb_lower": 99.0,
            "rsi_14": 30.0,
            "distance_to_20d_low": 1.0,
            "distance_to_60d_low": 4.0,
            "sma_5": 99.5,
            "sma_20": 101.0,
            "sma_60": 100.0,
            "volume_ratio_20d": 1.0,
            "close_improvement_streak": 2,
            "rsi_3d_change": 2.0,
            "market_context_score": 10.0,
            "weekly_trend_penalty": 0.0,
            "weekly_trend_severe_damage": False,
            "days_to_next_earnings": 1,
            "days_since_last_earnings": 40,
        }
    )

    assert candidate.snapshot["earnings_penalty"] == 8
    assert "실적 발표가 임박해 이벤트 리스크가 큼" in candidate.risks
    assert candidate.score < sum(candidate.subscores.values())
