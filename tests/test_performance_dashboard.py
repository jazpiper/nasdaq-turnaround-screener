from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from screener.cli.main import app
from screener.reporting.performance_dashboard import (
    build_performance_dashboard_markdown,
    build_performance_dashboard_payload,
    load_and_build_performance_dashboard,
    write_performance_dashboard,
)

runner = CliRunner()


def _sample_backtest_summary() -> dict:
    return {
        "start_date": "2026-03-01",
        "end_date": "2026-04-21",
        "trading_day_count": 36,
        "candidate_observation_count": 2293,
        "forward_horizons": [5, 10, 20],
        "forward_return_summary": {
            "5d": {
                "count": 2293,
                "excess_count": 2293,
                "average_return_pct": 0.4877,
                "median_return_pct": -0.0695,
                "win_rate": 0.4959,
                "average_excess_return_pct": -0.6813,
            },
            "10d": {
                "count": 2219,
                "excess_count": 2219,
                "average_return_pct": 1.5038,
                "median_return_pct": 0.1382,
                "win_rate": 0.5119,
                "average_excess_return_pct": -1.4647,
            },
            "20d": {
                "count": 1695,
                "excess_count": 1695,
                "average_return_pct": 4.5647,
                "median_return_pct": 1.8032,
                "win_rate": 0.5864,
                "average_excess_return_pct": -2.7155,
            },
        },
        "tier_forward_return_summary": {
            "avoid/high-risk": {
                "5d": {
                    "count": 456,
                    "excess_count": 456,
                    "average_return_pct": 1.8473,
                    "median_return_pct": 0.8611,
                    "win_rate": 0.5768,
                    "average_excess_return_pct": 0.0795,
                }
            },
            "buy-review": {
                "10d": {
                    "count": 53,
                    "excess_count": 53,
                    "average_return_pct": 0.0072,
                    "median_return_pct": 0.2527,
                    "win_rate": 0.5094,
                    "average_excess_return_pct": -3.3598,
                }
            },
        },
    }


def _sample_tuning_proposal() -> dict:
    return {
        "status": "proposal",
        "source": "walk_forward",
        "horizon": 10,
        "generated_at": "2026-04-21T20:30:00+00:00",
        "proposed": {
            "min_score": 45,
            "min_reversal": 20,
            "min_volume_ratio": 0.9,
            "max_risk_count": 2,
        },
        "current": {
            "min_score": 40,
            "min_reversal": 18,
            "min_volume_ratio": 0.8,
            "max_risk_count": 3,
        },
        "objective": {
            "excess_return_pct": 1.25,
            "sample_count": 53,
        },
        "stability": {
            "win_count": 3,
            "valid_eval_count": 4,
            "walk_forward_window_count": 4,
            "avg_eval_excess_return_pct": 0.42,
        },
    }


def _sample_tuning_walkforward() -> dict:
    return {
        "generated_at": "2026-04-21T20:30:00+00:00",
        "horizon": 10,
        "window_count": 4,
        "proposal_status": "proposal",
        "proposal": {
            "min_score": 45,
            "min_reversal": 20,
            "min_volume_ratio": 0.9,
            "max_risk_count": 2,
        },
        "stability": [
            {
                "thresholds": {
                    "min_score": 45,
                    "min_reversal": 20,
                    "min_volume_ratio": 0.9,
                    "max_risk_count": 2,
                },
                "win_count": 3,
                "valid_eval_count": 4,
                "window_indices": [0, 1, 2, 3],
                "avg_eval_excess_return": 0.42,
            }
        ],
        "windows": [
            {
                "window_index": 0,
                "train_start": "2026-01-01",
                "train_end": "2026-02-01",
                "eval_start": "2026-02-02",
                "eval_end": "2026-02-15",
                "train_obs_count": 100,
                "eval_obs_count": 25,
                "best_thresholds": {
                    "min_score": 45,
                    "min_reversal": 20,
                    "min_volume_ratio": 0.9,
                    "max_risk_count": 2,
                },
                "best_train_excess_return": 1.8,
                "best_train_sample_count": 50,
                "eval_excess_return": 0.5,
                "eval_sample_count": 25,
            }
        ],
    }


