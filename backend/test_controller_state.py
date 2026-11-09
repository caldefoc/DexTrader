import unittest
from unittest.mock import patch

from app.agents.controller import controller


class ControllerStateTests(unittest.TestCase):
    def setUp(self):
        self.original = (
            dict(controller.position_states),
            list(controller.proposals),
            controller.guardrails,
            controller._stored_state,
        )

    def tearDown(self):
        (
            controller.position_states,
            controller.proposals,
            controller.guardrails,
            controller._stored_state,
        ) = self.original

    def test_restoring_state_drops_stablecoin_positions(self):
        controller.position_states = {}
        controller._stored_state = {
            "positions": {
                "USDC": {"peak_price": 1.0},
                "VVV": {"peak_price": 9.0},
            },
            "proposals": [],
            "guardrails": {},
        }
        with patch.object(controller.audit_agent, "log"):
            controller._restore_agent_state()

        self.assertNotIn("USDC", controller.position_states)
        self.assertIn("VVV", controller.position_states)
        self.assertAlmostEqual(controller.position_states["VVV"]["peak_price"], 9.0)


if __name__ == "__main__":
    unittest.main()
