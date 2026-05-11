from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable

from screener.data import DailyBar, MarketDataFetcher, YFinanceDailyBarFetcher

BENCHMARK_TICKER = "QQQ"
DEFAULT_MAX_SECTORS = 3
DEFAULT_PER_SECTOR_CAP = 4
DEFAULT_LOOKBACK_SHORT = 20
DEFAULT_LOOKBACK_LONG = 60

SECTOR_PROXY_TICKERS: dict[str, str] = {
    "technology": "XLK",
    "communication_services": "XLC",
    "industrials": "XLI",
    "materials": "XLB",
    "utilities": "XLU",
    "consumer_discretionary": "XLY",
    "health_care": "XLV",
    "financials": "XLF",
    "energy": "XLE",
    "consumer_staples": "XLP",
    "real_estate": "XLRE",
    "semiconductors": "SMH",
}

HOT_SECTOR_BASKETS: dict[str, tuple[str, ...]] = {
    "technology": (
        "NVDA",
        "MSFT",
        "AVGO",
        "AMD",
        "QCOM",
        "ORCL",
        "PANW",
        "SNPS",
        "KLAC",
        "LRCX",
        "TXN",
        "ADBE",
    ),
    "communication_services": (
        "META",
        "GOOGL",
        "GOOG",
        "NFLX",
        "TMUS",
        "CMCSA",
        "CHTR",
        "TTWO",
        "EA",
    ),
    "industrials": (
        "HON",
        "GE",
        "CSX",
        "ODFL",
        "PAYX",
        "CTAS",
        "ROP",
        "PCAR",
        "FAST",
        "CSGP",
    ),
    "materials": (
        "LIN",
        "APD",
        "SHW",
        "ECL",
        "FCX",
        "NEM",
    ),
    "utilities": (
        "NEE",
        "DUK",
        "SO",
        "AEP",
        "EXC",
        "XEL",
        "CEG",
    ),
    "consumer_discretionary": (
        "AMZN",
        "TSLA",
        "BKNG",
        "COST",
        "MELI",
        "ROST",
        "MAR",
        "SBUX",
        "ORLY",
        "PDD",
    ),
    "health_care": (
        "ISRG",
        "VRTX",
        "REGN",
        "DXCM",
        "IDXX",
        "GILD",
        "AMGN",
        "AZN",
        "GEHC",
        "INSM",
        "ALNY",
    ),
    "financials": (
        "PYPL",
        "SCHW",
        "IBKR",
        "VIRT",
        "COIN",
        "AXP",
        "KKR",
    ),
    "energy": (
        "FANG",
        "BKR",
        "HAL",
        "SLB",
        "COP",
        "EOG",
    ),
    "consumer_staples": (
        "PEP",
        "MDLZ",
        "KDP",
        "KHC",
        "MNST",
        "CCEP",
    ),
    "real_estate": (
        "CSGP",
        "AMT",
        "EQIX",
        "DLR",
        "PLD",
        "CCI",
    ),
    "semiconductors": (
        "NVDA",
        "AVGO",
        "AMD",
        "QCOM",
        "MU",
        "MRVL",
        "ARM",
        "KLAC",
        "LRCX",
        "SNPS",
        "CDNS",
        "NXPI",
        "ADI",
        "MCHP",
        "MPWR",
        "TXN",
        "INTC",
        "WDC",
        "STX",
    ),
}


@dataclass(frozen=True, slots=True)
class SectorOverlaySignal:
    sector: str
    proxy_ticker: str
    qqq_return_20d: float | None
    qqq_return_60d: float | None
    sector_return_20d: float | None
    sector_return_60d: float | None
    excess_20d: float | None
    excess_60d: float | None
    score: float | None
    selected: bool = False


@dataclass(frozen=True, slots=True)
class HotSectorOverlayResult:
    generated_at: str
    benchmark_ticker: str
    lookback_short: int
    lookback_long: int
    max_sectors: int
    per_sector_cap: int
    selected_sectors: list[str]
    selected_tickers: list[str]
    signals: list[SectorOverlaySignal]

    def as_payload(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "benchmark_ticker": self.benchmark_ticker,
            "lookback_short": self.lookback_short,
            "lookback_long": self.lookback_long,
            "max_sectors": self.max_sectors,
            "per_sector_cap": self.per_sector_cap,
            "selected_sectors": self.selected_sectors,
            "tickers": self.selected_tickers,
            "signals": [asdict(signal) for signal in self.signals],
        }


def _percent_return(bars: list[DailyBar], lookback: int) -> float | None:
    if len(bars) <= lookback:
        return None
    start = bars[-(lookback + 1)].close
    end = bars[-1].close
    if start <= 0:
        return None
    return (end / start - 1.0) * 100.0


