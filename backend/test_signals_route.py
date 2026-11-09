import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI

from app.api import routes_signals


class SignalsRoutingTests(unittest.IsolatedAsyncioTestCase):
    """The demo sits behind a proxy that strips /api, so a trailing-slash
    redirect would lose the prefix and hit the frontend instead."""

    async def asyncSetUp(self):
        app = FastAPI()
        app.include_router(routes_signals.router, prefix="/signals")
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        )
        self.addAsyncCleanup(self.client.aclose)

        async def empty_market():
            return []

        self.start_patch(patch.object(routes_signals, "DEEPSEEK_API_KEY", ""))
        self.start_patch(patch.object(routes_signals, "OPENAI_API_KEY", ""))
        self.start_patch(
            patch.object(routes_signals, "get_cached_market_data", empty_market)
        )

    def start_patch(self, patcher):
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    async def test_both_spellings_answer_without_redirect(self):
        for path in ("/signals?limit=200", "/signals/?limit=200"):
            with self.subTest(path=path):
                response = await self.client.get(path, follow_redirects=False)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), [])

    async def test_limit_is_still_validated(self):
        response = await self.client.get("/signals?limit=0")
        self.assertEqual(response.status_code, 422)
