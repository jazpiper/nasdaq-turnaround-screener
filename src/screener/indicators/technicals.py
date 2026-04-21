from __future__ import annotations

from collections import deque
from datetime import timedelta
from math import sqrt
from typing import Iterable

from screener.data.market_data import DailyBar


def rolling_mean(values: Iterable[float], window: int) -> list[float | None]:
    if window <= 0:
        raise ValueError("window must be positive")
    queue: deque[float] = deque()
    result: list[float | None] = []
    total = 0.0
    for value in values:
        number = float(value)
        queue.append(number)
        total += number
        if len(queue) > window:
            total -= queue.popleft()
        result.append(total / window if len(queue) == window else None)
    return result


def rolling_stddev(values: Iterable[float], window: int) -> list[float | None]:
    queue: deque[float] = deque()
    result: list[float | None] = []
    total = 0.0
    total_sq = 0.0
    for value in values:
        number = float(value)
        queue.append(number)
        total += number
        total_sq += number * number
        if len(queue) > window:
            removed = queue.popleft()
            total -= removed
            total_sq -= removed * removed
        if len(queue) == window:
            mean = total / window
            variance = max((total_sq / window) - (mean * mean), 0.0)
            result.append(sqrt(variance))
        else:
            result.append(None)
    return result


def bollinger_bands(closes: Iterable[float], window: int = 20, num_stddev: float = 2.0) -> dict[str, list[float | None]]:
    close_values = [float(value) for value in closes]
    mid = rolling_mean(close_values, window)
    stddev = rolling_stddev(close_values, window)
    upper: list[float | None] = []
    lower: list[float | None] = []
    for mean, sigma in zip(mid, stddev):
        if mean is None or sigma is None:
            upper.append(None)
            lower.append(None)
        else:
            upper.append(mean + num_stddev * sigma)
            lower.append(mean - num_stddev * sigma)
    return {"middle": mid, "upper": upper, "lower": lower}


def true_range(highs: Iterable[float], lows: Iterable[float], closes: Iterable[float]) -> list[float]:
    high_values = [float(value) for value in highs]
    low_values = [float(value) for value in lows]
    close_values = [float(value) for value in closes]
    result: list[float] = []
    previous_close: float | None = None

    for high, low, close in zip(high_values, low_values, close_values):
        intraday_range = high - low
        if previous_close is None:
            result.append(intraday_range)
        else:
            result.append(max(intraday_range, abs(high - previous_close), abs(low - previous_close)))
        previous_close = close

    return result


def average_true_range(
    highs: Iterable[float],
    lows: Iterable[float],
    closes: Iterable[float],
    window: int = 14,
) -> list[float | None]:
    return rolling_mean(true_range(highs, lows, closes), window)


