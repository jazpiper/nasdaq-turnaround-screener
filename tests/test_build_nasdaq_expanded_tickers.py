from __future__ import annotations

from pathlib import Path

from scripts.build_nasdaq_expanded_tickers import build_nasdaq_expanded_tickers, write_ticker_file


NASDAQ_LISTED_SAMPLE = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N
AAPLW|Apple Acquisition Corp. - Warrant|Q|N|N|100|N|N
QQQM|Invesco NASDAQ 100 ETF|G|N|N|100|Y|N
TEST|Test Company - Common Stock|Q|Y|N|100|N|N
BRK.B|Berkshire Hathaway Inc. Class B Common Stock|Q|N|N|100|N|N
ABC.U|ABC Corp Unit|Q|N|N|100|N|N
MSFT|Microsoft Corporation - Common Stock|Q|N|N|100|N|N
File Creation Time: 0521202621:00|||||||
"""


def test_build_nasdaq_expanded_tickers_filters_non_common_instruments() -> None:
    assert build_nasdaq_expanded_tickers(NASDAQ_LISTED_SAMPLE, limit=10) == ("AAPL", "BRK-B", "MSFT")


def test_build_nasdaq_expanded_tickers_respects_limit() -> None:
    assert build_nasdaq_expanded_tickers(NASDAQ_LISTED_SAMPLE, limit=2) == ("AAPL", "BRK-B")


def test_write_ticker_file_creates_parent_and_newline(tmp_path: Path) -> None:
    output = write_ticker_file(tmp_path / "config" / "expanded.txt", ("AAPL", "MSFT"))

    assert output.read_text(encoding="utf-8") == "AAPL\nMSFT\n"
