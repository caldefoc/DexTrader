import os
import tempfile
import unittest

from app.services.market_history import MarketHistory
from app.services.state_store import JsonStateStore


class MarketHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = JsonStateStore(path=os.path.join(self.tmp.name, "history.json"))
        self.history = MarketHistory(store=self.store)
        self.start = 1_700_000_000.0

    def tearDown(self):
        self.tmp.cleanup()

    def feed(self, prices, volume_per_minute=1000.0, symbol="VVV"):
        cumulative = 0.0
        for index, price in enumerate(prices):
            cumulative += volume_per_minute
            self.history.record_pair(
                symbol, price, cumulative, now=self.start + index * 60
            )

    def test_warmup_returns_none_instead_of_fake_values(self):
        self.feed([1.0, 1.1, 1.2])
        summary = self.history.summary("VVV")
        self.assertIsNone(summary["rsi"])
        self.assertIsNotNone(summary["vwap"])
        self.assertIsNone(summary["volume_ratio"])

    def test_rsi_vwap_and_volume_spike_after_history(self):
        prices = [1.0 + index * 0.01 for index in range(20)]
        self.feed(prices, volume_per_minute=1000.0)
        # Last five minutes trade 5x the baseline rate.
        cumulative = 20 * 1000.0
        for index in range(5):
            cumulative += 5000.0
            self.history.record_pair(
                "VVV", prices[-1], cumulative, now=self.start + (20 + index) * 60
            )

        summary = self.history.summary("VVV")
        self.assertIsNotNone(summary["rsi"])
        self.assertGreater(summary["rsi"], 90)
        self.assertIsNotNone(summary["vwap"])
        self.assertTrue(summary["volume_spike"])
        self.assertGreater(summary["volume_ratio"], 2)

    def test_persist_and_reload_roundtrip(self):
        import time

        self.start = time.time() - 3600
        self.feed([1.0 + index * 0.01 for index in range(16)])
        self.history.persist(force=True)

        reloaded = MarketHistory(store=self.store)
        self.assertEqual(len(reloaded.samples("VVV")), 16)
        self.assertIsNotNone(reloaded.summary("VVV")["rsi"])

    def test_samples_are_rate_limited(self):
        self.assertTrue(self.history.record_pair("VVV", 1.0, 1000, now=self.start))
        self.assertFalse(self.history.record_pair("VVV", 1.0, 1000, now=self.start + 10))


if __name__ == "__main__":
    unittest.main()
