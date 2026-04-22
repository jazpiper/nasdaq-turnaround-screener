from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from screener.alerts import AlertSidecarError
from screener.backtest import BacktestArtifacts
from screener.cli.main import app
from screener.models import CandidateResult, RunArtifacts, RunMetadata, ScreenRunResult, ScoreBreakdown

runner = CliRunner()


class StubPipeline:
    def __init__(self, settings):
        self.settings = settings

    def run(self, context):
        result = ScreenRunResult(
            metadata=RunMetadata(
                run_date=context.run_date,
                generated_at=datetime(2026, 4, 21, 7, 30, tzinfo=timezone.utc),
                universe=context.universe_name,
                run_mode=context.run_mode,
                dry_run=context.dry_run,
                artifact_directory=context.output_dir,
                planned_ticker_count=100,
                successful_ticker_count=99,
                failed_ticker_count=1,
                bars_nonempty_count=99,
                latest_bar_date_mismatch_count=0,
                insufficient_history_count=1,
                planned_tickers=["AAPL", "NVDA"],
                data_failures=["NVDA: No price rows returned"],
                notes=["stubbed test run"],
            ),
            candidates=[
                CandidateResult(
                    ticker="AAPL",
                    name="Apple Inc.",
                    score=78,
                    subscores=ScoreBreakdown(oversold=20, bottom_context=17, reversal=23, volume=10, market_context=8),
                    close=172.4,
                    lower_bb=171.9,
                    rsi14=33.2,
                    distance_to_20d_low=1.8,
                    reasons=["BB 하단 근처 또는 재진입 구간"],
                    risks=["중기 추세는 아직 하락 압력일 수 있음"],
                    generated_at=datetime(2026, 4, 21, 7, 30, tzinfo=timezone.utc),
                )
            ],
        )
        artifacts = RunArtifacts(
            markdown_path=context.output_dir / "daily-report.md",
            json_report_path=context.output_dir / "daily-report.json",
            metadata_path=context.output_dir / "run-metadata.json",
            alert_events_path=context.output_dir / "alert-events.json",
            stable_alert_events_path=context.output_dir.parent / "latest" / "alert-events.json",
        )
        if not context.dry_run:
            context.output_dir.mkdir(parents=True, exist_ok=True)
            artifacts.stable_alert_events_path.parent.mkdir(parents=True, exist_ok=True)
            artifacts.markdown_path.write_text("# Report\n\nAAPL\n", encoding="utf-8")
            artifacts.json_report_path.write_text(
                json.dumps({
                    "date": context.run_date.isoformat(),
                    "planned_ticker_count": result.metadata.planned_ticker_count,
                    "successful_ticker_count": result.metadata.successful_ticker_count,
                    "failed_ticker_count": result.metadata.failed_ticker_count,
                    "bars_nonempty_count": result.metadata.bars_nonempty_count,
                    "latest_bar_date_mismatch_count": result.metadata.latest_bar_date_mismatch_count,
                    "insufficient_history_count": result.metadata.insufficient_history_count,
                    "planned_tickers": result.metadata.planned_tickers,
                    "candidate_count": 1,
                    "candidates": [{"ticker": "AAPL", "name": "Apple Inc."}],
                }),
                encoding="utf-8",
            )
            artifacts.metadata_path.write_text(
                json.dumps({
                    "planned_ticker_count": result.metadata.planned_ticker_count,
                    "successful_ticker_count": result.metadata.successful_ticker_count,
                    "failed_ticker_count": result.metadata.failed_ticker_count,
                    "bars_nonempty_count": result.metadata.bars_nonempty_count,
                    "latest_bar_date_mismatch_count": result.metadata.latest_bar_date_mismatch_count,
                    "insufficient_history_count": result.metadata.insufficient_history_count,
                    "planned_tickers": result.metadata.planned_tickers,
                    "data_failures": result.metadata.data_failures,
                }),
                encoding="utf-8",
            )
            artifacts.alert_events_path.write_text(json.dumps({"phase": "final"}), encoding="utf-8")
            artifacts.stable_alert_events_path.write_text(json.dumps({"phase": "final"}), encoding="utf-8")
        else:
            artifacts = RunArtifacts()
        return result, artifacts


