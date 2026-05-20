from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, cast
from typer.testing import CliRunner

from screener.cli.main import app
from screener.recommendations import build_daily_top3_recommendations, initialize_recommendation_db


def _candidate(ticker: str, risk_adjusted: int, score: int, **overrides: object) -> dict[str, object]:
    snapshot = {
        "close": 100.0,
        "low": 98.0,
        "bb_lower": 99.0,
        "rsi_14": 31.0,
        "sma_5": 101.0,
        "sma_20": 105.0,
        "sma_60": 110.0,
        "distance_to_20d_low": 2.0,
        "distance_to_60d_low": 6.0,
        "average_volume_20d": 2_000_000,
        "volume_ratio_20d": 1.2,
        "close_improvement_streak": 2,
        "rsi_3d_change": 4.0,
        "weekly_trend_penalty": 0,
        "weekly_trend_severe_damage": False,
        "atr_14_pct": 3.0,
        "daily_range_pct": 2.0,
        "bb_width_pct": 8.0,
        "days_to_next_earnings": 10,
        "days_since_last_earnings": 20,
        "rel_strength_20d_vs_qqq": 1.5,
        "rel_strength_60d_vs_qqq": 2.0,
        "market_context_score": 8,
        "earnings_penalty": 0,
        "volatility_penalty": 0,
        "severe_weekly_penalty": 0,
        "risk_adjustment_penalty": score - risk_adjusted,
        "risk_adjusted_score": risk_adjusted,
        "snapshot_schema_version": 2,
        "source_provider": "fixture",
        "source_timestamp": "2026-05-19T20:00:00+00:00",
        "freshness_label": "fresh",
        "reliability_label": "ok",
    }
    extra_snapshot = cast(dict[str, Any], overrides.pop("indicator_snapshot", {}) or {})
    snapshot.update(extra_snapshot)
    return {
        "ticker": ticker,
        "name": f"{ticker} Corp",
        "score": score,
        "risk_adjusted_score": risk_adjusted,
        "subscores": {
            "oversold": 20,
            "bottom_context": 18,
            "reversal": 21,
            "volume": 12,
            "market_context": 10,
        },
        "tier": "buy-review",
        "tier_reasons": ["buy-review threshold met"],
        "close": snapshot["close"],
        "reasons": ["BB 하단 근처", "5일선 회복 시도"],
        "risks": ["중기 추세 확인 필요"],
        "indicator_snapshot": snapshot,
        "snapshot_schema_version": 2,
        "generated_at": "2026-05-19T20:10:00+00:00",
        **overrides,
    }


def _daily_report(candidates: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "date": "2026-05-19",
        "generated_at": "2026-05-19T20:15:00+00:00",
        "universe": "NASDAQ-100",
        "planned_ticker_count": 5,
        "successful_ticker_count": 4,
        "candidate_count": len(candidates),
        "reliability_label": "ok",
        "data_failures": ["MISS"],
        "candidates": candidates,
    }


