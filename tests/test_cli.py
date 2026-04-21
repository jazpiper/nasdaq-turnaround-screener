from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

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
                data_failures=["NVDA: No price rows returned"],
                notes=["stubbed test run"],
            ),
            candidates=[
                CandidateResult(
                    ticker="AAPL",
                    score=78.0,
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
        )
        if not context.dry_run:
            context.output_dir.mkdir(parents=True, exist_ok=True)
            artifacts.markdown_path.write_text("# Report\n\nAAPL\n", encoding="utf-8")
            artifacts.json_report_path.write_text(
                json.dumps({"date": context.run_date.isoformat(), "candidate_count": 1, "candidates": [{"ticker": "AAPL"}]}),
                encoding="utf-8",
            )
            artifacts.metadata_path.write_text(
                json.dumps({"data_failures": result.metadata.data_failures}),
                encoding="utf-8",
            )
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
    assert "AAPL" in markdown_path.read_text(encoding="utf-8")

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["date"] == "2026-04-21"
    assert payload["candidate_count"] == 1
    assert payload["candidates"][0]["ticker"] == "AAPL"
