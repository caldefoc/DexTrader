import os
import unittest
from unittest.mock import patch

import httpx

from app.services import coingecko, coinmarketcap


TOKEN_IDS = {
    "ENA": "ethena",
    "ICP": "internet-computer",
    "MORPHO": "morpho",
    "ETHFI": "ether-fi",
    "ZRO": "layerzero",
}
HTTPX_CLIENT = httpx.AsyncClient


class BaseTokenSupportTests(unittest.IsolatedAsyncioTestCase):
    def test_new_symbols_are_priority_market_assets(self):
        for symbol in TOKEN_IDS:
            with self.subTest(symbol=symbol):
                self.assertIn(symbol, coinmarketcap.PRIORITY_SYMBOLS)

    def test_new_symbols_use_verified_coingecko_ids(self):
        for symbol, coin_id in TOKEN_IDS.items():
            with self.subTest(symbol=symbol):
                self.assertEqual(coingecko.COINGECKO_SYMBOL_ID_MAP.get(symbol), coin_id)

    def test_base_url_uses_pro_endpoint_when_a_key_is_configured(self):
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("CMC_BASE_URL", None)
            self.assertEqual(
                coinmarketcap._resolve_base_url("test-key"),
                "https://pro-api.coinmarketcap.com",
            )
            self.assertEqual(
                coinmarketcap._resolve_base_url(None),
                "https://pro-api.coinmarketcap.com/trial-pro-api",
            )

    def test_base_url_override_wins_over_key(self):
        with patch.dict("os.environ", {"CMC_BASE_URL": "https://cmc.test/"}):
            self.assertEqual(
                coinmarketcap._resolve_base_url("test-key"), "https://cmc.test"
            )

    async def test_pricing_fallback_fetches_each_new_asset_by_id(self):
        requests = []

        def upstream(request):
            requests.append(request)
            return httpx.Response(200, json=[
                {"id": coin_id, "symbol": symbol.lower(), "current_price": 2.5,
                 "price_change_percentage_24h": 1.2, "total_volume": 2500000}
                for symbol, coin_id in TOKEN_IDS.items()
            ])

        with patch.object(coingecko.httpx, "AsyncClient", side_effect=lambda **kwargs: HTTPX_CLIENT(
            transport=httpx.MockTransport(upstream), **kwargs
        )):
            pairs = await coingecko.fetch_coingecko_pairs(list(TOKEN_IDS))
        self.assertEqual(len(requests), 1)
        self.assertEqual(set(requests[0].url.params["ids"].split(",")), set(TOKEN_IDS.values()))
        self.assertEqual({pair.base_symbol for pair in pairs}, set(TOKEN_IDS))
        self.assertTrue(all(pair.price == 2.5 and pair.volume_24h == 2500000 for pair in pairs))


if __name__ == "__main__":
    unittest.main()
