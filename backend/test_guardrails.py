import unittest

from app.services.guardrails import GuardrailConfig, Guardrails


class GuardrailTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_700_000_000.0

    def test_daily_drawdown_halts_trading(self):
        rails = Guardrails()
        rails.begin_cycle(1000.0, now=self.now)
        rails.begin_cycle(949.0, now=self.now + 60)
        self.assertTrue(rails.halted)
        self.assertEqual(rails.halt_kind, "daily_drawdown")
        allowed, reason = rails.can_trade("VVV")
        self.assertFalse(allowed)
        self.assertIn("halted", reason.lower())

    def test_daily_breaker_resets_on_a_new_day(self):
        rails = Guardrails()
        rails.begin_cycle(1000.0, now=self.now)
        rails.begin_cycle(940.0, now=self.now + 60)
        self.assertTrue(rails.halted)
        rails.begin_cycle(940.0, now=self.now + 86400)
        self.assertFalse(rails.halted)
        self.assertEqual(rails.trades_today, 0)

    def test_manual_kill_switch_survives_the_day_rollover(self):
        rails = Guardrails()
        rails.halt("manual")
        rails.begin_cycle(1000.0, now=self.now + 86400)
        self.assertTrue(rails.halted)
        rails.resume()
        self.assertFalse(rails.halted)

    def test_daily_and_per_token_trade_limits(self):
        rails = Guardrails(config=GuardrailConfig(max_daily_trades=3, max_trades_per_token=2))
        rails.begin_cycle(1000.0, now=self.now)
        rails.record_trade("VVV")
        rails.record_trade("VVV")
        allowed, reason = rails.can_trade("VVV")
        self.assertFalse(allowed)
        self.assertIn("per-token", reason)
        self.assertTrue(rails.can_trade("AERO")[0])
        rails.record_trade("AERO")
        allowed, reason = rails.can_trade("TIBBIR")
        self.assertFalse(allowed)
        self.assertIn("Daily trade limit", reason)

    def test_serialisation_roundtrip(self):
        rails = Guardrails()
        rails.begin_cycle(1000.0, now=self.now)
        rails.record_trade("VVV")
        rails.halt("x")
        restored = Guardrails.from_dict(rails.to_dict())
        self.assertEqual(restored.trades_today, 1)
        self.assertTrue(restored.halted)
        self.assertEqual(restored.halt_reason, "x")


if __name__ == "__main__":
    unittest.main()
