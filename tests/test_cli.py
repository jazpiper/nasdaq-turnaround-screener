from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from screener.alerts import AlertSidecarError
from screener.backtest import BacktestArtifacts
from screener.cli.main import app
from screener.recommendations import build_daily_top3_recommendations, update_recommendation_outcomes
from screener.config import Settings
from screener.models import CandidateResult, RunArtifacts, RunMetadata, ScreenRunResult, ScoreBreakdown

runner = CliRunner()


@pytest.fixture(autouse=True)
def _disable_env_oracle_default(monkeypatch):
    monkeypatch.delenv("SCREENER_ORACLE_SQL_ENABLED", raising=False)


class StubPipeline:
    last_settings = None
    last_context = None
    run_called = False

    def __init__(self, settings):
        self.settings = settings
        StubPipeline.last_settings = settings

    def run(self, context):
        StubPipeline.run_called = True
        StubPipeline.last_context = context
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
    assert StubPipeline.last_settings.universe_tickers is None
    assert StubPipeline.last_context.universe_name == "NASDAQ-100"


def test_run_passes_custom_watchlist_universe_to_pipeline(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("screener.cli.main.ScreenPipeline", StubPipeline)

    result = runner.invoke(
        app,
        [
            "run",
            "--date",
            "2026-05-01",
            "--dry-run",
            "--output-dir",
            str(tmp_path),
            "--tickers",
            "tsla, INFQ,pltr,tsla,rklb,googl,nvda",
        ],
    )

    assert result.exit_code == 0
    assert StubPipeline.last_settings.universe_name == "user-watchlist"
    assert StubPipeline.last_settings.universe_tickers == (
        "TSLA",
        "INFQ",
        "PLTR",
        "RKLB",
        "GOOGL",
        "NVDA",
    )
    assert StubPipeline.last_context.universe_name == "user-watchlist"
    assert "Run universe: user-watchlist" in result.stdout


def test_run_allows_explicit_custom_universe_name(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("screener.cli.main.ScreenPipeline", StubPipeline)

    result = runner.invoke(
        app,
        [
            "run",
            "--date",
            "2026-05-01",
            "--dry-run",
            "--output-dir",
            str(tmp_path),
            "--universe-name",
            "personal-watchlist",
            "--universe-tickers",
            "TSLA,NVDA",
        ],
    )

    assert result.exit_code == 0
    assert StubPipeline.last_settings.universe_name == "personal-watchlist"
    assert StubPipeline.last_settings.universe_tickers == ("TSLA", "NVDA")
    assert StubPipeline.last_context.universe_name == "personal-watchlist"


def test_run_rejects_universe_name_without_custom_tickers(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("screener.cli.main.ScreenPipeline", StubPipeline)

    result = runner.invoke(
        app,
        [
            "run",
            "--date",
            "2026-05-01",
            "--dry-run",
            "--output-dir",
            str(tmp_path),
            "--universe-name",
            "personal-watchlist",
        ],
    )

    assert result.exit_code == 2
    assert "Invalid value for --universe-name" in result.output
    assert "--tickers/--universe-tickers" in result.output


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


class RecordingTuningBacktestRunner:
    called = False

    def __init__(self, settings):
        self.settings = settings

    def generate_observations(self, *, start_date, end_date, forward_horizons):
        RecordingTuningBacktestRunner.called = True
        return [], [], 0


class StubCollector:
    def __init__(self, settings):
        self.settings = settings

    def run_window(self, *, run_date, output_root, window_index, total_windows, max_credits_per_minute, dry_run):
        run_directory = output_root / run_date.isoformat() / "window-01-of-06" / "run-20260421T073000Z"
        metadata_path = run_directory / "collection-metadata.json"
        quotes_path = run_directory / "collected-quotes.json"
        alert_events_path = run_directory / "alert-events.json"
        stable_alert_events_path = output_root / run_date.isoformat() / "latest-alert-events.json"
        if not dry_run:
            run_directory.mkdir(parents=True, exist_ok=True)
            metadata_path.write_text(json.dumps({"window_index": window_index, "remaining_count": 83}), encoding="utf-8")
            quotes_path.write_text(json.dumps({"quotes": [{"ticker": "AAPL"}]}), encoding="utf-8")
            stable_alert_events_path.parent.mkdir(parents=True, exist_ok=True)
            alert_events_path.write_text(json.dumps({"phase": "provisional"}), encoding="utf-8")
            stable_alert_events_path.write_text(json.dumps({"phase": "provisional"}), encoding="utf-8")
        else:
            run_directory = metadata_path = quotes_path = alert_events_path = stable_alert_events_path = None

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
                self.alert_events_path = alert_events_path
                self.stable_alert_events_path = stable_alert_events_path

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


def test_run_persist_oracle_sql_preflights_before_pipeline_when_credentials_missing(tmp_path: Path, monkeypatch) -> None:
    StubPipeline.run_called = False
    monkeypatch.setattr("screener.cli.main.ScreenPipeline", StubPipeline)
    monkeypatch.setattr(
        "screener.cli.main.get_settings",
        lambda output_dir=None, **kwargs: Settings(output_dir=Path(output_dir or "output")),
    )

    result = runner.invoke(
        app,
        ["run", "--date", "2026-04-21", "--output-dir", str(tmp_path), "--persist-oracle-sql"],
    )

    output = result.stdout + result.stderr
    assert result.exit_code == 1
    assert "Oracle SQL persistence is enabled but credentials are missing" in output
    assert "super_secret" not in output
    assert StubPipeline.run_called is False
    assert not any(tmp_path.iterdir())


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
    assert "Provisional alert events:" in result.stdout
    assert "Stable provisional alert entrypoint:" in result.stdout
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


def test_collect_window_persist_oracle_sql_preflights_before_collection_when_credentials_missing(tmp_path: Path, monkeypatch) -> None:
    class RecordingCollector(StubCollector):
        run_called = False

        def run_window(self, **kwargs):
            RecordingCollector.run_called = True
            return super().run_window(**kwargs)

    monkeypatch.setattr("screener.cli.main.TwelveDataWindowCollector", RecordingCollector)
    monkeypatch.setattr(
        "screener.cli.main.get_settings",
        lambda output_dir=None, market_data_provider=None, **kwargs: Settings(output_dir=Path(output_dir or "output")),
    )

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

    output = result.stdout + result.stderr
    assert result.exit_code == 1
    assert "Oracle SQL persistence is enabled but credentials are missing" in output
    assert RecordingCollector.run_called is False
    assert not any(tmp_path.iterdir())


def test_collect_window_exits_nonzero_when_alert_sidecar_generation_fails(tmp_path: Path, monkeypatch) -> None:
    class FailingAlertCollector(StubCollector):
        def run_window(self, **kwargs):
            raise AlertSidecarError("alert sidecar failed")

    monkeypatch.setattr("screener.cli.main.TwelveDataWindowCollector", FailingAlertCollector)

    result = runner.invoke(
        app,
        ["collect-window", "--date", "2026-04-21", "--window-index", "0", "--output-dir", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "Alert sidecar generation failed: alert sidecar failed" in (result.stdout + result.stderr)


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


def test_tune_rejects_forward_horizon_missing_from_collected_horizons(tmp_path: Path, monkeypatch) -> None:
    RecordingTuningBacktestRunner.called = False
    monkeypatch.setattr("screener.cli.main.HistoricalBacktestRunner", RecordingTuningBacktestRunner)

    result = runner.invoke(
        app,
        [
            "tune",
            "--start-date",
            "2026-04-01",
            "--end-date",
            "2026-04-21",
            "--output-dir",
            str(tmp_path),
            "--forward-horizon",
            "20",
            "--horizons",
            "5,10",
        ],
    )

    output = result.stdout + result.stderr
    assert result.exit_code != 0
    assert "Forward horizon T+20 is not included in --horizons (5, 10)" in output
    assert RecordingTuningBacktestRunner.called is False


def test_openclaw_docs_do_not_pass_unsupported_flags_to_commands() -> None:
    docs = [
        Path("docs/openclaw-cron-runbook.md"),
        Path("docs/operations.md"),
    ]

    for doc_path in docs:
        content = doc_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            if "screener.cli.main tune" in line:
                assert "--skip-install" not in line, f"{doc_path} passes unsupported --skip-install to tune"
                assert "--dry-run" not in line, f"{doc_path} passes unsupported --dry-run to tune"
        assert "apply_tuning_proposal.py --dry-run" not in content, f"{doc_path} advertises unsupported apply --dry-run"


def test_build_assistant_briefing_writes_compact_artifacts(tmp_path: Path) -> None:
    report_path = tmp_path / "daily-report.json"
    report_path.write_text(
        json.dumps(
            {
                "date": "2026-05-01",
                "planned_ticker_count": 100,
                "successful_ticker_count": 100,
                "failed_ticker_count": 0,
                "bars_nonempty_count": 100,
                "latest_bar_date_mismatch_count": 0,
                "insufficient_history_count": 0,
                "planned_tickers": ["TSLA", "PLTR", "GOOGL", "NVDA", "GEHC"],
                "candidate_count": 1,
                "candidates": [
                    {
                        "ticker": "GEHC",
                        "name": "GE HealthCare Technologies Inc.",
                        "score": 68,
                        "risk_adjusted_score": 53,
                        "tier": "avoid/high-risk",
                        "reasons": ["BB 하단 근처 또는 재진입 구간"],
                        "risks": ["주봉 추세가 아직 약함"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "assistant"

    result = runner.invoke(
        app,
        [
            "build-assistant-briefing",
            "--report-path",
            str(report_path),
            "--output-dir",
            str(output_dir),
            "--user-tickers",
            "TSLA,INFQ,PLTR,RKLB,GOOGL,NVDA",
            "--top-candidates",
            "1",
        ],
    )

    assert result.exit_code == 0
    assert "Assistant briefing JSON:" in result.stdout
    json_path = output_dir / "latest-user-briefing-screener.json"
    markdown_path = output_dir / "latest-user-briefing-screener.md"
    assert json_path.exists()
    assert markdown_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    user_by_ticker = {item["ticker"]: item for item in payload["user_tickers"]}
    assert user_by_ticker["TSLA"]["in_screener_universe"] is True
    assert user_by_ticker["RKLB"]["in_screener_universe"] is False
    assert payload["top_candidates"][0]["ticker"] == "GEHC"


def test_build_assistant_briefing_writes_user_watchlist_artifact_names(tmp_path: Path) -> None:
    report_path = tmp_path / "daily-report.json"
    report_path.write_text(
        json.dumps(
            {
                "date": "2026-05-01",
                "universe": "user-watchlist",
                "planned_ticker_count": 6,
                "successful_ticker_count": 5,
                "failed_ticker_count": 1,
                "bars_nonempty_count": 5,
                "latest_bar_date_mismatch_count": 0,
                "insufficient_history_count": 0,
                "planned_tickers": ["TSLA", "INFQ", "PLTR", "RKLB", "GOOGL", "NVDA"],
                "data_failures": ["INFQ: No price rows returned"],
                "candidate_count": 0,
                "candidates": [],
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "assistant"

    result = runner.invoke(
        app,
        [
            "build-assistant-briefing",
            "--report-path",
            str(report_path),
            "--output-dir",
            str(output_dir),
            "--artifact-basename",
            "latest-user-watchlist-screener",
        ],
    )

    assert result.exit_code == 0
    json_path = output_dir / "latest-user-watchlist-screener.json"
    markdown_path = output_dir / "latest-user-watchlist-screener.md"
    assert json_path.exists()
    assert markdown_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    user_by_ticker = {item["ticker"]: item for item in payload["user_tickers"]}
    assert payload["universe"] == "user-watchlist"
    assert payload["missing_user_tickers"] == []
    assert user_by_ticker["INFQ"]["in_screener_universe"] is True
    assert user_by_ticker["INFQ"]["data_failure"] is True
    assert user_by_ticker["INFQ"]["data_failure_reason"] == "No price rows returned"


def test_build_assistant_briefing_dry_run_skips_artifacts(tmp_path: Path) -> None:
    report_path = tmp_path / "daily-report.json"
    report_path.write_text(
        json.dumps({"date": "2026-05-01", "planned_tickers": [], "candidate_count": 0, "candidates": []}),
        encoding="utf-8",
    )
    output_dir = tmp_path / "assistant"

    result = runner.invoke(
        app,
        [
            "build-assistant-briefing",
            "--report-path",
            str(report_path),
            "--output-dir",
            str(output_dir),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert "Artifacts skipped" in result.stdout
    assert not output_dir.exists()


def test_build_assistant_briefing_missing_report_exits_cleanly(tmp_path: Path) -> None:
    missing_report = tmp_path / "missing-daily-report.json"

    result = runner.invoke(
        app,
        [
            "build-assistant-briefing",
            "--report-path",
            str(missing_report),
            "--output-dir",
            str(tmp_path / "assistant"),
        ],
    )

    assert result.exit_code == 1
    assert "Daily report not found:" in (result.stdout + result.stderr)


def test_collect_window_dry_run_skips_artifacts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("screener.cli.main.TwelveDataWindowCollector", StubCollector)

    result = runner.invoke(
        app,
        ["collect-window", "--date", "2026-04-21", "--window-index", "0", "--dry-run", "--output-dir", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert "Artifacts skipped" in result.stdout
    assert not any(tmp_path.iterdir())


def test_build_assistant_briefing_uses_tracked_universe_contract(tmp_path: Path) -> None:
    report_path = tmp_path / "daily-report.json"
    report_path.write_text(
        json.dumps(
            {
                "date": "2026-05-01",
                "planned_ticker_count": 3,
                "successful_ticker_count": 3,
                "failed_ticker_count": 0,
                "bars_nonempty_count": 3,
                "latest_bar_date_mismatch_count": 0,
                "insufficient_history_count": 0,
                "planned_tickers": ["TSLA", "PLTR", "GEHC"],
                "candidate_count": 2,
                "candidates": [
                    {
                        "ticker": "GEHC",
                        "name": "GE HealthCare Technologies Inc.",
                        "score": 68,
                        "risk_adjusted_score": 53,
                        "tier": "avoid/high-risk",
                        "reasons": ["BB 하단 근처 또는 재진입 구간"],
                        "risks": ["주봉 추세가 아직 약함"],
                    },
                    {
                        "ticker": "PLTR",
                        "name": "Palantir Technologies Inc.",
                        "score": 72,
                        "risk_adjusted_score": 69,
                        "tier": "watchlist",
                        "reasons": ["최근 2일 이상 종가 개선"],
                        "risks": ["시장/섹터 맥락 확인이 필요함"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    universe_path = tmp_path / "us-stocks-universe.json"
    universe_path.write_text(
        json.dumps(
            {
                "coverage_policy": {"priority_order": ["holdings", "focus_watchlist"]},
                "holdings": [{"ticker": "TSLA"}, {"ticker": "PLTR"}],
                "focus_watchlist": ["GEHC"],
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "assistant"
    recommendation_report_path = tmp_path / "daily-top3-source.json"
    recommendation_report_path.write_text(
        json.dumps(
            {
                "date": "2026-04-30",
                "generated_at": "2026-04-30T20:15:00+00:00",
                "universe": "NASDAQ-100",
                "planned_ticker_count": 3,
                "successful_ticker_count": 3,
                "candidate_count": 2,
                "reliability_label": "ok",
                "data_failures": [],
                "candidates": [
                    {
                        "ticker": "AAPL",
                        "name": "Apple Inc.",
                        "score": 78,
                        "risk_adjusted_score": 70,
                        "subscores": {"oversold": 20, "bottom_context": 18, "reversal": 21, "volume": 12, "market_context": 10},
                        "tier": "buy-review",
                        "tier_reasons": ["buy-review threshold met"],
                        "close": 100.0,
                        "reasons": ["BB 하단 근처"],
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
                            "average_volume_20d": 2000000,
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
                            "risk_adjustment_penalty": 8,
                            "risk_adjusted_score": 70,
                            "snapshot_schema_version": 2,
                            "source_provider": "fixture",
                            "source_timestamp": "2026-04-30T20:00:00+00:00",
                            "freshness_label": "fresh",
                            "reliability_label": "ok"
                        },
                        "snapshot_schema_version": 2,
                        "generated_at": "2026-04-30T20:10:00+00:00"
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    recommendation_db_path = tmp_path / "recommendations.sqlite3"
    recommendation_output_dir = tmp_path / "recommendations"
    build_daily_top3_recommendations(
        daily_report_path=recommendation_report_path,
        db_path=recommendation_db_path,
        output_dir=recommendation_output_dir,
    )
    update_recommendation_outcomes(
        db_path=recommendation_db_path,
        prices_by_ticker={
            "AAPL": {"2026-05-01": {"open": 100.0, "high": 102.0, "low": 99.0, "close": 99.0}},
            "SPY": {
                "2026-04-30": {"open": 500.0, "high": 500.0, "low": 500.0, "close": 500.0},
                "2026-05-01": {"open": 502.0, "high": 502.0, "low": 502.0, "close": 502.0},
            },
            "QQQ": {
                "2026-04-30": {"open": 400.0, "high": 400.0, "low": 400.0, "close": 400.0},
                "2026-05-01": {"open": 401.0, "high": 401.0, "low": 401.0, "close": 401.0},
            },
        },
        as_of_date="2026-05-01",
    )

    result = runner.invoke(
        app,
        [
            "build-assistant-briefing",
            "--report-path",
            str(report_path),
            "--output-dir",
            str(output_dir),
            "--user-tickers",
            "TSLA,PLTR",
            "--top-candidates",
            "2",
            "--tracked-universe-path",
            str(universe_path),
            "--recommendation-db-path",
            str(recommendation_db_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads((output_dir / "latest-user-briefing-screener.json").read_text(encoding="utf-8"))
    user_by_ticker = {item["ticker"]: item for item in payload["user_tickers"]}
    assert user_by_ticker["PLTR"]["briefing_section"] == "holdings"
    assert user_by_ticker["PLTR"]["briefing_label"] == "모니터"
    assert [item["ticker"] for item in payload["top_candidates"]] == ["GEHC"]
    assert payload["previous_top3_feedback"]["available"] is True
    assert payload["previous_top3_feedback"]["source_run_date"] == "2026-04-30"
    markdown = (output_dir / "latest-user-briefing-screener.md").read_text(encoding="utf-8")
    assert "## Previous Top3 outcome feedback" in markdown
    assert "warning 손실, SPY 미만" in markdown
