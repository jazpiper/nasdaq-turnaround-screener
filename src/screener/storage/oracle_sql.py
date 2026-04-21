from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable
from uuid import uuid4

from screener.config import Settings
from screener.models import ScreenRunResult

if TYPE_CHECKING:
    from screener.collector import CollectionResult


@dataclass(frozen=True, slots=True)
class OracleSqlCredentials:
    user: str
    password: str
    connect_string: str


class OracleSqlStorageError(RuntimeError):
    """Raised when Oracle SQL persistence cannot be configured or completed."""


class OracleSqlStorage:
    def __init__(self, connector: Callable[[], Any]) -> None:
        self.connector = connector

    @classmethod
    def from_settings(cls, settings: Settings) -> "OracleSqlStorage | None":
        if not settings.oracle_sql_enabled:
            return None

        missing = [
            name
            for name, value in {
                "oracle_sql_user": settings.oracle_sql_user,
                "oracle_sql_password": settings.oracle_sql_password,
                "oracle_sql_connect_string": settings.oracle_sql_connect_string,
            }.items()
            if not value
        ]
        if missing:
            raise OracleSqlStorageError(
                "Oracle SQL persistence is enabled but credentials are missing: " + ", ".join(missing)
            )

        try:
            import oracledb
        except ModuleNotFoundError as exc:  # pragma: no cover, exercised in integration environments
            raise OracleSqlStorageError("oracledb is required for Oracle SQL persistence") from exc

        credentials = OracleSqlCredentials(
            user=str(settings.oracle_sql_user),
            password=str(settings.oracle_sql_password),
            connect_string=str(settings.oracle_sql_connect_string),
        )
        return cls(
            connector=lambda: oracledb.connect(
                user=credentials.user,
                password=credentials.password,
                dsn=credentials.connect_string,
            )
        )

    def persist_daily_run(self, result: ScreenRunResult) -> str:
        connection = self.connector()
        try:
            self._ensure_schema(connection)
            run_id = f"run_{uuid4().hex}"
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO screen_runs (
                        run_id,
                        run_date,
                        generated_at,
                        universe_name,
                        run_mode,
                        dry_run,
                        artifact_directory,
                        candidate_count,
                        data_failures_json,
                        notes_json
                    ) VALUES (
                        :run_id,
                        :run_date,
                        :generated_at,
                        :universe_name,
                        :run_mode,
                        :dry_run,
                        :artifact_directory,
                        :candidate_count,
                        :data_failures_json,
                        :notes_json
                    )
                    """,
                    {
                        "run_id": run_id,
                        "run_date": result.metadata.run_date,
                        "generated_at": result.metadata.generated_at,
                        "universe_name": result.metadata.universe,
                        "run_mode": result.metadata.run_mode,
                        "dry_run": 1 if result.metadata.dry_run else 0,
                        "artifact_directory": str(result.metadata.artifact_directory),
                        "candidate_count": result.candidate_count,
                        "data_failures_json": _json(result.metadata.data_failures),
                        "notes_json": _json(result.metadata.notes),
                    },
                )

                for candidate in result.candidates:
                    candidate_id = f"cand_{uuid4().hex}"
                    cursor.execute(
                        """
                        INSERT INTO screen_candidates (
                            candidate_id,
                            run_id,
                            ticker,
                            score,
                            close_price,
                            lower_bb,
                            rsi14,
                            distance_to_20d_low,
                            reasons_json,
                            risks_json,
                            indicator_snapshot_json,
                            snapshot_schema_version,
                            generated_at
                        ) VALUES (
                            :candidate_id,
                            :run_id,
                            :ticker,
                            :score,
                            :close_price,
                            :lower_bb,
                            :rsi14,
                            :distance_to_20d_low,
                            :reasons_json,
                            :risks_json,
                            :indicator_snapshot_json,
                            :snapshot_schema_version,
                            :generated_at
                        )
                        """,
                        {
                            "candidate_id": candidate_id,
                            "run_id": run_id,
                            "ticker": candidate.ticker,
                            "score": candidate.score,
                            "close_price": candidate.close,
                            "lower_bb": candidate.lower_bb,
                            "rsi14": candidate.rsi14,
                            "distance_to_20d_low": candidate.distance_to_20d_low,
                            "reasons_json": _json(candidate.reasons),
                            "risks_json": _json(candidate.risks),
                            "indicator_snapshot_json": _json(candidate.indicator_snapshot) if candidate.indicator_snapshot is not None else None,
                            "snapshot_schema_version": candidate.snapshot_schema_version,
                            "generated_at": candidate.generated_at,
                        },
                    )
                    cursor.execute(
                        """
                        INSERT INTO candidate_subscores (
                            candidate_id,
                            oversold,
                            bottom_context,
                            reversal,
                            volume_score,
                            market_context
                        ) VALUES (
                            :candidate_id,
                            :oversold,
                            :bottom_context,
                            :reversal,
                            :volume_score,
                            :market_context
                        )
                        """,
                        {
                            "candidate_id": candidate_id,
                            "oversold": candidate.subscores.oversold,
                            "bottom_context": candidate.subscores.bottom_context,
                            "reversal": candidate.subscores.reversal,
                            "volume_score": candidate.subscores.volume,
                            "market_context": candidate.subscores.market_context,
                        },
                    )
            finally:
                _close_safely(cursor)

            connection.commit()
            return run_id
        except Exception as exc:
            _rollback_safely(connection)
            raise OracleSqlStorageError(f"Oracle SQL daily persistence failed: {exc}") from exc
        finally:
            _close_safely(connection)

    def persist_intraday_collection(self, result: CollectionResult) -> str:
        metadata_path = result.artifacts.metadata_path
        if metadata_path is None:
            raise OracleSqlStorageError("Intraday Oracle SQL persistence requires metadata artifacts")

        metadata = _read_json(metadata_path)
        connection = self.connector()
        try:
            self._ensure_schema(connection)
            collection_run_id = f"intraday_{uuid4().hex}"
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO intraday_collection_runs (
                        collection_run_id,
                        run_date,
                        started_at,
                        completed_at,
                        provider,
                        interval_name,
                        window_index,
                        window_number,
                        total_windows,
                        max_credits_per_minute,
                        planned_tickers_json,
                        minute_batches_json,
                        successes_json,
                        failures_json,
                        remaining_tickers_json,
                        uncollected_tickers_json,
                        collected_count,
                        failed_count,
                        remaining_count,
                        artifact_directory
                    ) VALUES (
                        :collection_run_id,
                        :run_date,
                        :started_at,
                        :completed_at,
                        :provider,
                        :interval_name,
                        :window_index,
                        :window_number,
                        :total_windows,
                        :max_credits_per_minute,
                        :planned_tickers_json,
                        :minute_batches_json,
                        :successes_json,
                        :failures_json,
                        :remaining_tickers_json,
                        :uncollected_tickers_json,
                        :collected_count,
                        :failed_count,
                        :remaining_count,
                        :artifact_directory
                    )
                    """,
                    {
                        "collection_run_id": collection_run_id,
                        "run_date": _parse_date(metadata["run_date"]),
                        "started_at": _parse_datetime(metadata["started_at"]),
                        "completed_at": _parse_datetime(metadata["completed_at"]),
                        "provider": metadata.get("provider", "twelve-data"),
                        "interval_name": metadata.get("interval", "1min"),
                        "window_index": metadata["window_index"],
                        "window_number": metadata["window_number"],
                        "total_windows": metadata["total_windows"],
                        "max_credits_per_minute": metadata["max_credits_per_minute"],
                        "planned_tickers_json": _json(metadata.get("planned_tickers", [])),
                        "minute_batches_json": _json(metadata.get("minute_batches", [])),
                        "successes_json": _json(metadata.get("successes", [])),
                        "failures_json": _json(metadata.get("failures", {})),
                        "remaining_tickers_json": _json(metadata.get("remaining_tickers", [])),
                        "uncollected_tickers_json": _json(metadata.get("uncollected_tickers", [])),
                        "collected_count": metadata.get("collected_count", len(result.collected)),
                        "failed_count": metadata.get("failed_count", len(result.failures)),
                        "remaining_count": metadata.get("remaining_count", len(result.plan.remaining_tickers)),
                        "artifact_directory": str(result.artifacts.run_directory) if result.artifacts.run_directory else None,
                    },
                )

                for quote in result.collected:
                    cursor.execute(
                        """
                        INSERT INTO intraday_collection_quotes (
                            quote_id,
                            collection_run_id,
                            ticker,
                            quote_timestamp,
                            open_price,
                            high_price,
                            low_price,
                            close_price,
                            volume
                        ) VALUES (
                            :quote_id,
                            :collection_run_id,
                            :ticker,
                            :quote_timestamp,
                            :open_price,
                            :high_price,
                            :low_price,
                            :close_price,
                            :volume
                        )
                        """,
                        {
                            "quote_id": f"quote_{uuid4().hex}",
                            "collection_run_id": collection_run_id,
                            "ticker": quote.ticker,
                            "quote_timestamp": quote.timestamp,
                            "open_price": quote.open,
                            "high_price": quote.high,
                            "low_price": quote.low,
                            "close_price": quote.close,
                            "volume": quote.volume,
                        },
                    )
            finally:
                _close_safely(cursor)

            connection.commit()
            return collection_run_id
        except Exception as exc:
            _rollback_safely(connection)
            raise OracleSqlStorageError(f"Oracle SQL intraday persistence failed: {exc}") from exc
        finally:
            _close_safely(connection)

    def _ensure_schema(self, connection: Any) -> None:
        cursor = connection.cursor()
        try:
            for statement in _SCHEMA_STATEMENTS:
                cursor.execute(statement)
        finally:
            _close_safely(cursor)


