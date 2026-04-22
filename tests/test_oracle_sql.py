from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from screener.collector import CollectedQuote, CollectionArtifacts, CollectionPlan, CollectionResult
from screener.models import CandidateResult, RunMetadata, ScoreBreakdown, ScreenRunResult
from screener.storage.oracle_sql import OracleSqlStorage


class FakeCursor:
    def __init__(self, statements: list[tuple[str, dict | None]]) -> None:
        self.statements = statements
        self.closed = False

    def execute(self, statement: str, parameters: dict | None = None) -> None:
        self.statements.append((" ".join(statement.split()), parameters))

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    def __init__(self) -> None:
        self.statements: list[tuple[str, dict | None]] = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.statements)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def make_screen_result(tmp_path: Path) -> ScreenRunResult:
    return ScreenRunResult(
        metadata=RunMetadata(
            run_date=date(2026, 4, 21),
            generated_at=datetime(2026, 4, 21, 7, 30, tzinfo=timezone.utc),
            universe="NASDAQ-100",
            run_mode="daily",
            dry_run=False,
            artifact_directory=tmp_path,
            data_failures=["NVDA: No price rows returned"],
            notes=["oracle persistence test"],
        ),
        candidates=[
            CandidateResult(
                ticker="AAPL",
                score=78,
                subscores=ScoreBreakdown(oversold=20, bottom_context=17, reversal=23, volume=10, market_context=8),
                close=172.4,
                lower_bb=171.9,
                rsi14=33.2,
                distance_to_20d_low=1.8,
                reasons=["BB 하단 근처 또는 재진입 구간"],
                risks=["중기 추세는 아직 하락 압력일 수 있음"],
                indicator_snapshot={
                    "schema_version": 2,
                    "earnings_data_available": False,
                    "sma_5": 173.1,
                    "atr_14_pct": 2.8,
                    "bb_width_pct": 11.5,
                    "close_location_value": 0.82,
                    "upper_wick_ratio": 0.12,
                    "inside_day": True,
                    "bullish_engulfing_like": True,
                    "gap_down_reclaim": True,
                    "volatility_penalty": 0,
                    "volume_ratio_20d": 1.2,
                    "weekly_trend_penalty": 0.0,
                },
                snapshot_schema_version=2,
                generated_at=datetime(2026, 4, 21, 7, 30, tzinfo=timezone.utc),
            )
        ],
    )


def make_collection_result(tmp_path: Path) -> CollectionResult:
    run_directory = tmp_path / "2026-04-21" / "window-01-of-06" / "run-20260421T073000Z"
    run_directory.mkdir(parents=True)
    metadata_path = run_directory / "collection-metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "run_date": "2026-04-21",
                "started_at": "2026-04-21T07:30:00+00:00",
                "completed_at": "2026-04-21T07:32:16+00:00",
                "provider": "twelve-data",
                "interval": "1min",
                "window_index": 0,
                "window_number": 1,
                "total_windows": 6,
                "max_credits_per_minute": 8,
                "planned_tickers": ["AAPL"],
                "minute_batches": [["AAPL"]],
                "successes": ["AAPL"],
                "failures": {},
                "skipped_due_to_credit_exhaustion": [],
                "remaining_tickers": ["MSFT"],
                "uncollected_tickers": [],
                "collected_count": 1,
                "failed_count": 0,
                "skipped_due_to_credit_exhaustion_count": 0,
                "remaining_count": 1,
            }
        ),
        encoding="utf-8",
    )

    return CollectionResult(
        plan=CollectionPlan(
            window_index=0,
            total_windows=6,
            window_tickers=["AAPL"],
            minute_batches=[["AAPL"]],
            remaining_tickers=["MSFT"],
            max_credits_per_minute=8,
        ),
        collected=[
            CollectedQuote(
                ticker="AAPL",
                timestamp="2026-04-21T07:31:00+00:00",
                open=172.0,
                high=173.0,
                low=171.8,
                close=172.6,
                volume=123456,
            )
        ],
        successes=["AAPL"],
        failures={},
        skipped_due_to_credit_exhaustion=[],
        artifacts=CollectionArtifacts(
            run_directory=run_directory,
            metadata_path=metadata_path,
            quotes_path=run_directory / "collected-quotes.json",
        ),
    )


def test_persist_daily_run_executes_schema_and_inserts(tmp_path: Path) -> None:
    connection = FakeConnection()
    storage = OracleSqlStorage(connector=lambda: connection)

    storage.initialize_schema()

    assert connection.committed is True
    assert any("CREATE TABLE screen_runs" in statement for statement, _ in connection.statements)
    assert any("ALTER TABLE screen_candidates ADD ( indicator_snapshot_json CLOB )" in statement for statement, _ in connection.statements)


def test_persist_daily_run_inserts_without_schema_ddl(tmp_path: Path) -> None:
    connection = FakeConnection()
    storage = OracleSqlStorage(connector=lambda: connection)

    run_id = storage.persist_daily_run(make_screen_result(tmp_path))

    assert run_id.startswith("run_")
    assert connection.committed is True
    assert connection.rolled_back is False
    assert connection.closed is True
    assert any("INSERT INTO screen_runs" in statement for statement, _ in connection.statements)
    assert not any("CREATE TABLE" in statement for statement, _ in connection.statements)
    assert not any("ALTER TABLE" in statement for statement, _ in connection.statements)
    candidate_insert = next(parameters for statement, parameters in connection.statements if "INSERT INTO screen_candidates" in statement)
    assert candidate_insert is not None
    assert "volume_ratio_20d" in candidate_insert["indicator_snapshot_json"]
    assert "volatility_penalty" in candidate_insert["indicator_snapshot_json"]
    assert "gap_down_reclaim" in candidate_insert["indicator_snapshot_json"]
    assert "bullish_engulfing_like" in candidate_insert["indicator_snapshot_json"]
    assert candidate_insert["snapshot_schema_version"] == 2
    assert any("INSERT INTO candidate_subscores" in statement for statement, _ in connection.statements)


def test_persist_intraday_collection_inserts_without_schema_ddl(tmp_path: Path) -> None:
    connection = FakeConnection()
    storage = OracleSqlStorage(connector=lambda: connection)

    collection_run_id = storage.persist_intraday_collection(make_collection_result(tmp_path))

    assert collection_run_id.startswith("intraday_")
    assert connection.committed is True
    assert connection.rolled_back is False
    assert connection.closed is True
    assert any("INSERT INTO intraday_collection_runs" in statement for statement, _ in connection.statements)
    assert any("INSERT INTO intraday_collection_quotes" in statement for statement, _ in connection.statements)
    assert not any("CREATE TABLE" in statement for statement, _ in connection.statements)
    intraday_insert = next(
        parameters for statement, parameters in connection.statements if "INSERT INTO intraday_collection_runs" in statement
    )
    assert intraday_insert["credit_exhaustion_skips_json"] == "[]"
    assert intraday_insert["credit_exhaustion_skip_count"] == 0