def test_performance_dashboard_payload_and_markdown(tmp_path: Path) -> None:
    payload = build_performance_dashboard_payload(
        _sample_backtest_summary(),
        generated_at=datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc),
        backtest_summary_path=Path("output/backtests/backtest-summary.json"),
        tuning_proposal=_sample_tuning_proposal(),
        tuning_walkforward=_sample_tuning_walkforward(),
        tuning_proposal_path=Path("output/tuning/2026-04-21/tuning-proposal.json"),
        tuning_walkforward_path=Path("output/tuning-walkforward-6mo-30d/2026-04-21/tuning-walkforward.json"),
        output_dir=tmp_path,
    )
    markdown = build_performance_dashboard_markdown(payload)

    assert payload["schema_version"] == 1
    assert payload["backtest"]["forward_return_summary"][1]["horizon"] == "10d"
    assert payload["tuning"]["status"] == "available"
    assert any("Backtest covers 36 trading days" in item for item in payload["backtest"]["highlights"])
    assert any("Tuning proposal available" in item for item in payload["tuning"]["highlights"])
    assert "## Forward return summary" in markdown
    assert "| 10d | 2219 | +1.50% | -1.46% | 51.2% |" in markdown
    assert "## Tier summary" in markdown
    assert "| buy-review | 10d | 53 | +0.01% | -3.36% | 50.9% |" in markdown
    assert "## Tuning status" in markdown
    assert "Walk-forward proposal" in markdown

    json_path, markdown_path = write_performance_dashboard(payload, markdown, tmp_path)
    assert json_path.exists()
    assert markdown_path.exists()
    written = json.loads(json_path.read_text(encoding="utf-8"))
    assert written["source_paths"]["backtest_summary_path"] == "output/backtests/backtest-summary.json"


def test_performance_dashboard_command_writes_artifacts(tmp_path: Path) -> None:
    backtest_summary_path = tmp_path / "backtest-summary.json"
    tuning_proposal_path = tmp_path / "tuning-proposal.json"
    tuning_walkforward_path = tmp_path / "tuning-walkforward.json"
    output_dir = tmp_path / "dashboard"

    backtest_summary_path.write_text(json.dumps(_sample_backtest_summary()), encoding="utf-8")
    tuning_proposal_path.write_text(json.dumps(_sample_tuning_proposal()), encoding="utf-8")
    tuning_walkforward_path.write_text(json.dumps(_sample_tuning_walkforward()), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "performance-dashboard",
            "--backtest-summary-path",
            str(backtest_summary_path),
            "--tuning-proposal-path",
            str(tuning_proposal_path),
            "--tuning-walkforward-path",
            str(tuning_walkforward_path),
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    assert "Backtest summary:" in result.stdout
    assert "Tuning status: available" in result.stdout
    assert (output_dir / "performance-dashboard.json").exists()
    assert (output_dir / "performance-dashboard.md").exists()
    dashboard = json.loads((output_dir / "performance-dashboard.json").read_text(encoding="utf-8"))
    assert dashboard["tuning"]["status"] == "available"
    assert dashboard["backtest"]["trading_day_count"] == 36


def test_load_and_build_performance_dashboard_with_missing_optional_tuning(tmp_path: Path) -> None:
    backtest_summary_path = tmp_path / "backtest-summary.json"
    backtest_summary_path.write_text(json.dumps(_sample_backtest_summary()), encoding="utf-8")

    payload, markdown = load_and_build_performance_dashboard(
        backtest_summary_path=backtest_summary_path,
        output_dir=tmp_path / "dashboard",
        generated_at=datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc),
    )

    assert payload["tuning"]["status"] == "missing"
    assert "No tuning artifacts found." in markdown
