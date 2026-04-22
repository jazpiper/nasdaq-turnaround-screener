from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from screener.alerts.builder import build_intraday_alert_document
from screener.alerts.state import AlertState
from screener.alerts.state import load_alert_state
from screener.collector import (
    CollectedQuote,
    CollectionArtifacts,
    CollectionPlan,
    CollectionResult,
    TwelveDataWindowCollector,
)
from screener.config import Settings
from screener.models import CandidateResult, RunMetadata, ScoreBreakdown, ScreenRunResult


def test_write_provisional_alerts_writes_run_and_stable_sidecars(tmp_path: Path, monkeypatch) -> None:
    class StubPipeline:
        def __init__(self, settings):
            self.settings = settings

        def run(self, context):
            from screener.models import CandidateResult, RunArtifacts, RunMetadata, ScreenRunResult, ScoreBreakdown

            result = ScreenRunResult(
                metadata=RunMetadata(
                    run_date=context.run_date,
                    generated_at=datetime(2026, 4, 21, 15, 30, tzinfo=timezone.utc),
                    artifact_directory=context.output_dir,
                    run_mode="intraday-provisional",
                    failed_ticker_count=0,
                    bars_nonempty_count=100,
                    latest_bar_date_mismatch_count=0,
                    insufficient_history_count=0,
                ),
                candidates=[
                    CandidateResult(
                        ticker="AAPL",
                        name="Apple Inc.",
                        score=66,
                        subscores=ScoreBreakdown(oversold=20, bottom_context=16, reversal=18, volume=7, market_context=5),
                        reasons=["BB 하단 근처 또는 재진입 구간", "5일선 회복 또는 회복 시도"],
                        risks=["중기 추세는 아직 하락 압력일 수 있음"],
                        indicator_snapshot={"earnings_penalty": 0, "volatility_penalty": 0},
                        generated_at=datetime(2026, 4, 21, 15, 30, tzinfo=timezone.utc),
                    )
                ],
            )
            return result, RunArtifacts()

    monkeypatch.setattr("screener.collector.ScreenPipeline", StubPipeline)

    output_root = tmp_path / "intraday"
    run_directory = output_root / "2026-04-21" / "window-01-of-01" / "run-20260421T153000Z"
    run_directory.mkdir(parents=True, exist_ok=True)
    metadata_path = run_directory / "collection-metadata.json"
    quotes_path = run_directory / "collected-quotes.json"
    metadata_path.write_text(json.dumps({"completed_at": "2026-04-21T15:30:00+00:00"}), encoding="utf-8")
    quotes_path.write_text(
        json.dumps(
            {
                "quotes": [
                    {
                        "ticker": "AAPL",
                        "timestamp": "2026-04-21T15:29:00+00:00",
                        "open": 111.0,
                        "high": 113.0,
                        "low": 109.0,
                        "close": 112.0,
                        "volume": 3210000.0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    collector = TwelveDataWindowCollector(settings=Settings(intraday_output_root=output_root, output_dir=output_root))
    collected = [
        CollectedQuote(
            ticker=f"T{i:02d}",
            timestamp="2026-04-21T15:29:00+00:00",
            open=111.0,
            high=113.0,
            low=109.0,
            close=112.0,
            volume=3210000.0,
        )
        for i in range(60)
    ]
    result = CollectionResult(
        plan=CollectionPlan(
            window_index=0,
            total_windows=1,
            window_tickers=[quote.ticker for quote in collected],
            minute_batches=[[quote.ticker for quote in collected[:5]]],
            remaining_tickers=[],
            max_credits_per_minute=5,
        ),
        collected=collected,
        successes=[quote.ticker for quote in collected],
        failures={},
        skipped_due_to_credit_exhaustion=[],
        artifacts=CollectionArtifacts(
            run_directory=run_directory,
            metadata_path=metadata_path,
            quotes_path=quotes_path,
        ),
    )

    collector._write_provisional_alerts(
        run_date=date(2026, 4, 21),
        output_root=output_root,
        result=result,
        completed_at=datetime(2026, 4, 21, 15, 30, tzinfo=timezone.utc),
    )

    run_payload = json.loads((run_directory / "alert-events.json").read_text(encoding="utf-8"))
    stable_path = output_root / "2026-04-21" / "latest-alert-events.json"
    stable_payload = json.loads(stable_path.read_text(encoding="utf-8"))

    assert run_payload["phase"] == "provisional"
    assert run_payload["run_mode"] == "intraday-provisional"
    assert run_payload["summary"]["quality_gate"] == "pass"
    assert run_payload["source"]["window_index"] == 0
    assert run_payload["source"]["window_number"] == 1
    assert run_payload["source"]["total_windows"] == 1
    assert run_payload["events"][0]["phase"] == "provisional"
    assert run_payload["events"][0]["group_key"].endswith(":provisional")
    assert stable_payload == run_payload

    state = load_alert_state(tmp_path / "alerts" / "2026-04-21" / "alert-state.json")
    assert state.tickers["AAPL"].last_phase == "provisional"


def test_build_intraday_alert_document_elevates_digest_severity_on_warn_collection() -> None:
    result = ScreenRunResult(
        metadata=RunMetadata(
            run_date=date(2026, 4, 21),
            generated_at=datetime(2026, 4, 21, 15, 30, tzinfo=timezone.utc),
            artifact_directory=Path("output/intraday/2026-04-21/window-01-of-01/run-20260421T153000Z"),
            run_mode="intraday-provisional",
            failed_ticker_count=0,
            bars_nonempty_count=100,
            latest_bar_date_mismatch_count=0,
            insufficient_history_count=0,
        ),
        candidates=[
            CandidateResult(
                ticker="AAPL",
                name="Apple Inc.",
                score=55,
                subscores=ScoreBreakdown(oversold=20, bottom_context=15, reversal=10, volume=5, market_context=5),
                reasons=["BB 하단 근처 또는 재진입 구간", "최근 20일 저점 부근"],
                risks=["중기 추세는 아직 하락 압력일 수 있음"],
                indicator_snapshot={"earnings_penalty": 0, "volatility_penalty": 0},
                generated_at=datetime(2026, 4, 21, 15, 30, tzinfo=timezone.utc),
            )
        ],
    )
    collection_result = CollectionResult(
        plan=CollectionPlan(
            window_index=0,
            total_windows=1,
            window_tickers=[f"T{i:02d}" for i in range(50)],
            minute_batches=[],
            remaining_tickers=[],
            max_credits_per_minute=5,
        ),
        collected=[],
        successes=[],
        failures={},
        skipped_due_to_credit_exhaustion=[],
        artifacts=CollectionArtifacts(run_directory=None, metadata_path=None, quotes_path=None),
    )
    collection_result = CollectionResult(
        plan=collection_result.plan,
        collected=[
            CollectedQuote(
                ticker=f"T{i:02d}",
                timestamp="2026-04-21T15:29:00+00:00",
                open=111.0,
                high=113.0,
                low=109.0,
                close=112.0,
                volume=3210000.0,
            )
            for i in range(50)
        ],
        successes=[f"T{i:02d}" for i in range(50)],
        failures={},
        skipped_due_to_credit_exhaustion=[],
        artifacts=CollectionArtifacts(run_directory=None, metadata_path=None, quotes_path=None),
    )

    document, _ = build_intraday_alert_document(
        result,
        collection_result=collection_result,
        state=AlertState(),
        artifact_directory="output/intraday/2026-04-21/window-01-of-01/run-20260421T153000Z",
        report_path="output/intraday/2026-04-21/window-01-of-01/run-20260421T153000Z/collected-quotes.json",
        metadata_path="output/intraday/2026-04-21/window-01-of-01/run-20260421T153000Z/collection-metadata.json",
    )

    assert document.summary.quality_gate == "warn"
    assert [event.event_type for event in document.events] == ["digest_alert"]
    assert document.events[0].severity == "warning"