def rsi(closes: Iterable[float], window: int = 14) -> list[float | None]:
    close_values = [float(value) for value in closes]
    if not close_values:
        return []
    gains: list[float] = [0.0]
    losses: list[float] = [0.0]
    for index in range(1, len(close_values)):
        delta = close_values[index] - close_values[index - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    avg_gain = rolling_mean(gains, window)
    avg_loss = rolling_mean(losses, window)
    result: list[float | None] = []
    for gain, loss in zip(avg_gain, avg_loss):
        if gain is None or loss is None:
            result.append(None)
        elif loss == 0:
            result.append(100.0)
        else:
            rs = gain / loss
            result.append(100.0 - (100.0 / (1.0 + rs)))
    return result


def distance_from_recent_low(closes: Iterable[float], window: int) -> list[float | None]:
    close_values = [float(value) for value in closes]
    queue: deque[float] = deque()
    result: list[float | None] = []
    for value in close_values:
        queue.append(value)
        if len(queue) > window:
            queue.popleft()
        if len(queue) == window:
            recent_low = min(queue)
            result.append(0.0 if recent_low <= 0 else ((value / recent_low) - 1.0) * 100.0)
        else:
            result.append(None)
    return result


def volume_ratio(volumes: Iterable[float], window: int = 20) -> list[float | None]:
    volume_values = [float(value) for value in volumes]
    averages = rolling_mean(volume_values, window)
    result: list[float | None] = []
    for value, average in zip(volume_values, averages):
        if average is None or average == 0:
            result.append(None)
        else:
            result.append(value / average)
    return result


def aggregate_weekly_bars(bars: Iterable[DailyBar]) -> list[DailyBar]:
    daily_bars = sorted(bars, key=lambda bar: bar.trading_date)
    weekly: list[DailyBar] = []
    current_week: list[DailyBar] = []
    current_week_key = None

    for bar in daily_bars:
        week_key = bar.trading_date - timedelta(days=bar.trading_date.weekday())
        if current_week and week_key != current_week_key:
            weekly.append(_merge_weekly_bar(current_week))
            current_week = []
        current_week_key = week_key
        current_week.append(bar)

    if current_week:
        weekly.append(_merge_weekly_bar(current_week))

    return weekly


def _merge_weekly_bar(bars: list[DailyBar]) -> DailyBar:
    first = bars[0]
    last = bars[-1]
    return DailyBar(
        ticker=first.ticker,
        trading_date=last.trading_date,
        open=first.open,
        high=max(bar.high for bar in bars),
        low=min(bar.low for bar in bars),
        close=last.close,
        adj_close=last.adj_close,
        volume=sum(bar.volume for bar in bars),
    )


def latest_weekly_context(bars: Iterable[DailyBar]) -> dict[str, float | int | bool | None]:
    weekly_bars = aggregate_weekly_bars(bars)
    closes = [bar.close for bar in weekly_bars]
    sma5 = rolling_mean(closes, 5)
    sma10 = rolling_mean(closes, 10)
    latest_close = closes[-1] if closes else None
    latest_sma5 = sma5[-1] if sma5 else None
    latest_sma10 = sma10[-1] if sma10 else None
    previous_close = closes[-2] if len(closes) >= 2 else None
    improving = bool(latest_close is not None and previous_close is not None and latest_close >= previous_close)

    severe_damage = False
    if latest_close is not None and latest_sma10 not in (None, 0) and latest_sma5 is not None:
        severe_damage = (
            latest_close < latest_sma10 * 0.85
            and latest_sma5 < latest_sma10
            and not improving
        )

    trend_penalty = 0.0
    if latest_close is not None and latest_sma10 not in (None, 0) and latest_sma5 is not None:
        if latest_close < latest_sma10 * 0.9 and latest_sma5 < latest_sma10 and not improving:
            trend_penalty = 6.0
        elif latest_close < latest_sma10 * 0.95 and latest_sma5 < latest_sma10 and not improving:
            trend_penalty = 3.0

    return {
        "weekly_bars_available": len(weekly_bars),
        "weekly_close": latest_close,
        "weekly_sma_5": latest_sma5,
        "weekly_sma_10": latest_sma10,
        "weekly_close_improving": improving,
        "weekly_trend_severe_damage": severe_damage,
        "weekly_trend_penalty": trend_penalty,
    }


def add_indicator_columns(bars: Iterable[DailyBar]) -> list[dict[str, float | str | None]]:
    rows = sorted(bars, key=lambda bar: bar.trading_date)
    closes = [bar.close for bar in rows]
    highs = [bar.high for bar in rows]
    lows = [bar.low for bar in rows]
    volumes = [bar.volume for bar in rows]
    bb = bollinger_bands(closes, window=20, num_stddev=2.0)
    atr14 = average_true_range(highs, lows, closes, window=14)
    sma5 = rolling_mean(closes, 5)
    sma20 = rolling_mean(closes, 20)
    sma60 = rolling_mean(closes, 60)
    rsi14 = rsi(closes, 14)
    dist20 = distance_from_recent_low(closes, 20)
    dist60 = distance_from_recent_low(closes, 60)
    vol_ratio = volume_ratio(volumes, 20)
    atr14_pct = [None if atr is None or close == 0 else (atr / close) * 100.0 for atr, close in zip(atr14, closes)]
    daily_range_pct = [None if close == 0 else ((high - low) / close) * 100.0 for high, low, close in zip(highs, lows, closes)]
    bb_width_pct = [
        None if upper is None or lower is None or close == 0 else ((upper - lower) / close) * 100.0
        for upper, lower, close in zip(bb["upper"], bb["lower"], closes)
    ]

    enriched: list[dict[str, float | str | None]] = []
    for index, bar in enumerate(rows):
        enriched.append(
            {
                "ticker": bar.ticker,
                "trading_date": bar.trading_date.isoformat(),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "adj_close": bar.adj_close,
                "volume": bar.volume,
                "sma_5": sma5[index],
                "sma_20": sma20[index],
                "sma_60": sma60[index],
                "bb_middle": bb["middle"][index],
                "bb_upper": bb["upper"][index],
                "bb_lower": bb["lower"][index],
                "atr_14": atr14[index],
                "atr_14_pct": atr14_pct[index],
                "daily_range_pct": daily_range_pct[index],
                "bb_width_pct": bb_width_pct[index],
                "rsi_14": rsi14[index],
                "distance_to_20d_low": dist20[index],
                "distance_to_60d_low": dist60[index],
                "volume_ratio_20d": vol_ratio[index],
            }
        )
    return enriched
