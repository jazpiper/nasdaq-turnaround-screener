from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from screener.recommendations import build_daily_top3_recommendations
from scripts import run_nasdaq_expanded_discovery as discovery


def _candidate(ticker: str, risk_adjusted: int, score: int) -> dict[str, object]:
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
        "close": 100.0,
        "reasons": ["BB 하단 근처", "5일선 회복 시도"],
        "risks": ["중기 추세 확인 필요"],
        "indicator_snapshot": {
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
        },
        "snapshot_schema_version": 2,
        "generated_at": "2026-05-19T20:10:00+00:00",
    }


def _daily_report(*, run_date: str = "2026-05-19") -> dict[str, object]:
    return {
        "schema_version": 1,
        "date": run_date,
        "generated_at": f"{run_date}T20:15:00+00:00",
        "universe": "NASDAQ-100",
        "planned_ticker_count": 5,
        "successful_ticker_count": 4,
        "candidate_count": 3,
        "reliability_label": "ok",
        "data_failures": ["MISS"],
        "candidates": [
            _candidate("EEE", 90, 90),
            _candidate("AAA", 71, 80),
            _candidate("BBB", 71, 80),
        ],
    }


def _write_quality_gated_daily_fixture(output_root: Path, *, run_date: str, run_status: str = "success", quality_gate: str = "block") -> Path:
    report_dir = output_root / run_date
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "daily-report.json"
    report_path.write_text(json.dumps(_daily_report(run_date=run_date), ensure_ascii=False), encoding="utf-8")
    (report_dir / "run-metadata.json").write_text(
        json.dumps({"run_date": run_date, "run_status": run_status, "quality_gate": quality_gate}, ensure_ascii=False),
        encoding="utf-8",
    )
    return report_path


def test_main_builds_recommendations_from_dated_report_path(monkeypatch) -> None:
    commands: list[list[str]] = []

    monkeypatch.setattr(
        sys,
        "argv",
        ["run_nasdaq_expanded_discovery.py", "--date", "2026-05-19", "--skip-install"],
    )
    monkeypatch.setattr(discovery, "ensure_ticker_file", lambda *args, **kwargs: None)
    monkeypatch.setattr(discovery, "run", lambda command: commands.append(command))

    assert discovery.main() == 0

    assert commands[0][0] == sys.executable
    assert commands[0][1:4] == ["scripts/run_daily.py", "--date", "2026-05-19"]
    recommendation_command = commands[1]
    report_path = recommendation_command[recommendation_command.index("--daily-report-path") + 1]
    assert report_path.endswith("output/daily-nasdaq-expanded-500/2026-05-19/daily-report.json")
    assert "/latest/" not in report_path


def test_main_resolves_auto_date_once_for_daily_and_recommendation(monkeypatch) -> None:
    commands: list[list[str]] = []

    monkeypatch.setattr(
        sys,
        "argv",
        ["run_nasdaq_expanded_discovery.py", "--date", "ny-today", "--skip-install"],
    )
    monkeypatch.setattr(discovery, "ensure_ticker_file", lambda *args, **kwargs: None)
    monkeypatch.setattr(discovery, "resolve_ny_run_date", lambda value: "2026-05-26")
    monkeypatch.setattr(discovery, "run", lambda command: commands.append(command))

    assert discovery.main() == 0

    assert commands[0][commands[0].index("--date") + 1] == "2026-05-26"
    recommendation_command = commands[1]
    report_path = recommendation_command[recommendation_command.index("--daily-report-path") + 1]
    assert report_path.endswith("output/daily-nasdaq-expanded-500/2026-05-26/daily-report.json")


