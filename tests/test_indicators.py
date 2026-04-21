import math
import sys
from datetime import date, timedelta
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from screener.data.market_data import DailyBar
from screener.indicators.technicals import add_indicator_columns, bollinger_bands, distance_from_recent_low, rolling_mean, rsi, volume_ratio


class IndicatorTests(unittest.TestCase):
    def test_rolling_mean(self):
        values = [1, 2, 3, 4]
        self.assertEqual(rolling_mean(values, 2), [None, 1.5, 2.5, 3.5])

    def test_bollinger_bands_constant_series(self):
        bands = bollinger_bands([10.0] * 20)
        self.assertEqual(bands["middle"][-1], 10.0)
        self.assertEqual(bands["upper"][-1], 10.0)
        self.assertEqual(bands["lower"][-1], 10.0)

    def test_rsi_for_monotonic_gain_series(self):
        values = list(range(1, 25))
        result = rsi(values, 14)
        self.assertIsNone(result[12])
        self.assertEqual(result[-1], 100.0)

    def test_distance_from_recent_low(self):
        result = distance_from_recent_low([10, 9, 8, 8, 9], 3)
        self.assertEqual(result[:2], [None, None])
        self.assertAlmostEqual(result[-1], 12.5)

    def test_volume_ratio(self):
        values = [100.0] * 19 + [200.0]
        ratio = volume_ratio(values, 20)
        self.assertAlmostEqual(ratio[-1], 200.0 / 105.0)

    def test_add_indicator_columns(self):
        start = date(2026, 1, 1)
        bars = [
            DailyBar("TEST", start + timedelta(days=day), 10 + day, 11 + day, 9 + day, 10 + day, 10 + day, 1_000_000)
            for day in range(60)
        ]
        rows = add_indicator_columns(bars)
        self.assertEqual(len(rows), 60)
        self.assertEqual(rows[-1]["ticker"], "TEST")
        self.assertAlmostEqual(rows[-1]["sma_5"], 67.0)
        self.assertTrue(math.isfinite(rows[-1]["volume_ratio_20d"]))


if __name__ == "__main__":
    unittest.main()
