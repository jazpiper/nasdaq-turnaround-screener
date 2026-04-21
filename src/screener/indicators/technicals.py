from __future__ import annotations

from collections import deque
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


def add_indicator_columns(bars: Iterable[DailyBar]) -> list[dict[str, float | str | None]]:
    rows = sorted(bars, key=lambda bar: bar.trading_date)
    closes = [bar.close for bar in rows]
    volumes = [bar.volume for bar in rows]
    bb = bollinger_bands(closes, window=20, num_stddev=2.0)
    sma5 = rolling_mean(closes, 5)
    sma20 = rolling_mean(closes, 20)
    sma60 = rolling_mean(closes, 60)
    rsi14 = rsi(closes, 14)
    dist20 = distance_from_recent_low(closes, 20)
    dist60 = distance_from_recent_low(closes, 60)
    vol_ratio = volume_ratio(volumes, 20)

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
                "rsi_14": rsi14[index],
                "distance_to_20d_low": dist20[index],
                "distance_to_60d_low": dist60[index],
                "volume_ratio_20d": vol_ratio[index],
            }
        )
    return enriched