_SCHEMA_STATEMENTS = (
    """
    BEGIN
      EXECUTE IMMEDIATE '
        CREATE TABLE screen_runs (
          run_id VARCHAR2(64) PRIMARY KEY,
          run_date DATE NOT NULL,
          generated_at TIMESTAMP WITH TIME ZONE NOT NULL,
          universe_name VARCHAR2(100) NOT NULL,
          run_mode VARCHAR2(50) NOT NULL,
          dry_run NUMBER(1) DEFAULT 0 NOT NULL,
          artifact_directory VARCHAR2(1000) NOT NULL,
          candidate_count NUMBER DEFAULT 0 NOT NULL,
          data_failures_json CLOB,
          notes_json CLOB,
          created_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL
        )';
    EXCEPTION
      WHEN OTHERS THEN
        IF SQLCODE != -955 THEN RAISE; END IF;
    END;
    """,
    """
    BEGIN
      EXECUTE IMMEDIATE '
        CREATE TABLE screen_candidates (
          candidate_id VARCHAR2(64) PRIMARY KEY,
          run_id VARCHAR2(64) NOT NULL,
          ticker VARCHAR2(32) NOT NULL,
          score NUMBER NOT NULL,
          close_price NUMBER,
          lower_bb NUMBER,
          rsi14 NUMBER,
          distance_to_20d_low NUMBER,
          reasons_json CLOB,
          risks_json CLOB,
          indicator_snapshot_json CLOB,
          snapshot_schema_version NUMBER DEFAULT 1 NOT NULL,
          generated_at TIMESTAMP WITH TIME ZONE NOT NULL,
          created_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
          CONSTRAINT fk_screen_candidates_run
            FOREIGN KEY (run_id) REFERENCES screen_runs(run_id)
        )';
    EXCEPTION
      WHEN OTHERS THEN
        IF SQLCODE != -955 THEN RAISE; END IF;
    END;
    """,
    """
    BEGIN
      EXECUTE IMMEDIATE '
        ALTER TABLE screen_candidates ADD (
          indicator_snapshot_json CLOB
        )';
    EXCEPTION
      WHEN OTHERS THEN
        IF SQLCODE != -1430 THEN RAISE; END IF;
    END;
    """,
    """
    BEGIN
      EXECUTE IMMEDIATE '
        ALTER TABLE screen_candidates ADD (
          snapshot_schema_version NUMBER DEFAULT 1 NOT NULL
        )';
    EXCEPTION
      WHEN OTHERS THEN
        IF SQLCODE != -1430 THEN RAISE; END IF;
    END;
    """,
    """
    BEGIN
      EXECUTE IMMEDIATE '
        CREATE TABLE candidate_subscores (
          candidate_id VARCHAR2(64) PRIMARY KEY,
          oversold NUMBER DEFAULT 0 NOT NULL,
          bottom_context NUMBER DEFAULT 0 NOT NULL,
          reversal NUMBER DEFAULT 0 NOT NULL,
          volume_score NUMBER DEFAULT 0 NOT NULL,
          market_context NUMBER DEFAULT 0 NOT NULL,
          CONSTRAINT fk_candidate_subscores_candidate
            FOREIGN KEY (candidate_id) REFERENCES screen_candidates(candidate_id)
        )';
    EXCEPTION
      WHEN OTHERS THEN
        IF SQLCODE != -955 THEN RAISE; END IF;
    END;
    """,
    """
    BEGIN
      EXECUTE IMMEDIATE '
        CREATE TABLE intraday_collection_runs (
          collection_run_id VARCHAR2(64) PRIMARY KEY,
          run_date DATE NOT NULL,
          started_at TIMESTAMP WITH TIME ZONE NOT NULL,
          completed_at TIMESTAMP WITH TIME ZONE NOT NULL,
          provider VARCHAR2(50) NOT NULL,
          interval_name VARCHAR2(20) NOT NULL,
          window_index NUMBER NOT NULL,
          window_number NUMBER NOT NULL,
          total_windows NUMBER NOT NULL,
          max_credits_per_minute NUMBER NOT NULL,
          planned_tickers_json CLOB,
          minute_batches_json CLOB,
          successes_json CLOB,
          failures_json CLOB,
          remaining_tickers_json CLOB,
          uncollected_tickers_json CLOB,
          collected_count NUMBER DEFAULT 0 NOT NULL,
          failed_count NUMBER DEFAULT 0 NOT NULL,
          remaining_count NUMBER DEFAULT 0 NOT NULL,
          artifact_directory VARCHAR2(1000),
          created_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL
        )';
    EXCEPTION
      WHEN OTHERS THEN
        IF SQLCODE != -955 THEN RAISE; END IF;
    END;
    """,
    """
    BEGIN
      EXECUTE IMMEDIATE '
        CREATE TABLE intraday_collection_quotes (
          quote_id VARCHAR2(64) PRIMARY KEY,
          collection_run_id VARCHAR2(64) NOT NULL,
          ticker VARCHAR2(32) NOT NULL,
          quote_timestamp VARCHAR2(64) NOT NULL,
          open_price NUMBER NOT NULL,
          high_price NUMBER NOT NULL,
          low_price NUMBER NOT NULL,
          close_price NUMBER NOT NULL,
          volume NUMBER NOT NULL,
          created_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
          CONSTRAINT fk_intraday_quotes_run
            FOREIGN KEY (collection_run_id) REFERENCES intraday_collection_runs(collection_run_id)
        )';
    EXCEPTION
      WHEN OTHERS THEN
        IF SQLCODE != -955 THEN RAISE; END IF;
    END;
    """,
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value))


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _rollback_safely(connection: Any) -> None:
    rollback = getattr(connection, "rollback", None)
    if callable(rollback):
        rollback()


def _close_safely(resource: Any) -> None:
    close = getattr(resource, "close", None)
    if callable(close):
        close()