def test_run_dry_run_skips_artifacts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("screener.cli.main.ScreenPipeline", StubPipeline)

    result = runner.invoke(
        app,
        ["run", "--date", "2026-04-21", "--dry-run", "--output-dir", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert "Candidate count: 1" in result.stdout
    assert "Artifacts skipped" in result.stdout
    assert not any(tmp_path.iterdir())


class StubOracleSqlStorage:
    def persist_daily_run(self, result):
        return "run_test"

    def persist_intraday_collection(self, result):
        return "intraday_test"

    def initialize_schema(self):
        return None


class StubBacktestRunner:
    def __init__(self, settings):
        self.settings = settings

    def run(self, *, start_date, end_date, output_dir, forward_horizons, dry_run):
        summary = {
            "trading_day_count": 3,
            "candidate_observation_count": 2,
        }
        artifacts = BacktestArtifacts(
            summary_path=output_dir / "backtest-summary.json",
            observations_path=output_dir / "backtest-observations.csv",
        )
        if not dry_run:
            output_dir.mkdir(parents=True, exist_ok=True)
            artifacts.summary_path.write_text(json.dumps(summary), encoding="utf-8")
            artifacts.observations_path.write_text("run_date,ticker,score\n2026-04-20,AAPL,78\n", encoding="utf-8")
        else:
            artifacts = BacktestArtifacts()
        return summary, artifacts


class StubCollector:
    def __init__(self, settings):
        self.settings = settings

    def run_window(self, *, run_date, output_root, window_index, total_windows, max_credits_per_minute, dry_run):
        run_directory = output_root / run_date.isoformat() / "window-01-of-06" / "run-20260421T073000Z"
        metadata_path = run_directory / "collection-metadata.json"
        quotes_path = run_directory / "collected-quotes.json"
        if not dry_run:
            run_directory.mkdir(parents=True, exist_ok=True)
            metadata_path.write_text(json.dumps({"window_index": window_index, "remaining_count": 83}), encoding="utf-8")
            quotes_path.write_text(json.dumps({"quotes": [{"ticker": "AAPL"}]}), encoding="utf-8")
        else:
            run_directory = metadata_path = quotes_path = None

        class Plan:
            window_index = 0
            total_windows = 6
            window_tickers = ["AAPL"] * 17
            remaining_tickers = ["MSFT"] * 83

        class Artifacts:
            def __init__(self):
                self.run_directory = run_directory
                self.metadata_path = metadata_path
                self.quotes_path = quotes_path

        class Result:
            def __init__(self):
                self.plan = Plan()
                self.collected = [{"ticker": "AAPL"}]
                self.failures = {}
                self.artifacts = Artifacts()

        return Result()


def test_run_writes_artifacts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("screener.cli.main.ScreenPipeline", StubPipeline)

    result = runner.invoke(
        app,
        ["run", "--date", "2026-04-21", "--output-dir", str(tmp_path)],
    )

    assert result.exit_code == 0
    markdown_path = tmp_path / "daily-report.md"
    json_path = tmp_path / "daily-report.json"
    metadata_path = tmp_path / "run-metadata.json"

    assert markdown_path.exists()
    assert json_path.exists()
    assert metadata_path.exists()
    assert "Markdown report" in result.stdout
    assert "Alert events:" in result.stdout
    assert "Stable alert entrypoint:" in result.stdout
    assert "AAPL" in markdown_path.read_text(encoding="utf-8")

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["date"] == "2026-04-21"
    assert payload["planned_ticker_count"] == 100
    assert payload["successful_ticker_count"] == 99
    assert payload["failed_ticker_count"] == 1
    assert payload["bars_nonempty_count"] == 99
    assert payload["latest_bar_date_mismatch_count"] == 0
    assert payload["insufficient_history_count"] == 1
    assert payload["planned_tickers"] == ["AAPL", "NVDA"]
    assert payload["candidate_count"] == 1
    assert payload["candidates"][0]["ticker"] == "AAPL"
    assert payload["candidates"][0]["name"] == "Apple Inc."


def test_run_exits_nonzero_when_alert_sidecar_generation_fails(tmp_path: Path, monkeypatch) -> None:
    class FailingAlertPipeline(StubPipeline):
        def run(self, context):
            result, artifacts = super().run(context)
            if not context.dry_run:
                raise AlertSidecarError("alert sidecar failed")
            return result, artifacts

    monkeypatch.setattr("screener.cli.main.ScreenPipeline", FailingAlertPipeline)

    result = runner.invoke(
        app,
        ["run", "--date", "2026-04-21", "--output-dir", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "Alert sidecar generation failed: alert sidecar failed" in (result.stdout + result.stderr)
    assert (tmp_path / "daily-report.json").exists()


def test_run_can_persist_to_oracle_sql(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("screener.cli.main.ScreenPipeline", StubPipeline)
    monkeypatch.setattr("screener.cli.main.OracleSqlStorage.from_settings", lambda settings: StubOracleSqlStorage())

    result = runner.invoke(
        app,
        ["run", "--date", "2026-04-21", "--output-dir", str(tmp_path), "--persist-oracle-sql"],
    )

    assert result.exit_code == 0
    assert "Oracle SQL run id: run_test" in result.stdout


def test_init_oracle_schema_command(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("screener.cli.main.OracleSqlStorage.from_settings", lambda settings: StubOracleSqlStorage())

    result = runner.invoke(app, ["init-oracle-schema"])

    assert result.exit_code == 0
    assert "Oracle SQL schema initialized." in result.stdout



def test_collect_window_writes_artifacts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("screener.cli.main.TwelveDataWindowCollector", StubCollector)

    result = runner.invoke(
        app,
        ["collect-window", "--date", "2026-04-21", "--window-index", "0", "--output-dir", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert "Window: 1/6" in result.stdout
    assert "Remaining after window: 83" in result.stdout
    assert (tmp_path / "2026-04-21" / "window-01-of-06" / "run-20260421T073000Z" / "collection-metadata.json").exists()


def test_collect_window_can_persist_to_oracle_sql(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("screener.cli.main.TwelveDataWindowCollector", StubCollector)
    monkeypatch.setattr("screener.cli.main.OracleSqlStorage.from_settings", lambda settings: StubOracleSqlStorage())

    result = runner.invoke(
        app,
        [
            "collect-window",
            "--date",
            "2026-04-21",
            "--window-index",
            "0",
            "--output-dir",
            str(tmp_path),
            "--persist-oracle-sql",
        ],
    )

    assert result.exit_code == 0
    assert "Oracle SQL collection id: intraday_test" in result.stdout


def test_backtest_writes_artifacts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("screener.cli.main.HistoricalBacktestRunner", StubBacktestRunner)

    result = runner.invoke(
        app,
        [
            "backtest",
            "--start-date",
            "2026-04-01",
            "--end-date",
            "2026-04-21",
            "--output-dir",
            str(tmp_path),
            "--horizons",
            "5,10",
        ],
    )

    assert result.exit_code == 0
    assert "Trading days: 3" in result.stdout
    assert "Candidate observations: 2" in result.stdout
    assert (tmp_path / "backtest-summary.json").exists()
    assert (tmp_path / "backtest-observations.csv").exists()



def test_collect_window_dry_run_skips_artifacts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("screener.cli.main.TwelveDataWindowCollector", StubCollector)

    result = runner.invoke(
        app,
        ["collect-window", "--date", "2026-04-21", "--window-index", "0", "--dry-run", "--output-dir", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert "Artifacts skipped" in result.stdout
    assert not any(tmp_path.iterdir())
