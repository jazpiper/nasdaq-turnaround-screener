from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from screener.data import DailyBar, FetchResult
from screener.recommendations import build_daily_top3_recommendations
from scripts import update_recommendation_outcomes as script


def _daily_report() -> dict[str, object]:
    return {
        "schema_version": 1,
        "date": "2026-05-19",
        "generated_at": "2026-05-19T20:15:00+00:00",
        "universe": "nasdaq-expanded-500",
        "planned_ticker_count": 3,
        "successful_ticker_count": 3,
        "candidate_count": 1,
        "reliability_label": "ok",
        "data_failures": [],
        "candidates": [
            {
                "ticker": "AAA",
                "name": "AAA Corp",
                "score": 80,
                "risk_adjusted_score": 80,
                "subscores": {"oversold": 20, "bottom_context": 20, "reversal": 20, "volume": 10, "market_context": 10},
                "close": 100.0,
                "reasons": ["test setup"],
                "risks": [],
                "indicator_snapshot": {
                    "close": 100.0,
                    "low": 99.0,
                    "bb_lower": 98.0,
                    "rsi_14": 32.0,
                    "distance_to_20d_low": 2.0,
                    "volume_ratio_20d": 1.2,
                    "weekly_trend_severe_damage": False,
                    "days_to_next_earnings": 10,
                    "source_provider": "fixture",
                    "source_timestamp": "2026-05-19T20:00:00+00:00",
                    "freshness_label": "fresh",
                    "reliability_label": "ok",
                },
                "generated_at": "2026-05-19T20:10:00+00:00",
            }
        ],
    }


class StubFetcher:
    def fetch(self, tickers):
        seen = set(tickers)
        assert {"AAA", "SPY", "QQQ"}.issubset(seen)
        bars = [
            DailyBar("AAA", date(2026, 5, 20), 100.0, 114.0, 99.0, 112.0, 112.0, 1000),
            DailyBar("SPY", date(2026, 5, 20), 500.0, 505.0, 499.0, 502.0, 502.0, 1000),
            DailyBar("QQQ", date(2026, 5, 20), 400.0, 402.0, 398.0, 401.0, 401.0, 1000),
        ]
        return FetchResult(
            bars_by_ticker={"AAA": [bars[0]], "SPY": [bars[1]], "QQQ": [bars[2]]},
            failed_tickers={},
            source_statuses=[{"provider": "stub", "successful": 3}],
        )


def test_wrapper_fetches_pending_tickers_writes_ohlc_updates_and_summarizes(tmp_path: Path) -> None:
    report_path = tmp_path / "daily-report.json"
    db_path = tmp_path / "recommendations.sqlite3"
    recommendations_dir = tmp_path / "recommendations"
    market_ohlc_path = tmp_path / "market-ohlc.json"
    summary_path = tmp_path / "outcome-summary.json"
    report_path.write_text(json.dumps(_daily_report()), encoding="utf-8")
    build_daily_top3_recommendations(daily_report_path=report_path, db_path=db_path, output_dir=recommendations_dir)

    result = script.run_outcome_update(
        db_path=db_path,
        market_ohlc_path=market_ohlc_path,
        summary_path=summary_path,
        as_of_date="2026-05-20",
        fetcher=StubFetcher(),
    )

    assert result["pending_ticker_count"] == 3
    assert result["settled_outcomes"] >= 1
    assert market_ohlc_path.exists()
    payload = json.loads(market_ohlc_path.read_text(encoding="utf-8"))
    assert payload["AAA"]["2026-05-20"]["close"] == 112.0
    assert summary_path.exists()
    with sqlite3.connect(db_path) as conn:
        statuses = {row[0] for row in conn.execute("select outcome_status from recommendation_outcomes")}
    assert "settled" in statuses


def test_wrapper_returns_no_work_message_when_there_are_no_pending_tickers(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.sqlite3"
    result = script.run_outcome_update(
        db_path=db_path,
        market_ohlc_path=tmp_path / "market-ohlc.json",
        summary_path=tmp_path / "summary.json",
        as_of_date="2026-05-20",
        fetcher=pytest.fail,
    )

    assert result["pending_ticker_count"] == 0
    assert result["message"] == "No pending recommendation outcomes."
