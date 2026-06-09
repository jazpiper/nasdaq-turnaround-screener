from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, cast

import pytest
from typer.testing import CliRunner

from screener.cli.main import app
from screener.recommendations import (
    DailyArtifactConsistencyError,
    build_daily_top3_recommendations,
    initialize_recommendation_db,
    summarize_recommendation_outcomes,
    update_recommendation_outcomes,
    validate_daily_artifact_consistency,
)


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


def _daily_report(candidates: list[dict[str, object]], *, run_date: str = "2026-05-19") -> dict[str, object]:
    return {
        "schema_version": 1,
        "date": run_date,
        "generated_at": f"{run_date}T20:15:00+00:00",
        "universe": "NASDAQ-100",
        "planned_ticker_count": 5,
        "successful_ticker_count": 4,
        "candidate_count": len(candidates),
        "reliability_label": "ok",
        "data_failures": ["MISS"],
        "candidates": candidates,
    }


def _write_latest_daily_artifacts(
    tmp_path: Path,
    *,
    latest_target_date: str,
    report_date: str,
    metadata_run_date: str,
) -> Path:
    output_root = tmp_path / "output" / "daily"
    run_dir = output_root / latest_target_date
    latest_dir = output_root / "latest"
    run_dir.mkdir(parents=True)
    latest_dir.symlink_to(run_dir.name, target_is_directory=True)
    (run_dir / "daily-report.json").write_text(
        json.dumps(_daily_report([_candidate("AAA", 70, 78)], run_date=report_date)),
        encoding="utf-8",
    )
    (run_dir / "run-metadata.json").write_text(json.dumps({"run_date": metadata_run_date}), encoding="utf-8")
    return latest_dir / "daily-report.json"


def test_latest_daily_artifact_consistency_accepts_matching_dates(tmp_path: Path) -> None:
    report_path = _write_latest_daily_artifacts(
        tmp_path,
        latest_target_date="2026-05-19",
        report_date="2026-05-19",
        metadata_run_date="2026-05-19",
    )
    daily_report = json.loads(report_path.read_text(encoding="utf-8"))

    validate_daily_artifact_consistency(report_path, daily_report=daily_report)


@pytest.mark.parametrize(
    ("latest_target_date", "report_date", "metadata_run_date", "expected_error"),
    [
        (
            "2026-05-08",
            "2026-05-19",
            "2026-05-19",
            "latest_target!=daily-report.date:2026-05-08!=2026-05-19",
        ),
        (
            "2026-05-19",
            "2026-05-19",
            "2026-05-08",
            "daily-report.date!=run-metadata.run_date:2026-05-19!=2026-05-08",
        ),
        (
            "2026-05-08",
            "2026-05-08",
            "2026-05-19",
            "latest_target!=run-metadata.run_date:2026-05-08!=2026-05-19",
        ),
    ],
)
def test_latest_daily_artifact_consistency_rejects_date_mismatches(
    tmp_path: Path,
    latest_target_date: str,
    report_date: str,
    metadata_run_date: str,
    expected_error: str,
) -> None:
    report_path = _write_latest_daily_artifacts(
        tmp_path,
        latest_target_date=latest_target_date,
        report_date=report_date,
        metadata_run_date=metadata_run_date,
    )
    daily_report = json.loads(report_path.read_text(encoding="utf-8"))

    with pytest.raises(DailyArtifactConsistencyError, match=expected_error):
        validate_daily_artifact_consistency(report_path, daily_report=daily_report)


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


def test_cli_build_daily_top3_recommendations_fails_on_latest_date_mismatch(tmp_path: Path) -> None:
    output_root = tmp_path / "output" / "daily"
    run_dir = output_root / "2026-05-08"
    latest_dir = output_root / "latest"
    run_dir.mkdir(parents=True)
    latest_dir.symlink_to(run_dir.name, target_is_directory=True)

    (run_dir / "daily-report.json").write_text(
        json.dumps(_daily_report([_candidate("AAA", 70, 78)], run_date="2026-05-19")),
        encoding="utf-8",
    )
    (run_dir / "run-metadata.json").write_text(json.dumps({"run_date": "2026-05-08"}), encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "build-daily-top3-recommendations",
            "--daily-report-path",
            str(latest_dir / "daily-report.json"),
            "--db-path",
            str(tmp_path / "recommendations.sqlite3"),
            "--output-dir",
            str(tmp_path / "recommendations"),
        ],
    )

    assert result.exit_code == 1
    assert "Daily artifact consistency check failed:" in result.output
    assert "daily-report.date!=run-metadata.run_date:2026-05-19!=2026-05-08" in result.output
    assert "latest_target!=daily-report.date:2026-05-08!=2026-05-19" in result.output


