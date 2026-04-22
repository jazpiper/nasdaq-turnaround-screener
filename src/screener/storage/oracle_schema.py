from __future__ import annotations

from typing import Any

from screener._pipeline.snapshot import INDICATOR_SNAPSHOT_SCHEMA_VERSION

SCHEMA_STATEMENTS = (
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
    f"""
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
          snapshot_schema_version NUMBER DEFAULT {INDICATOR_SNAPSHOT_SCHEMA_VERSION} NOT NULL,
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
    f"""
    BEGIN
      EXECUTE IMMEDIATE '
        ALTER TABLE screen_candidates ADD (
          snapshot_schema_version NUMBER DEFAULT {INDICATOR_SNAPSHOT_SCHEMA_VERSION} NOT NULL
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
          credit_exhaustion_skips_json CLOB,
          remaining_tickers_json CLOB,
          uncollected_tickers_json CLOB,
          collected_count NUMBER DEFAULT 0 NOT NULL,
          failed_count NUMBER DEFAULT 0 NOT NULL,
          credit_exhaustion_skip_count NUMBER DEFAULT 0 NOT NULL,
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
        ALTER TABLE intraday_collection_runs ADD (
          credit_exhaustion_skips_json CLOB
        )';
    EXCEPTION
      WHEN OTHERS THEN
        IF SQLCODE != -1430 THEN RAISE; END IF;
    END;
    """,
    """
    BEGIN
      EXECUTE IMMEDIATE '
        ALTER TABLE intraday_collection_runs ADD (
          credit_exhaustion_skip_count NUMBER DEFAULT 0 NOT NULL
        )';
    EXCEPTION
      WHEN OTHERS THEN
        IF SQLCODE != -1430 THEN RAISE; END IF;
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


def initialize_oracle_schema(connection: Any) -> None:
    cursor = connection.cursor()
    try:
        for statement in SCHEMA_STATEMENTS:
            cursor.execute(statement)
    finally:
        close = getattr(cursor, "close", None)
        if callable(close):
            close()