def test_main_continues_recommendations_on_quality_gated_success_nonzero_daily(monkeypatch, tmp_path: Path, capsys) -> None:
    output_root = tmp_path / "daily-nasdaq-expanded-500"
    recommendation_root = tmp_path / "recommendations-expanded"
    db_path = recommendation_root / "recommendations.sqlite3"
    run_date = "2026-05-19"

    monkeypatch.setattr(discovery, "DEFAULT_OUTPUT_ROOT", output_root)
    monkeypatch.setattr(discovery, "DEFAULT_RECOMMENDATION_OUTPUT_DIR", recommendation_root)
    monkeypatch.setattr(discovery, "DEFAULT_RECOMMENDATION_DB", db_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_nasdaq_expanded_discovery.py", "--date", run_date, "--skip-install"],
    )
    monkeypatch.setattr(discovery, "ensure_ticker_file", lambda *args, **kwargs: None)

    calls: list[list[str]] = []

    def fake_run(command: list[str]) -> None:
        calls.append(command)
        if command[1] == "scripts/run_daily.py":
            _write_quality_gated_daily_fixture(output_root, run_date=run_date, run_status="success", quality_gate="block")
            raise subprocess.CalledProcessError(returncode=2, cmd=command)
        report_path = Path(command[command.index("--daily-report-path") + 1])
        build_daily_top3_recommendations(
            daily_report_path=report_path,
            db_path=Path(command[command.index("--db-path") + 1]),
            output_dir=Path(command[command.index("--output-dir") + 1]),
        )

    monkeypatch.setattr(discovery, "run", fake_run)

    assert discovery.main() == 0

    captured = capsys.readouterr()
    assert "continuing recommendation build" in captured.err
    assert len(calls) == 2
    assert db_path.exists()
    assert (recommendation_root / run_date / "daily-top3-recommendations.json").exists()
    assert (recommendation_root / run_date / "daily-top3-recommendations.md").exists()


def test_main_propagates_true_failure_when_quality_gated_success_artifact_missing(monkeypatch, tmp_path: Path) -> None:
    output_root = tmp_path / "daily-nasdaq-expanded-500"
    monkeypatch.setattr(discovery, "DEFAULT_OUTPUT_ROOT", output_root)
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_nasdaq_expanded_discovery.py", "--date", "2026-05-19", "--skip-install"],
    )
    monkeypatch.setattr(discovery, "ensure_ticker_file", lambda *args, **kwargs: None)

    def fake_run(command: list[str]) -> None:
        raise subprocess.CalledProcessError(returncode=3, cmd=command)

    monkeypatch.setattr(discovery, "run", fake_run)

    try:
        discovery.main()
    except subprocess.CalledProcessError as exc:
        assert exc.returncode == 3
    else:
        raise AssertionError("Expected CalledProcessError for missing quality-gated success artifacts")


def test_main_propagates_true_failure_when_run_status_is_not_success(monkeypatch, tmp_path: Path) -> None:
    output_root = tmp_path / "daily-nasdaq-expanded-500"
    monkeypatch.setattr(discovery, "DEFAULT_OUTPUT_ROOT", output_root)
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_nasdaq_expanded_discovery.py", "--date", "2026-05-19", "--skip-install"],
    )
    monkeypatch.setattr(discovery, "ensure_ticker_file", lambda *args, **kwargs: None)

    def fake_run(command: list[str]) -> None:
        _write_quality_gated_daily_fixture(output_root, run_date="2026-05-19", run_status="failed", quality_gate="block")
        raise subprocess.CalledProcessError(returncode=4, cmd=command)

    monkeypatch.setattr(discovery, "run", fake_run)

    try:
        discovery.main()
    except subprocess.CalledProcessError as exc:
        assert exc.returncode == 4
    else:
        raise AssertionError("Expected CalledProcessError when run_status is not success")


def test_main_rejects_stale_quality_gated_success_artifacts(monkeypatch, tmp_path: Path) -> None:
    output_root = tmp_path / "daily-nasdaq-expanded-500"
    _write_quality_gated_daily_fixture(output_root, run_date="2026-05-19", run_status="success", quality_gate="block")
    monkeypatch.setattr(discovery, "DEFAULT_OUTPUT_ROOT", output_root)
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_nasdaq_expanded_discovery.py", "--date", "2026-05-19", "--skip-install"],
    )
    monkeypatch.setattr(discovery, "ensure_ticker_file", lambda *args, **kwargs: None)

    def fake_run(command: list[str]) -> None:
        raise subprocess.CalledProcessError(returncode=5, cmd=command)

    monkeypatch.setattr(discovery, "run", fake_run)

    try:
        discovery.main()
    except subprocess.CalledProcessError as exc:
        assert exc.returncode == 5
    else:
        raise AssertionError("Expected CalledProcessError when only stale quality-gated artifacts exist")
