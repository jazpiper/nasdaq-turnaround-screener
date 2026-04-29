from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable
from uuid import uuid4

from screener.config import Settings
from screener.models import ScreenRunResult
from screener.storage.oracle_schema import initialize_oracle_schema

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
                            risk_adjusted_score,
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
                            :risk_adjusted_score,
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
                            "risk_adjusted_score": candidate.risk_adjusted_score,
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
                        credit_exhaustion_skips_json,
                        remaining_tickers_json,
                        uncollected_tickers_json,
                        collected_count,
                        failed_count,
                        credit_exhaustion_skip_count,
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
                        :credit_exhaustion_skips_json,
                        :remaining_tickers_json,
                        :uncollected_tickers_json,
                        :collected_count,
                        :failed_count,
                        :credit_exhaustion_skip_count,
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
                        "credit_exhaustion_skips_json": _json(
                            metadata.get("skipped_due_to_credit_exhaustion", [])
                        ),
                        "remaining_tickers_json": _json(metadata.get("remaining_tickers", [])),
                        "uncollected_tickers_json": _json(metadata.get("uncollected_tickers", [])),
                        "collected_count": metadata.get("collected_count", len(result.collected)),
                        "failed_count": metadata.get("failed_count", len(result.failures)),
                        "credit_exhaustion_skip_count": metadata.get(
                            "skipped_due_to_credit_exhaustion_count",
                            len(metadata.get("skipped_due_to_credit_exhaustion", [])),
                        ),
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

    def initialize_schema(self) -> None:
        connection = self.connector()
        try:
            initialize_oracle_schema(connection)
            connection.commit()
        except Exception as exc:
            _rollback_safely(connection)
            raise OracleSqlStorageError(f"Oracle SQL schema initialization failed: {exc}") from exc
        finally:
            _close_safely(connection)


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