def _sector_score(short_excess: float | None, long_excess: float | None) -> float | None:
    if short_excess is None and long_excess is None:
        return None
    if short_excess is None:
        return long_excess
    if long_excess is None:
        return short_excess
    return (0.65 * short_excess) + (0.35 * long_excess)


def _rank_signals(signals: Iterable[SectorOverlaySignal]) -> list[SectorOverlaySignal]:
    return sorted(
        signals,
        key=lambda signal: (
            signal.score is None,
            -(signal.score or float("-inf")),
            signal.sector,
        ),
    )


def _build_sector_signals(
    fetcher: MarketDataFetcher,
    *,
    benchmark_ticker: str = BENCHMARK_TICKER,
    lookback_short: int = DEFAULT_LOOKBACK_SHORT,
    lookback_long: int = DEFAULT_LOOKBACK_LONG,
) -> list[SectorOverlaySignal]:
    tickers = [benchmark_ticker, *SECTOR_PROXY_TICKERS.values()]
    fetch_result = fetcher.fetch(tickers)
    bars_by_ticker = fetch_result.bars_by_ticker
    benchmark_bars = bars_by_ticker.get(benchmark_ticker)
    if not benchmark_bars:
        raise ValueError(f"No benchmark bars returned for {benchmark_ticker}")

    qqq_return_20d = _percent_return(benchmark_bars, lookback_short)
    qqq_return_60d = _percent_return(benchmark_bars, lookback_long)

    signals: list[SectorOverlaySignal] = []
    for sector, proxy_ticker in SECTOR_PROXY_TICKERS.items():
        proxy_bars = bars_by_ticker.get(proxy_ticker)
        if not proxy_bars:
            continue
        sector_return_20d = _percent_return(proxy_bars, lookback_short)
        sector_return_60d = _percent_return(proxy_bars, lookback_long)
        excess_20d = None if qqq_return_20d is None or sector_return_20d is None else sector_return_20d - qqq_return_20d
        excess_60d = None if qqq_return_60d is None or sector_return_60d is None else sector_return_60d - qqq_return_60d
        signals.append(
            SectorOverlaySignal(
                sector=sector,
                proxy_ticker=proxy_ticker,
                qqq_return_20d=qqq_return_20d,
                qqq_return_60d=qqq_return_60d,
                sector_return_20d=sector_return_20d,
                sector_return_60d=sector_return_60d,
                excess_20d=excess_20d,
                excess_60d=excess_60d,
                score=_sector_score(excess_20d, excess_60d),
            )
        )
    return _rank_signals(signals)


def build_hot_sector_overlay(
    *,
    fetcher: MarketDataFetcher | None = None,
    benchmark_ticker: str = BENCHMARK_TICKER,
    max_sectors: int = DEFAULT_MAX_SECTORS,
    per_sector_cap: int = DEFAULT_PER_SECTOR_CAP,
    lookback_short: int = DEFAULT_LOOKBACK_SHORT,
    lookback_long: int = DEFAULT_LOOKBACK_LONG,
) -> HotSectorOverlayResult:
    resolved_fetcher = fetcher or YFinanceDailyBarFetcher(period="9mo")
    signals = _build_sector_signals(
        resolved_fetcher,
        benchmark_ticker=benchmark_ticker,
        lookback_short=lookback_short,
        lookback_long=lookback_long,
    )
    ranked = [signal for signal in signals if signal.score is not None]
    if not ranked:
        ranked = list(signals)
    selected_signals = ranked[:max(1, min(max_sectors, len(ranked)))]
    selected_sector_names = [signal.sector for signal in selected_signals]

    selected_tickers: list[str] = []
    seen: set[str] = set()
    for sector in selected_sector_names:
        for ticker in HOT_SECTOR_BASKETS.get(sector, ()):
            if ticker in seen:
                continue
            selected_tickers.append(ticker)
            seen.add(ticker)
            if len([item for item in selected_tickers if item in HOT_SECTOR_BASKETS.get(sector, ())]) >= per_sector_cap:
                break

    for signal in signals:
        if signal.sector in selected_sector_names:
            signal_index = selected_sector_names.index(signal.sector)
            selected_signals[signal_index] = SectorOverlaySignal(**{**asdict(signal), "selected": True})

    return HotSectorOverlayResult(
        generated_at=datetime.now(timezone.utc).isoformat(),
        benchmark_ticker=benchmark_ticker,
        lookback_short=lookback_short,
        lookback_long=lookback_long,
        max_sectors=max_sectors,
        per_sector_cap=per_sector_cap,
        selected_sectors=selected_sector_names,
        selected_tickers=selected_tickers,
        signals=selected_signals,
    )


def write_hot_sector_overlay(path: str | Path, result: HotSectorOverlayResult) -> Path:
    output_path = Path(path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result.as_payload(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path
