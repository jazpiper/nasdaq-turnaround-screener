from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from screener.data import EarningsInfo
from screener.models import PipelineContext, TickerInput

from .contracts import MarketDataProvider

BENCHMARK_TICKER = "QQQ"
TRADING_TIMEZONE_NAME = "America/New_York"
TRADING_TIMEZONE = ZoneInfo(TRADING_TIMEZONE_NAME)


def normalize_generated_at(generated_at: datetime | None) -> datetime:
    if generated_at is None:
        return datetime.now(TRADING_TIMEZONE)
    if generated_at.tzinfo is None:
        # Treat naive datetimes as already aligned to the trading timezone.
        return generated_at.replace(tzinfo=TRADING_TIMEZONE)
    return generated_at.astimezone(TRADING_TIMEZONE)


def _close_improvement_streak(closes: list[float]) -> int:
    if len(closes) < 2:
        return 0
    streak = 0
    for index in range(len(closes) - 1, 0, -1):
        if closes[index] > closes[index - 1]:
            streak += 1
        else:
            break
    return streak


def _latest_change(values: list[float | None], periods: int) -> float:
    valid = [float(value) for value in values if value is not None]
    if len(valid) <= periods:
        return 0.0
    return valid[-1] - valid[-1 - periods]


def _percent_return(closes: list[float], periods: int) -> float | None:
    if len(closes) <= periods:
        return None
    previous_close = closes[-1 - periods]
    if previous_close == 0:
        return None
    return ((closes[-1] / previous_close) - 1.0) * 100.0


def fetch_benchmark_context(market_data_provider: MarketDataProvider, context: PipelineContext) -> dict[str, Any]:
    benchmark = TickerInput(ticker=BENCHMARK_TICKER)
    prepare = getattr(market_data_provider, "prepare", None)
    if callable(prepare):
        prepare([benchmark], context)
    history = market_data_provider.fetch_history(benchmark, context)
    closes = [float(value) for value in history.sort_values("date")["close"].tolist()]
    sma_20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
    qqq_above_20d_ma = (closes[-1] > sma_20) if sma_20 is not None and closes else None
    return {
        "qqq_return_20d": _percent_return(closes, 20),
        "qqq_return_60d": _percent_return(closes, 60),
        "qqq_above_20d_ma": qqq_above_20d_ma,
    }


def merge_benchmark_context(indicators: dict[str, Any], benchmark_context: dict[str, Any]) -> dict[str, Any]:
    merged = dict(indicators)
    if not benchmark_context:
        return merged

    merged.update(benchmark_context)
    stock_return_20d = merged.get("stock_return_20d")
    qqq_return_20d = merged.get("qqq_return_20d")
    if stock_return_20d is not None and qqq_return_20d is not None:
        merged["rel_strength_20d_vs_qqq"] = float(stock_return_20d) - float(qqq_return_20d)

    stock_return_60d = merged.get("stock_return_60d")
    qqq_return_60d = merged.get("qqq_return_60d")
    if stock_return_60d is not None and qqq_return_60d is not None:
        merged["rel_strength_60d_vs_qqq"] = float(stock_return_60d) - float(qqq_return_60d)
    return merged


def merge_earnings_context(indicators: dict[str, Any], earnings_info: EarningsInfo | None) -> dict[str, Any]:
    merged = dict(indicators)
    merged["earnings_data_available"] = earnings_info is not None
    if earnings_info is None:
        return merged

    merged["next_earnings_date"] = (
        earnings_info.next_earnings_date.isoformat() if earnings_info.next_earnings_date is not None else None
    )
    merged["days_to_next_earnings"] = earnings_info.days_to_next_earnings
    merged["days_since_last_earnings"] = earnings_info.days_since_last_earnings
    return merged


__all__ = [
    "BENCHMARK_TICKER",
    "TRADING_TIMEZONE",
    "TRADING_TIMEZONE_NAME",
    "fetch_benchmark_context",
    "merge_benchmark_context",
    "merge_earnings_context",
    "normalize_generated_at",
]
