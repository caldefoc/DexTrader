import asyncio
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.models.market import MarketSnapshot, TradingPair


TARGETS = {"ETH", "WETH", "VVV", "VIRTUAL", "AERO", "TIBBIR", "AVNT"}
REMOVED_DEFAULTS = {"FAI", "LUNA", "CLANKER", "BRETT"}
OTHER_DEFAULTS = {
    "USDC", "SHIB", "DEGEN", "TOSHI", "AIXBT", "ETHY", "ARB", "AAVE", "UNI", "LINK"
}


def isolated_controller_module():
    # Replace audit and trade reconstruction dependencies BEFORE the module's
    # global controller is constructed; never open live audit/trade files.
    replacements = {}
    for name, attributes in {
        "app.agents.audit_agent": {"AuditAgent": Mock},
        "app.services.portfolio": {"load_trades": Mock(return_value=[]), "get_user_holdings": Mock(return_value={})},
        "app.services.coinmarketcap": {"fetch_market_pairs": AsyncMock()},
        "app.agents.polling_agent": {"poll_once": AsyncMock()},
    }.items():
        module = ModuleType(name)
        module.__dict__.update(attributes)
        replacements[name] = module
    name = "app.agents._auto_trade_policy_test_controller"
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parent / "app/agents/controller.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, replacements):
        spec.loader.exec_module(module)
    return module


class AutoTradePolicyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.module = isolated_controller_module()
        self.controller = self.module.controller
        self.module.load_trades.assert_called_once_with()
        self.assertEqual(self.controller.position_states, {})

    def test_default_monitoring_preserves_other_assets_and_covers_every_target(self):
        defaults = self.controller.get_status().monitored_tokens
        self.assertEqual(set(defaults), TARGETS | OTHER_DEFAULTS)
        self.assertEqual(len(defaults), len(set(defaults)))
        self.assertFalse(REMOVED_DEFAULTS.intersection(defaults))

    async def one_simulated_cycle(self, symbols):
        snapshot = MarketSnapshot(pairs=[
            TradingPair(base_symbol=symbol, quote_symbol="USDC", price=2,
                        change_24h=-3, volume_24h=1_000_000)
            for symbol in symbols
        ])
        self.controller.set_user_holdings({"USDC": 1000, "FAI": 10})
        # Run only this isolated instance, with a mocked data feed and no task,
        # agent start/stop API, network, recording, or wall-clock sleep.
        self.controller.is_running = True
        with (
            patch.object(self.module, "poll_once", AsyncMock(return_value=snapshot)) as poll,
            patch.object(self.module, "asyncio", Mock(sleep=AsyncMock(side_effect=asyncio.CancelledError))),
            patch("builtins.print"),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await self.controller.run_loop()
        poll.assert_awaited_once()
        return self.controller.get_proposals()

    async def test_all_seven_targets_can_generate_pending_proposals_by_default(self):
        proposals = await self.one_simulated_cycle(TARGETS)
        self.assertEqual({p.token for p in proposals}, TARGETS)
        self.assertTrue(all(p.status == "pending" and p.amount > 0 for p in proposals))

    async def test_monitoring_is_editable_and_other_monitored_or_held_assets_remain_manual(self):
        manual = {"DEGEN", "TOSHI", "ENA", "ICP", "MORPHO", "ETHFI", "ZRO"} | REMOVED_DEFAULTS
        self.controller.monitored_tokens = sorted(manual - {"FAI"})
        proposals = await self.one_simulated_cycle(manual | {"NOT_MONITORED_OR_HELD"})
        self.assertEqual({p.token for p in proposals}, manual)
        self.assertTrue(all(p.status == "pending" for p in proposals))
        self.assertNotIn("AUTO_TRADE_TOKENS", self.controller.run_loop.__code__.co_varnames)


if __name__ == "__main__":
    unittest.main()