def _ohlcv(close: float, *, high: float | None = None, low: float | None = None) -> dict[str, float]:
    return {"open": close, "high": high if high is not None else close, "low": low if low is not None else close, "close": close}


def _market_prices() -> dict[str, dict[str, dict[str, float]]]:
    return {
        "AAA": {
            "2026-05-20": _ohlcv(102.0, high=103.0, low=101.0),
            "2026-05-21": _ohlcv(110.0, high=113.0, low=102.0),
            "2026-05-24": _ohlcv(106.0, high=108.0, low=96.0),
            "2026-06-08": _ohlcv(115.0, high=116.0, low=95.0),
            "2026-07-18": _ohlcv(130.0, high=132.0, low=94.0),
        },
        "SPY": {
            "2026-05-19": _ohlcv(500.0),
            "2026-05-20": _ohlcv(505.0),
            "2026-05-24": _ohlcv(510.0),
            "2026-06-08": _ohlcv(520.0),
            "2026-07-18": _ohlcv(550.0),
        },
        "QQQ": {
            "2026-05-19": _ohlcv(400.0),
            "2026-05-20": _ohlcv(404.0),
            "2026-05-24": _ohlcv(408.0),
            "2026-06-08": _ohlcv(416.0),
            "2026-07-18": _ohlcv(440.0),
        },
    }


