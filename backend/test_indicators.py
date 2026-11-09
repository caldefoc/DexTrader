import unittest

from app.services import indicators


class IndicatorTests(unittest.TestCase):
    def test_rsi_needs_enough_samples_and_returns_none_during_warmup(self):
        self.assertIsNone(indicators.rsi([1.0] * 14))
        self.assertIsNone(indicators.rsi([]))

    def test_rsi_saturates_on_monotonic_series(self):
        rising = [float(value) for value in range(1, 20)]
        falling = list(reversed(rising))
        self.assertEqual(indicators.rsi(rising), 100.0)
        self.assertEqual(indicators.rsi(falling), 0.0)

    def test_rsi_flat_series_is_neutral(self):
        self.assertEqual(indicators.rsi([2.0] * 20), 50.0)

    def test_vwap_weights_by_volume_and_ignores_missing_samples(self):
        self.assertAlmostEqual(
            indicators.vwap([1.0, 2.0, 3.0], [1.0, 1.0, 2.0]),
            2.25,
        )
        self.assertIsNone(indicators.vwap([1.0, 2.0], [0.0, 0.0]))
        self.assertIsNone(indicators.vwap([1.0, None], [None, 0.0]))

    def test_volume_ratio_and_spike_threshold(self):
        self.assertAlmostEqual(indicators.volume_ratio(600.0, 6000.0, 12), 1.2)
        self.assertAlmostEqual(indicators.volume_ratio(1200.0, 6000.0, 12), 2.4)
        self.assertTrue(indicators.is_volume_spike(2.4))
        self.assertFalse(indicators.is_volume_spike(1.9))
        self.assertIsNone(indicators.volume_ratio(None, 100.0))


if __name__ == "__main__":
    unittest.main()