def test_build_daily_top3_recommendations_persists_snapshot_and_artifacts(tmp_path: Path) -> None:
    report_path = tmp_path / "daily-report.json"
    db_path = tmp_path / "recommendations.sqlite3"
    output_dir = tmp_path / "recommendations"
    report_path.write_text(
        json.dumps(
            _daily_report(
                [
                    _candidate("BBB", 71, 80),
                    _candidate("AAA", 71, 80),
                    _candidate("EEE", 90, 90, indicator_snapshot={"days_to_next_earnings": 3.9}),
                    _candidate("CCC", 69, 78),
                    _candidate("DDD", 65, 75, indicator_snapshot={"days_to_next_earnings": 2}),
                ]
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = build_daily_top3_recommendations(
        daily_report_path=report_path,
        db_path=db_path,
        output_dir=output_dir,
    )

    assert result.run_id == 1
    assert [item["ticker"] for item in result.payload["recommendations"]] == ["EEE", "AAA", "BBB"]
    assert result.json_path.exists()
    assert result.markdown_path.exists()
    assert "사면 안 되는 이유/주의점" in result.markdown_path.read_text(encoding="utf-8")

    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute("select name from sqlite_master where type = 'table'")}
        assert {"algorithm_versions", "recommendation_runs", "recommendations", "recommendation_features", "recommendation_outcomes"} <= tables
        run = conn.execute("select algorithm_version, selected_candidate_count, report_path, metadata_path from recommendation_runs").fetchone()
        assert run[0] == "daily-top3-v0"
        assert run[1] == 3
        assert run[2].endswith("daily-top3-recommendations.md")
        assert run[3].endswith("daily-top3-recommendations.json")
        rows = conn.execute(
            """
            select rank, ticker, price, reference_price, buy_limit_price,
                   stop_loss_price, target_sell_price_1, target_sell_price_2,
                   invalidation_price, risk_reward_ratio, expected_holding_days,
                   time_stop_date, price_method, price_formula, risk_adjusted_score
            from recommendations
            order by rank
            """
        ).fetchall()
        assert rows == [
            (
                1,
                "EEE",
                100.0,
                100.0,
                101.0,
                92.0,
                112.0,
                124.0,
                92.0,
                1.5,
                20,
                "2026-06-08",
                "close_based_v1",
                "reference=latest close; buy_limit=reference*1.01; stop/invalidation=reference*0.92; targets=reference*1.12/1.24; R/R=(target1-reference)/(reference-stop)",
                90.0,
            ),
            (
                2,
                "AAA",
                100.0,
                100.0,
                101.0,
                92.0,
                112.0,
                124.0,
                92.0,
                1.5,
                20,
                "2026-06-08",
                "close_based_v1",
                "reference=latest close; buy_limit=reference*1.01; stop/invalidation=reference*0.92; targets=reference*1.12/1.24; R/R=(target1-reference)/(reference-stop)",
                71.0,
            ),
            (
                3,
                "BBB",
                100.0,
                100.0,
                101.0,
                92.0,
                112.0,
                124.0,
                92.0,
                1.5,
                20,
                "2026-06-08",
                "close_based_v1",
                "reference=latest close; buy_limit=reference*1.01; stop/invalidation=reference*0.92; targets=reference*1.12/1.24; R/R=(target1-reference)/(reference-stop)",
                71.0,
            ),
        ]
        features = conn.execute("select feature_name from recommendation_features where recommendation_id = 1").fetchall()
        assert ("close",) in features
        outcomes = conn.execute(
            "select horizon_label, entry_price, stop_loss_price, target_sell_price_1, invalidation_price, outcome_status from recommendation_outcomes where recommendation_id = 1 order by horizon_days"
        ).fetchall()
        assert outcomes == [
            ("D+1", 100.0, 92.0, 112.0, 92.0, "pending"),
            ("D+5", 100.0, 92.0, 112.0, 92.0, "pending"),
            ("D+20", 100.0, 92.0, 112.0, 92.0, "pending"),
            ("D+60", 100.0, 92.0, 112.0, 92.0, "pending"),
        ]

    artifact = json.loads(result.json_path.read_text(encoding="utf-8"))
    first = artifact["recommendations"][0]
    assert artifact["selection_method"]["pipeline"] == [
        "universe_filter",
        "risk_exclusion_gate",
        "score_components",
        "diversification_tie_break",
        "top3_rank",
    ]
    assert first["reference_price"] == 100.0
    assert first["buy_limit_price"] == 101.0
    assert first["stop_loss_price"] == 92.0
    assert first["target_sell_price_1"] == 112.0
    assert first["target_sell_price_2"] == 124.0
    assert first["invalidation_price"] == 92.0
    assert first["risk_reward_ratio"] == 1.5
    assert first["expected_holding_days"] == 20
    assert first["time_stop_date"] == "2026-06-08"
    assert first["price_method"] == "close_based_v1"
    assert first["price_formula"] == "reference=latest close; buy_limit=reference*1.01; stop/invalidation=reference*0.92; targets=reference*1.12/1.24; R/R=(target1-reference)/(reference-stop)"
    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "추천 종목 선정 방식" in markdown
    assert "**매수가(상한)**: 101.0" in markdown
    assert "**목표 매도가 1**: 112.0" in markdown
    assert "**손절/무효화가**: 92.0 / 92.0" in markdown


def test_initialize_recommendation_db_migrates_existing_price_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            create table recommendations (
                recommendation_id integer primary key autoincrement,
                run_id integer not null,
                rank integer not null,
                ticker text not null,
                price real
            );
            create table recommendation_outcomes (
                outcome_id integer primary key autoincrement,
                recommendation_id integer not null,
                horizon_days integer not null,
                horizon_label text not null,
                entry_date text not null,
                entry_price real,
                outcome_status text not null default 'pending'
            );
            """
        )

    initialize_recommendation_db(db_path)

    with sqlite3.connect(db_path) as conn:
        recommendation_columns = {row[1] for row in conn.execute("pragma table_info(recommendations)")}
        outcome_columns = {row[1] for row in conn.execute("pragma table_info(recommendation_outcomes)")}
    assert {
        "reference_price",
        "buy_limit_price",
        "stop_loss_price",
        "target_sell_price_1",
        "target_sell_price_2",
        "invalidation_price",
        "risk_reward_ratio",
        "expected_holding_days",
        "price_method",
        "price_formula",
    } <= recommendation_columns
    assert {"stop_loss_price", "target_sell_price_1", "target_sell_price_2", "invalidation_price", "price_method"} <= outcome_columns


def test_cli_build_daily_top3_recommendations_writes_report(tmp_path: Path) -> None:
    report_path = tmp_path / "daily-report.json"
    db_path = tmp_path / "recommendations.sqlite3"
    output_dir = tmp_path / "recommendations"
    report_path.write_text(json.dumps(_daily_report([_candidate("AAA", 70, 78)])), encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "build-daily-top3-recommendations",
            "--daily-report-path",
            str(report_path),
            "--db-path",
            str(db_path),
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Selected recommendations: 1" in result.output
    assert (output_dir / "2026-05-19" / "daily-top3-recommendations.md").exists()
    assert db_path.exists()