def test_update_recommendation_outcomes_settles_horizons_and_price_simulation(tmp_path: Path) -> None:
    report_path = tmp_path / "daily-report.json"
    db_path = tmp_path / "recommendations.sqlite3"
    output_dir = tmp_path / "recommendations"
    report_path.write_text(json.dumps(_daily_report([_candidate("AAA", 70, 78)])), encoding="utf-8")
    build_daily_top3_recommendations(daily_report_path=report_path, db_path=db_path, output_dir=output_dir)

    result = update_recommendation_outcomes(
        db_path=db_path,
        prices_by_ticker=_market_prices(),
        as_of_date="2026-07-20",
    )

    assert result["settled_outcomes"] == 4
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            select horizon_label, horizon_date, exit_price, absolute_return_pct,
                   spy_return_pct, qqq_return_pct, relative_return_vs_spy_pct,
                   max_drawdown_pct, max_drawdown_available, outcome_status,
                   fill_status, fill_date, fill_price, target1_hit, target1_hit_date,
                   stop_hit, stop_hit_date, exit_reason, r_multiple
            from recommendation_outcomes
            where horizon_days = 1
            """
        ).fetchone()
    assert row == (
        "D+1",
        "2026-05-20",
        102.0,
        0.99,
        1.0,
        1.0,
        -0.01,
        0.0,
        1,
        "settled",
        "filled",
        "2026-05-20",
        101.0,
        0,
        None,
        0,
        None,
        "horizon_close",
        0.11,
    )


def test_update_recommendation_outcomes_uses_next_available_market_day_for_weekend_horizon(tmp_path: Path) -> None:
    report_path = tmp_path / "daily-report.json"
    db_path = tmp_path / "recommendations.sqlite3"
    output_dir = tmp_path / "recommendations"
    report_path.write_text(
        json.dumps(_daily_report([_candidate("AAA", 70, 78)], run_date="2026-05-22")),
        encoding="utf-8",
    )
    build_daily_top3_recommendations(daily_report_path=report_path, db_path=db_path, output_dir=output_dir)

    prices = {
        "AAA": {
            "2026-05-25": _ohlcv(104.0, high=105.0, low=100.0),
        },
        "SPY": {
            "2026-05-22": _ohlcv(500.0),
            "2026-05-25": _ohlcv(505.0),
        },
        "QQQ": {
            "2026-05-22": _ohlcv(400.0),
            "2026-05-25": _ohlcv(404.0),
        },
    }
    result = update_recommendation_outcomes(db_path=db_path, prices_by_ticker=prices, as_of_date="2026-05-25")

    assert result["settled_outcomes"] == 1
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "select horizon_label, horizon_date, outcome_status, exit_price, absolute_return_pct from recommendation_outcomes where horizon_days = 1"
        ).fetchone()
    assert row == ("D+1", "2026-05-25", "settled", 104.0, 2.97)


def test_update_recommendation_outcomes_marks_no_fill_and_unobservable(tmp_path: Path) -> None:
    report_path = tmp_path / "daily-report.json"
    db_path = tmp_path / "recommendations.sqlite3"
    output_dir = tmp_path / "recommendations"
    report_path.write_text(json.dumps(_daily_report([_candidate("AAA", 70, 78)])), encoding="utf-8")
    build_daily_top3_recommendations(daily_report_path=report_path, db_path=db_path, output_dir=output_dir)

    prices = _market_prices()
    prices["AAA"] = {"2026-05-20": _ohlcv(103.0, high=105.0, low=102.0)}
    result = update_recommendation_outcomes(db_path=db_path, prices_by_ticker=prices, as_of_date="2026-05-20")

    assert result["settled_outcomes"] == 1
    with sqlite3.connect(db_path) as conn:
        statuses = conn.execute(
            "select horizon_label, outcome_status, observation_note, fill_status from recommendation_outcomes order by horizon_days"
        ).fetchall()
    assert statuses == [
        ("D+1", "no_fill", "buy_limit_not_touched", "no_fill"),
        ("D+5", "pending", "insufficient_future_prices", None),
        ("D+20", "pending", "insufficient_future_prices", None),
        ("D+60", "pending", "insufficient_future_prices", None),
    ]


def test_summarize_recommendation_outcomes_by_algorithm_version(tmp_path: Path) -> None:
    report_path = tmp_path / "daily-report.json"
    db_path = tmp_path / "recommendations.sqlite3"
    output_dir = tmp_path / "recommendations"
    report_path.write_text(json.dumps(_daily_report([_candidate("AAA", 70, 78)])), encoding="utf-8")
    build_daily_top3_recommendations(daily_report_path=report_path, db_path=db_path, output_dir=output_dir)
    update_recommendation_outcomes(db_path=db_path, prices_by_ticker=_market_prices(), as_of_date="2026-07-20")

    artifact_path = tmp_path / "summary.json"
    summary = summarize_recommendation_outcomes(db_path=db_path, output_path=artifact_path)

    assert artifact_path.exists()
    version = summary["algorithm_versions"][0]
    assert version["algorithm_version"] == "daily-top3-v0"
    assert version["sample_size"] == 4
    assert version["hit_rate_pct"] == 100.0
    assert version["target1_hit_rate_pct"] == 75.0
    assert version["stop_hit_rate_pct"] == 0.0
    assert version["no_fill_rate_pct"] == 0.0
    assert version["avg_absolute_return_pct"] == 12.13
    assert version["median_absolute_return_pct"] == 9.4
    assert version["avg_relative_return_vs_spy_pct"] == 7.88
    assert "improvement_suggestions" in summary


def test_cli_update_and_summarize_recommendation_outcomes(tmp_path: Path) -> None:
    report_path = tmp_path / "daily-report.json"
    prices_path = tmp_path / "prices.json"
    db_path = tmp_path / "recommendations.sqlite3"
    output_dir = tmp_path / "recommendations"
    summary_path = tmp_path / "summary.json"
    report_path.write_text(json.dumps(_daily_report([_candidate("AAA", 70, 78)])), encoding="utf-8")
    prices_path.write_text(json.dumps(_market_prices()), encoding="utf-8")
    build_daily_top3_recommendations(daily_report_path=report_path, db_path=db_path, output_dir=output_dir)

    update_result = CliRunner().invoke(
        app,
        [
            "update-recommendation-outcomes",
            "--db-path",
            str(db_path),
            "--prices-path",
            str(prices_path),
            "--as-of-date",
            "2026-07-20",
        ],
    )
    assert update_result.exit_code == 0, update_result.output
    assert "Settled outcomes: 4" in update_result.output

    summary_result = CliRunner().invoke(
        app,
        [
            "summarize-recommendation-outcomes",
            "--db-path",
            str(db_path),
            "--output-path",
            str(summary_path),
        ],
    )
    assert summary_result.exit_code == 0, summary_result.output
    assert "Outcome summary JSON" in summary_result.output
    assert summary_path.exists()
