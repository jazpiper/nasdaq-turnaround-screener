from __future__ import annotations

import pytest

from screener.universe import parse_ticker_list


def test_parse_ticker_list_normalizes_deduplicates_and_preserves_order() -> None:
    tickers = parse_ticker_list("tsla, INFQ,pltr, tsla, brk.b, nvda")

    assert tickers == ("TSLA", "INFQ", "PLTR", "BRK-B", "NVDA")


def test_parse_ticker_list_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="At least one ticker"):
        parse_ticker_list(" , , ")
