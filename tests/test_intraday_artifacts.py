from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from screener.data import DailyBar
from screener.indicators.technicals import add_indicator_columns
from screener.intraday_artifacts import (
    StagedIntradayQuote,
    discover_latest_intraday_snapshot,
    merge_history_with_staged_quote,
)


def write_snapshot(root: Path, *, run_date: str, window: str, run_id: str, completed_at: str, quotes: list[dict]) -> Path:
    run_dir = root / run_date / window / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / 'collection-metadata.json').write_text(json.dumps({'completed_at': completed_at}), encoding='utf-8')
    (run_dir / 'collected-quotes.json').write_text(json.dumps({'quotes': quotes}), encoding='utf-8')
    return run_dir


def test_discover_latest_intraday_snapshot_picks_latest_completed_run(tmp_path: Path) -> None:
    write_snapshot(
        tmp_path,
        run_date='2026-04-21',
        window='window-01-of-06',
        run_id='run-20260421T140000Z',
        completed_at='2026-04-21T14:00:00+00:00',
        quotes=[{'ticker': 'AAPL', 'timestamp': '2026-04-21T14:00:00+00:00', 'open': 100, 'high': 101, 'low': 99, 'close': 100.5, 'volume': 10}],
    )
    latest_dir = write_snapshot(
        tmp_path,
        run_date='2026-04-21',
        window='window-02-of-06',
        run_id='run-20260421T153000Z',
        completed_at='2026-04-21T15:30:00+00:00',
        quotes=[{'ticker': 'MSFT', 'timestamp': '2026-04-21T15:29:00+00:00', 'open': 200, 'high': 202, 'low': 199, 'close': 201.5, 'volume': 20}],
    )

    snapshot = discover_latest_intraday_snapshot(tmp_path, date(2026, 4, 21))

    assert snapshot is not None
    assert snapshot.run_directory == latest_dir
    assert set(snapshot.quotes_by_ticker) == {'MSFT'}
    assert snapshot.quotes_by_ticker['MSFT'].close == 201.5


def test_discover_latest_intraday_snapshot_ignores_wrong_date_metadata(tmp_path: Path) -> None:
    trusted_dir = write_snapshot(
        tmp_path,
        run_date='2026-04-21',
        window='window-01-of-06',
        run_id='run-20260421T153000Z',
        completed_at='2026-04-21T15:30:00+00:00',
        quotes=[{'ticker': 'AAPL', 'timestamp': '2026-04-21T15:29:00+00:00', 'open': 100, 'high': 101, 'low': 99, 'close': 100.5, 'volume': 10}],
    )
    write_snapshot(
        tmp_path,
        run_date='2026-04-21',
        window='window-02-of-06',
        run_id='run-20260421T235959Z',
        completed_at='2026-04-22T00:00:00+00:00',
        quotes=[{'ticker': 'MSFT', 'timestamp': '2026-04-21T23:59:00+00:00', 'open': 200, 'high': 202, 'low': 199, 'close': 201.5, 'volume': 20}],
    )

    snapshot = discover_latest_intraday_snapshot(tmp_path, date(2026, 4, 21))

    assert snapshot is not None
    assert snapshot.run_directory == trusted_dir
    assert set(snapshot.quotes_by_ticker) == {'AAPL'}


def test_discover_latest_intraday_snapshot_falls_back_from_invalid_latest_quotes(tmp_path: Path) -> None:
    trusted_dir = write_snapshot(
        tmp_path,
        run_date='2026-04-21',
        window='window-01-of-06',
        run_id='run-20260421T150000Z',
        completed_at='2026-04-21T15:00:00+00:00',
        quotes=[{'ticker': 'AAPL', 'timestamp': '2026-04-21T14:59:00+00:00', 'open': 100, 'high': 101, 'low': 99, 'close': 100.5, 'volume': 10}],
    )
    write_snapshot(
        tmp_path,
        run_date='2026-04-21',
        window='window-02-of-06',
        run_id='run-20260421T153000Z',
        completed_at='2026-04-21T15:30:00+00:00',
        quotes=[
            {'ticker': 'MSFT', 'timestamp': '2026-04-22T15:29:00+00:00', 'open': 200, 'high': 202, 'low': 199, 'close': 201.5, 'volume': 20},
            {'ticker': 'NVDA', 'timestamp': '2026-04-21T15:29:00+00:00', 'open': 200, 'high': 190, 'low': 199, 'close': 201.5, 'volume': 20},
        ],
    )

    snapshot = discover_latest_intraday_snapshot(tmp_path, date(2026, 4, 21))

    assert snapshot is not None
    assert snapshot.run_directory == trusted_dir
    assert set(snapshot.quotes_by_ticker) == {'AAPL'}


def test_merge_history_with_staged_quote_preserves_same_day_daily_volume() -> None:
    history = [
        DailyBar('AAPL', date(2026, 4, 20), 90, 91, 89, 90.5, 90.5, 1000),
        DailyBar('AAPL', date(2026, 4, 21), 100, 101, 99, 100.5, 100.5, 2000),
    ]
    staged_quote = StagedIntradayQuote(
        ticker='AAPL',
        timestamp=datetime(2026, 4, 21, 15, 30, tzinfo=timezone.utc),
        open=100,
        high=103,
        low=98,
        close=102,
        volume=2500,
        source_path=Path('collected-quotes.json'),
    )

    merged = merge_history_with_staged_quote(history, staged_quote)

    assert len(merged) == 2
    assert merged[-1].trading_date == date(2026, 4, 21)
    assert merged[-1].close == 102
    assert merged[-1].high == 103
    assert merged[-1].low == 98
    assert merged[-1].volume == 2000


def test_merge_history_with_staged_quote_appends_neutral_volume_for_new_day() -> None:
    history = [
        DailyBar('AAPL', date(2026, 4, 20), 90, 91, 89, 90.5, 90.5, 1000),
        DailyBar('AAPL', date(2026, 4, 21), 100, 101, 99, 100.5, 100.5, 3000),
    ]
    staged_quote = StagedIntradayQuote(
        ticker='AAPL',
        timestamp=datetime(2026, 4, 22, 15, 30, tzinfo=timezone.utc),
        open=100,
        high=103,
        low=98,
        close=102,
        volume=25,
        source_path=Path('collected-quotes.json'),
    )

    merged = merge_history_with_staged_quote(history, staged_quote)

    assert len(merged) == 3
    assert merged[-1].trading_date == date(2026, 4, 22)
    assert merged[-1].close == 102
    assert merged[-1].volume == 2000


def test_merge_history_with_staged_quote_keeps_volume_ratio_neutral_for_new_day() -> None:
    history = [
        DailyBar(
            "AAPL",
            date(2026, 4, day),
            100,
            101,
            99,
            100,
            100,
            1000 if day == 1 else 200,
        )
        for day in range(1, 21)
    ]
    staged_quote = StagedIntradayQuote(
        ticker='AAPL',
        timestamp=datetime(2026, 4, 21, 15, 30, tzinfo=timezone.utc),
        open=100,
        high=103,
        low=98,
        close=102,
        volume=25,
        source_path=Path('collected-quotes.json'),
    )

    merged = merge_history_with_staged_quote(history, staged_quote)
    indicators = add_indicator_columns(merged)

    assert merged[-1].volume == 200
    assert indicators[-1]["volume_ratio_20d"] == pytest.approx(1.0)
