from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from screener.config import Settings
from screener.models import TickerInput
from screener.pipeline import PreferredIntradaySnapshotMarketDataProvider, YFinanceMarketDataProvider, build_context
from tests.test_pipeline import StubFetcher, make_bars_from_history, make_history


def write_snapshot(root: Path) -> None:
    run_dir = root / '2026-04-21' / 'window-06-of-06' / 'run-20260421T153000Z'
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / 'collection-metadata.json').write_text(json.dumps({'completed_at': '2026-04-21T15:30:00+00:00'}), encoding='utf-8')
    (run_dir / 'collected-quotes.json').write_text(
        json.dumps(
            {
                'quotes': [
                    {
                        'ticker': 'AAPL',
                        'timestamp': '2026-04-21T15:29:00+00:00',
                        'open': 111.0,
                        'high': 113.0,
                        'low': 109.0,
                        'close': 112.0,
                        'volume': 3210000,
                    }
                ]
            }
        ),
        encoding='utf-8',
    )


def test_preferred_intraday_snapshot_provider_overlays_same_day_quote(tmp_path: Path) -> None:
    history = make_history(start_close=180.0)
    history.loc[history.index[-1], 'date'] = date(2026, 4, 21)
    base_provider = YFinanceMarketDataProvider(fetcher=StubFetcher({'AAPL': make_bars_from_history('AAPL', history)}))
    write_snapshot(tmp_path)
    provider = PreferredIntradaySnapshotMarketDataProvider(
        base_provider,
        Settings(intraday_output_root=tmp_path, daily_intraday_source_mode='prefer-staged'),
    )
    context = build_context(run_date=date(2026, 4, 21), dry_run=True, output_dir=tmp_path)
    ticker = TickerInput(ticker='AAPL')

    provider.prepare([ticker], context)
    merged = provider.fetch_history(ticker, context)

    latest = merged.sort_values('date').iloc[-1]
    assert float(latest['close']) == 112.0
    assert float(latest['high']) == 113.0
    assert float(latest['volume']) == 3210000.0
