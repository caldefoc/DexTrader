import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import FastAPI

from app.api import routes_market
from app.services import base_tokens, coingecko, geckoterminal


HTTPX_CLIENT = httpx.AsyncClient

ADDR_A = "0x" + "aa" * 20
ADDR_B = "0x" + "bb" * 20
ADDR_C = "0x" + "cc" * 20
ADDR_D = "0x" + "dd" * 20
ADDR_E = "0x" + "ee" * 20
WETH = "0x4200000000000000000000000000000000000006"
USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
DAI = "0x50c5725949a6f0c72e6c4a641f24049a917db0cb"
MISSING = object()


def numbered_address(index):
    return f"0x{index:040x}"


def cg_coin(coin_id="base-coin", change=-2.5, **overrides):
    item = {
        "id": coin_id,
        "name": "Base Coin",
        "symbol": "base",
        "price_change_percentage_24h": change,
    }
    item.update(overrides)
    return item


def gt_token(
    address,
    symbol="tok",
    name="Token",
    price="1.5",
    fdv="2000000",
    volume="50000",
    cg_id="base-coin",
):
    return {
        "id": f"base_{address}",
        "type": "token",
        "attributes": {
            "address": address,
            "name": name,
            "symbol": symbol,
            "price_usd": price,
            "fdv_usd": fdv,
            "volume_usd": {"h24": volume},
            "coingecko_coin_id": cg_id,
        },
    }


def gt_pool(base, quote, h24):
    volume_usd = {} if h24 is MISSING else {"h24": str(h24)}
    return {
        "id": "base_0xpool",
        "type": "pool",
        "attributes": {"volume_usd": volume_usd},
        "relationships": {
            "base_token": {"data": {"id": f"base_{base}"}},
            "quote_token": {"data": {"id": f"base_{quote}"}},
        },
    }


class BaseMarketTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Do not import app.main: its startup performs unrelated application work.
        app = FastAPI()
        app.include_router(routes_market.router, prefix="/market")
        self.client = HTTPX_CLIENT(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        )
        self.addAsyncCleanup(self.client.aclose)

        self.requests = []
        self.candidates = [cg_coin()]
        self.changes_payload = []
        self.detail_payloads = {}
        self.platform_list = []
        self.ds_pairs = []
        self.gt_tokens = {ADDR_A: gt_token(ADDR_A)}
        self.gt_pools = []
        self.forced_pool_statuses = []
        self.fail_hosts = set()
        self.timeout_hosts = set()
        self.raw_content = {}
        self.upstream_started = asyncio.Event()
        self.upstream_release = asyncio.Event()
        self.upstream_release.set()
        self.clock = 1000.0

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.address_cache_path = Path(tmp.name) / "cache.json"

        for name, value in (
            ("_base_tokens_cache", {}),
            ("_base_tokens_timestamp", {}),
            ("_base_tokens_lock", asyncio.Lock()),
        ):
            self.start_patch(patch.object(routes_market, name, value))
        self.start_patch(patch.object(coingecko, "COINGECKO_API_KEY", "test-demo-key"))
        self.start_patch(
            patch.object(coingecko, "COINGECKO_BASE_URL", "https://coingecko.test/api/v3")
        )
        self.start_patch(
            patch.object(
                geckoterminal,
                "GECKOTERMINAL_BASE_URL",
                "https://geckoterminal.test/api/v2",
            )
        )
        self.start_patch(patch.object(geckoterminal, "POOL_PAGE_DELAY", 0))
        self.start_patch(patch.object(geckoterminal, "RATE_LIMIT_RETRY_DELAY", 0))
        self.start_patch(
            patch.object(base_tokens, "ADDRESS_CACHE_PATH", self.address_cache_path)
        )
        self.platform_map_path = Path(tmp.name) / "platform_map.json"
        self.start_patch(
            patch.object(base_tokens, "PLATFORM_MAP_PATH", self.platform_map_path)
        )
        self.start_patch(patch.object(base_tokens, "_platform_map", None))
        self.start_patch(patch.object(base_tokens, "_platform_map_timestamp", 0.0))
        self.start_patch(patch.object(base_tokens, "_address_cache", {"base-coin": ADDR_A}))
        self.address_cache = base_tokens._address_cache
        # Replace only this route's clock, not asyncio's global monotonic clock.
        self.start_patch(
            patch.object(routes_market, "time", monotonic=lambda: self.clock)
        )
        self.start_patch(
            patch.object(
                httpx,
                "AsyncClient",
                side_effect=lambda **kwargs: HTTPX_CLIENT(
                    transport=httpx.MockTransport(self.upstream), **kwargs
                ),
            )
        )

    def start_patch(self, patcher):
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    async def upstream(self, request):
        self.requests.append(request)
        self.upstream_started.set()
        await self.upstream_release.wait()
        host = request.url.host
        if host in self.timeout_hosts:
            raise httpx.ReadTimeout("private provider details", request=request)
        if host in self.fail_hosts:
            return self.respond(
                {"error": "private provider details test-demo-key"}, status=500
            )
        if host in self.raw_content:
            return httpx.Response(
                200,
                content=self.raw_content[host],
                headers={"Content-Type": "application/json"},
            )
        if host == "coingecko.test":
            return self.handle_coingecko(request)
        if host == "geckoterminal.test":
            return self.handle_geckoterminal(request)
        if host == "api.dexscreener.com":
            return self.handle_dexscreener(request)
        raise AssertionError(f"Unexpected host {host}")

    def handle_dexscreener(self, request):
        path = request.url.path
        if not path.startswith("/tokens/v1/base/"):
            raise AssertionError(f"Unexpected DexScreener path {path}")
        requested = set(path.rsplit("/", 1)[1].split(","))
        data = [
            pair
            for pair in self.ds_pairs
            if str(pair["baseToken"]["address"]).lower() in requested
        ]
        return self.respond(data)

    def respond(self, payload, status=200):
        return httpx.Response(
            status,
            content=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )

    def handle_coingecko(self, request):
        path = request.url.path
        if path == "/api/v3/coins/markets":
            if "ids" in request.url.params:
                return self.respond(self.changes_payload)
            return self.respond(self.candidates)
        if path == "/api/v3/coins/list":
            return self.respond(self.platform_list)
        if path.startswith("/api/v3/coins/"):
            coin_id = path.rsplit("/", 1)[1]
            payload = self.detail_payloads.get(coin_id, {"id": coin_id, "platforms": {}})
            return self.respond(payload)
        raise AssertionError(f"Unexpected CoinGecko path {path}")

    def handle_geckoterminal(self, request):
        path = request.url.path
        if path == "/api/v2/networks/base/pools":
            if self.forced_pool_statuses:
                return self.respond(
                    {"error": "rate limited"}, status=self.forced_pool_statuses.pop(0)
                )
            page = int(request.url.params.get("page", "1"))
            start = (page - 1) * 20
            return self.respond({"data": self.gt_pools[start : start + 20]})
        if path.startswith("/api/v2/networks/base/tokens/multi/"):
            segment = path.rsplit("/", 1)[1]
            data, seen = [], set()
            for address in segment.split(","):
                key = address.lower()
                if key in self.gt_tokens and key not in seen:
                    seen.add(key)
                    data.append(self.gt_tokens[key])
            return self.respond({"data": data})
        raise AssertionError(f"Unexpected GeckoTerminal path {path}")

    def host_requests(self, host):
        return [r for r in self.requests if r.url.host == host]

    def path_requests(self, host, prefix):
        return [r for r in self.host_requests(host) if r.url.path.startswith(prefix)]

    async def test_cap_ranking_returns_base_native_metrics(self):
        response = await self.client.get("/market/base-tokens")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "tokens": [
                    {
                        "id": "base-coin",
                        "name": "Token",
                        "symbol": "TOK",
                        "price": 1.5,
                        "change_24h": -2.5,
                        "volume_24h": 50000.0,
                        "market_cap": 2000000.0,
                    }
                ]
            },
        )
        cg = self.host_requests("coingecko.test")
        gt = self.host_requests("geckoterminal.test")
        self.assertEqual(len(cg), 1)
        self.assertEqual(
            str(cg[0].url).split("?")[0], "https://coingecko.test/api/v3/coins/markets"
        )
        self.assertEqual(
            dict(cg[0].url.params),
            {
                "vs_currency": "usd",
                "category": "base-ecosystem",
                "order": "market_cap_desc",
                "per_page": "100",
                "page": "1",
                "sparkline": "false",
            },
        )
        self.assertEqual(cg[0].headers["Accept"], "application/json")
        self.assertEqual(cg[0].headers["x-cg-demo-api-key"], "test-demo-key")
        self.assertNotIn("Authorization", cg[0].headers)
        self.assertNotIn("test-demo-key", str(cg[0].url))
        self.assertEqual(len(gt), 1)
        self.assertEqual(
            str(gt[0].url),
            f"https://geckoterminal.test/api/v2/networks/base/tokens/multi/{ADDR_A}",
        )
        self.assertNotIn("x-cg-demo-api-key", gt[0].headers)
        self.assertNotIn("test-demo-key", str(gt[0].url))
        self.assertNotIn("test-demo-key", response.text)

    async def test_no_demo_key_header_when_unconfigured(self):
        with patch.object(coingecko, "COINGECKO_API_KEY", ""):
            response = await self.client.get("/market/base-tokens")
        self.assertEqual(response.status_code, 200)
        cg = self.host_requests("coingecko.test")
        self.assertNotIn("x-cg-demo-api-key", cg[0].headers)

    async def test_cap_ranking_ranks_by_base_fdv_not_global_cap(self):
        # CoinGecko lists the global-cap leader first; Base FDV reverses the order.
        self.candidates = [cg_coin("global-leader"), cg_coin("base-leader")]
        self.address_cache.update({"global-leader": ADDR_B, "base-leader": ADDR_C})
        self.gt_tokens = {
            ADDR_B: gt_token(ADDR_B, symbol="big", fdv="5000000", cg_id="global-leader"),
            ADDR_C: gt_token(ADDR_C, symbol="small", fdv="9000000", cg_id="base-leader"),
        }
        response = await self.client.get("/market/base-tokens")
        self.assertEqual(response.status_code, 200)
        tokens = response.json()["tokens"]
        self.assertEqual([t["id"] for t in tokens], ["base-leader", "global-leader"])
        self.assertEqual([t["market_cap"] for t in tokens], [9000000.0, 5000000.0])

    async def test_cap_ranking_skips_tokens_without_base_presence(self):
        self.candidates = [
            cg_coin("no-base-address"),
            cg_coin("gt-unknown"),
            cg_coin("zero-fdv"),
            cg_coin("negative-fdv"),
            cg_coin("bad-price"),
            cg_coin(),
        ]
        self.address_cache.update(
            {
                "no-base-address": None,
                "gt-unknown": ADDR_B,
                "zero-fdv": ADDR_C,
                "negative-fdv": ADDR_D,
                "bad-price": ADDR_E,
            }
        )
        self.gt_tokens = {
            ADDR_C: gt_token(ADDR_C, fdv="0", cg_id="zero-fdv"),
            ADDR_D: gt_token(ADDR_D, fdv="-5", cg_id="negative-fdv"),
            ADDR_E: gt_token(ADDR_E, price="bad", cg_id="bad-price"),
            ADDR_A: gt_token(ADDR_A),
        }
        response = await self.client.get("/market/base-tokens")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([t["id"] for t in response.json()["tokens"]], ["base-coin"])

    async def test_cap_ranking_dedupes_tokens_sharing_an_address(self):
        self.candidates = [cg_coin("first"), cg_coin("second")]
        self.address_cache.update({"first": ADDR_A, "second": ADDR_A})
        response = await self.client.get("/market/base-tokens")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([t["id"] for t in response.json()["tokens"]], ["first"])

    async def test_cap_ranking_top_50_and_stable_ties(self):
        count = 55
        self.candidates = [cg_coin(f"coin-{i}") for i in range(1, count + 1)]
        self.gt_tokens = {}
        for i in range(1, count + 1):
            address = numbered_address(i)
            self.address_cache[f"coin-{i}"] = address
            # coin-55 ties coin-1 so stable ordering is observable.
            fdv = 99 if i == count else 100 - i
            self.gt_tokens[address] = gt_token(address, fdv=str(fdv), cg_id=f"coin-{i}")
        response = await self.client.get("/market/base-tokens")
        self.assertEqual(response.status_code, 200)
        tokens = response.json()["tokens"]
        self.assertEqual(len(tokens), 50)
        self.assertEqual(
            [t["id"] for t in tokens],
            ["coin-1", "coin-55"] + [f"coin-{i}" for i in range(2, 50)],
        )
        self.assertEqual(len({t["id"] for t in tokens}), 50)
        # 55 addresses resolve in batches of at most 30.
        multi = self.path_requests(
            "geckoterminal.test", "/api/v2/networks/base/tokens/multi/"
        )
        self.assertEqual(len(multi), 2)
        batch_sizes = sorted(
            len(str(r.url).rsplit("/", 1)[1].split(",")) for r in multi
        )
        self.assertEqual(batch_sizes, [25, 30])

    async def test_address_resolution_uses_detail_endpoint_once_then_cache(self):
        self.address_cache.clear()
        self.detail_payloads["base-coin"] = {
            "id": "base-coin",
            "platforms": {"base": ADDR_A.replace("aa", "AA"), "ethereum": "0x" + "00" * 20},
        }
        response = await self.client.get("/market/base-tokens")
        self.assertEqual(response.status_code, 200)
        detail = self.path_requests("coingecko.test", "/api/v3/coins/base-coin")
        self.assertEqual(len(detail), 1)
        self.assertEqual(
            dict(detail[0].url.params),
            {
                "localization": "false",
                "tickers": "false",
                "market_data": "false",
                "community_data": "false",
                "developer_data": "false",
                "sparkline": "false",
            },
        )
        self.assertEqual(self.address_cache["base-coin"], ADDR_A)
        self.clock += 300
        again = await self.client.get("/market/base-tokens")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(
            len(self.path_requests("coingecko.test", "/api/v3/coins/base-coin")), 1
        )

    async def test_address_resolution_caches_missing_base_address(self):
        self.candidates = [cg_coin("no-base"), cg_coin()]
        response = await self.client.get("/market/base-tokens")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([t["id"] for t in response.json()["tokens"]], ["base-coin"])
        self.assertIsNone(self.address_cache["no-base"])
        self.clock += 300
        again = await self.client.get("/market/base-tokens")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(
            len(self.path_requests("coingecko.test", "/api/v3/coins/no-base")), 1
        )

    async def test_address_cache_persisted_and_reloaded_from_disk(self):
        self.address_cache.clear()
        self.detail_payloads["base-coin"] = {
            "id": "base-coin",
            "platforms": {"base": ADDR_A},
        }
        response = await self.client.get("/market/base-tokens")
        self.assertEqual(response.status_code, 200)
        persisted = json.loads(self.address_cache_path.read_text())
        self.assertEqual(persisted["addresses"], {"base-coin": ADDR_A})

        # Simulate a restart: drop the in-memory cache and the route cache.
        base_tokens._address_cache = None
        routes_market._base_tokens_cache.clear()
        routes_market._base_tokens_timestamp.clear()
        again = await self.client.get("/market/base-tokens")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json(), response.json())
        self.assertEqual(
            len(self.path_requests("coingecko.test", "/api/v3/coins/base-coin")), 1
        )

    async def test_bulk_platform_map_resolves_candidates_in_one_call(self):
        self.address_cache.clear()
        self.platform_list = [
            {"id": "base-coin", "symbol": "base", "name": "Base Coin",
             "platforms": {"base": ADDR_A.replace("aa", "AA"), "ethereum": "0x" + "00" * 20}},
        ]
        response = await self.client.get("/market/base-tokens")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([t["id"] for t in response.json()["tokens"]], ["base-coin"])
        self.assertEqual(len(self.path_requests("coingecko.test", "/api/v3/coins/list")), 1)
        # No per-coin detail call is needed when the catalogue is available.
        self.assertEqual(
            len([r for r in self.host_requests("coingecko.test")
                 if r.url.path.startswith("/api/v3/coins/")
                 and r.url.path != "/api/v3/coins/markets"
                 and r.url.path != "/api/v3/coins/list"]),
            0,
        )
        self.assertEqual(self.address_cache["base-coin"], ADDR_A)
        self.assertTrue(self.platform_map_path.exists())

    async def test_platform_map_failure_falls_back_to_detail_calls(self):
        self.address_cache.clear()
        self.platform_list = {"error": "rate limited"}  # malformed catalogue
        self.detail_payloads["base-coin"] = {
            "id": "base-coin",
            "platforms": {"base": ADDR_A},
        }
        response = await self.client.get("/market/base-tokens")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.path_requests("coingecko.test", "/api/v3/coins/base-coin")), 1)
        self.assertEqual(self.address_cache["base-coin"], ADDR_A)

    async def test_dexscreener_fallback_supplies_metrics_when_geckoterminal_fails(self):
        self.fail_hosts.add("geckoterminal.test")
        self.ds_pairs = [
            {
                "baseToken": {"address": ADDR_A, "name": "Dex Token", "symbol": "dex"},
                "priceUsd": "3.5",
                "fdv": "9000000",
                "volume": {"h24": 1234.5},
                "liquidity": {"usd": 50000},
            }
        ]
        response = await self.client.get("/market/base-tokens")
        self.assertEqual(response.status_code, 200)
        token = response.json()["tokens"][0]
        self.assertEqual(token["id"], "base-coin")
        self.assertEqual(token["symbol"], "DEX")
        self.assertEqual(token["price"], 3.5)
        self.assertEqual(token["market_cap"], 9000000.0)
        self.assertEqual(token["volume_24h"], 1234.5)

    async def test_rate_limited_refresh_serves_previous_snapshot(self):
        first = await self.client.get("/market/base-tokens")
        self.assertEqual(first.status_code, 200)
        snapshot = routes_market._base_tokens_cache["market_cap"]
        self.clock += 300
        request = httpx.Request("GET", "https://coingecko.test/api/v3/coins/markets")
        rate_limited = httpx.HTTPStatusError(
            "429 rate limited",
            request=request,
            response=httpx.Response(429, request=request),
        )
        with patch.object(routes_market, "fetch_base_tokens", side_effect=rate_limited):
            second = await self.client.get("/market/base-tokens")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json(), first.json())
        self.assertIs(routes_market._base_tokens_cache["market_cap"], snapshot)

    async def test_pool_rate_limit_is_retried_once(self):
        self.gt_pools = [gt_pool(ADDR_A, WETH, 100)]
        self.forced_pool_statuses = [429]
        response = await self.client.get("/market/base-tokens?sort_by=volume_24h")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [t["id"] for t in response.json()["tokens"]], ["base-coin"]
        )
        pools = self.path_requests("geckoterminal.test", "/api/v2/networks/base/pools")
        self.assertEqual(len(pools), 2)

    async def test_persistent_pool_rate_limit_falls_back_to_candidate_ranking(self):
        self.gt_pools = [gt_pool(ADDR_A, WETH, 100)]
        self.forced_pool_statuses = [429, 429]
        response = await self.client.get("/market/base-tokens?sort_by=volume_24h")
        # The pool endpoint is exhausted, but the candidate pool can still
        # produce a volume ranking, so the tab stays populated.
        self.assertEqual(response.status_code, 200)
        self.assertEqual([t["id"] for t in response.json()["tokens"]], ["base-coin"])
        pools = self.path_requests("geckoterminal.test", "/api/v2/networks/base/pools")
        self.assertEqual(len(pools), 2)

    async def test_slow_pool_walk_falls_back_within_budget(self):
        self.gt_pools = [gt_pool(ADDR_A, WETH, 100)]
        with patch.object(base_tokens, "VOLUME_POOL_BUDGET", 0.0):
            response = await self.client.get("/market/base-tokens?sort_by=volume_24h")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([t["id"] for t in response.json()["tokens"]], ["base-coin"])

    async def test_volume_ranking_attributes_volume_to_non_quote_side(self):
        self.gt_pools = [
            gt_pool(ADDR_A, WETH, 100),
            gt_pool(WETH, USDC, 999999),  # quote-vs-quote pools are skipped
            gt_pool(USDC, ADDR_B, 50),
            gt_pool(ADDR_C, DAI, 10),
            gt_pool(ADDR_A, USDC, 5),
        ]
        self.gt_tokens = {
            ADDR_A: gt_token(ADDR_A, symbol="aaa", cg_id="tok-a"),
            ADDR_B: gt_token(ADDR_B, symbol="bbb", cg_id="tok-b"),
            ADDR_C: gt_token(ADDR_C, symbol="ccc", cg_id=None),
        }
        self.changes_payload = [
            {"id": "tok-a", "price_change_percentage_24h": 1.5},
            {"id": "tok-b", "price_change_percentage_24h": None},
        ]
        response = await self.client.get("/market/base-tokens?sort_by=volume_24h")
        self.assertEqual(response.status_code, 200)
        tokens = response.json()["tokens"]
        self.assertEqual(
            [t["id"] for t in tokens], ["tok-a", "tok-b", f"base-{ADDR_C}"]
        )
        self.assertEqual([t["volume_24h"] for t in tokens], [105.0, 50.0, 10.0])
        self.assertEqual([t["market_cap"] for t in tokens], [2000000.0] * 3)
        self.assertEqual(tokens[0]["change_24h"], 1.5)
        self.assertIsNone(tokens[1]["change_24h"])
        self.assertIsNone(tokens[2]["change_24h"])

        pools = self.path_requests("geckoterminal.test", "/api/v2/networks/base/pools")
        self.assertEqual(len(pools), 1)  # short page ends pagination early
        self.assertEqual(
            dict(pools[0].url.params), {"sort": "h24_volume_usd_desc", "page": "1"}
        )
        changes = self.host_requests("coingecko.test")
        self.assertEqual(len(changes), 1)
        self.assertEqual(
            set(changes[0].url.params["ids"].split(",")), {"tok-a", "tok-b"}
        )
        self.assertEqual(changes[0].headers["x-cg-demo-api-key"], "test-demo-key")

    async def test_volume_ranking_survives_change_lookup_failure(self):
        self.gt_pools = [gt_pool(ADDR_A, WETH, 100)]
        self.fail_hosts.add("coingecko.test")
        response = await self.client.get("/market/base-tokens?sort_by=volume_24h")
        self.assertEqual(response.status_code, 200)
        tokens = response.json()["tokens"]
        self.assertEqual([t["id"] for t in tokens], ["base-coin"])
        self.assertIsNone(tokens[0]["change_24h"])
        self.assertEqual(tokens[0]["volume_24h"], 100.0)

    async def test_volume_ranking_top_50(self):
        count = 60
        self.gt_pools = [
            gt_pool(numbered_address(i), WETH, 1000 - i) for i in range(1, count + 1)
        ]
        self.gt_tokens = {
            numbered_address(i): gt_token(
                numbered_address(i), symbol=f"t{i}", cg_id=f"vol-{i}"
            )
            for i in range(1, count + 1)
        }
        response = await self.client.get("/market/base-tokens?sort_by=volume_24h")
        self.assertEqual(response.status_code, 200)
        tokens = response.json()["tokens"]
        self.assertEqual(len(tokens), 50)
        self.assertEqual([t["id"] for t in tokens], [f"vol-{i}" for i in range(1, 51)])
        self.assertEqual(
            [t["volume_24h"] for t in tokens], [float(1000 - i) for i in range(1, 51)]
        )
        pools = self.path_requests("geckoterminal.test", "/api/v2/networks/base/pools")
        # 60 pools fill pages 1-3 exactly; the empty page 4 ends pagination.
        self.assertEqual([r.url.params["page"] for r in pools], ["1", "2", "3", "4"])

    async def test_volume_ranking_skips_tokens_geckoterminal_cannot_price(self):
        self.gt_pools = [gt_pool(ADDR_A, WETH, 100), gt_pool(ADDR_B, WETH, 50)]
        self.gt_tokens = {
            ADDR_A: gt_token(ADDR_A, price=None, cg_id="bad-price"),
            ADDR_B: gt_token(ADDR_B, cg_id="tok-b"),
        }
        response = await self.client.get("/market/base-tokens?sort_by=volume_24h")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([t["id"] for t in response.json()["tokens"]], ["tok-b"])

    async def assert_failure_is_not_cached(self, sort_by="market_cap"):
        before = len(self.requests)
        for _ in range(2):
            response = await self.client.get(
                "/market/base-tokens", params={"sort_by": sort_by}
            )
            self.assertEqual(response.status_code, 502)
            self.assertEqual(
                response.json(), {"detail": "Unable to fetch Base token market data"}
            )
            self.assertNotIn("private", response.text)
            self.assertNotIn("test-demo-key", response.text)
        self.assertGreater(len(self.requests), before)
        self.assertNotIn(sort_by, routes_market._base_tokens_cache)

    async def test_provider_errors_are_safe_502_and_not_cached(self):
        # Candidate fetch (CoinGecko) fails for the cap ranking.
        self.fail_hosts.add("coingecko.test")
        await self.assert_failure_is_not_cached("market_cap")
        self.fail_hosts.clear()
        # Metrics/pool fetch fails for both rankings; DexScreener is empty too,
        # so there is no provider left to fall back to.
        self.fail_hosts.add("geckoterminal.test")
        self.fail_hosts.add("api.dexscreener.com")
        await self.assert_failure_is_not_cached("market_cap")
        await self.assert_failure_is_not_cached("volume_24h")
        self.fail_hosts.clear()
        response = await self.client.get("/market/base-tokens")
        self.assertEqual(response.status_code, 200)

    async def test_timeout_is_safe_502_and_not_cached(self):
        self.timeout_hosts.add("geckoterminal.test")
        await self.assert_failure_is_not_cached("market_cap")
        self.timeout_hosts.clear()
        self.timeout_hosts.add("coingecko.test")
        await self.assert_failure_is_not_cached("market_cap")

    async def test_malformed_payloads_are_safe_502_and_not_cached(self):
        for payload in (
            {"error": "private provider details"},
            None,
            "wrong shape",
            [None],
            [cg_coin(), []],
            [cg_coin(id=None)],
            [cg_coin(id="")],
            [cg_coin(name=123)],
            [cg_coin(symbol=" ")],
            [{}],
            [],
        ):
            with self.subTest(payload=payload):
                self.candidates = payload
                await self.assert_failure_is_not_cached("market_cap")
        self.candidates = [cg_coin()]
        self.raw_content["coingecko.test"] = "not JSON: private provider details"
        await self.assert_failure_is_not_cached("market_cap")
        del self.raw_content["coingecko.test"]

        # Malformed GeckoTerminal token metrics (cap ranking).
        for content in ('{"data": {}}', '{"data": []}', '{"data": [null]}'):
            with self.subTest(content=content):
                self.raw_content["geckoterminal.test"] = content
                await self.assert_failure_is_not_cached("market_cap")
        del self.raw_content["geckoterminal.test"]

        # Malformed address-detail payload while resolving a cache miss.
        self.address_cache.clear()
        self.detail_payloads["base-coin"] = "not-a-dict"
        await self.assert_failure_is_not_cached("market_cap")
        del self.detail_payloads["base-coin"]
        self.address_cache["base-coin"] = ADDR_A

        # Malformed GeckoTerminal pools (volume ranking).
        for pools in (
            [None],
            [{"attributes": {}}],
            [gt_pool(ADDR_A, WETH, float("nan"))],
            [gt_pool(ADDR_A, WETH, -1)],
            [gt_pool(ADDR_A, WETH, MISSING)],
        ):
            with self.subTest(pools=pools):
                self.gt_pools = pools
                # Without candidates there is no fallback ranking either.
                self.candidates = []
                await self.assert_failure_is_not_cached("volume_24h")
        self.candidates = [cg_coin()]

    async def test_subsequent_requests_use_separate_cache_without_refresh_bypass(self):
        original_cache = [object()]
        with (
            patch.object(routes_market, "_market_data_cache", original_cache),
            patch.object(routes_market, "_cache_timestamp", 42.0),
            patch.object(routes_market, "_cache_initialized", True),
        ):
            first = await self.client.get("/market/base-tokens")
            self.assertEqual(first.status_code, 200)
            self.gt_tokens[ADDR_A] = gt_token(ADDR_A, name="Changed")
            self.clock += 299
            second = await self.client.get("/market/base-tokens?refresh=true")
            self.assertEqual(second.status_code, 200)
            self.assertEqual(second.json(), first.json())
            self.assertEqual(len(self.host_requests("coingecko.test")), 1)
            self.assertIs(routes_market._market_data_cache, original_cache)
            self.assertEqual(routes_market._cache_timestamp, 42.0)
            self.assertTrue(routes_market._cache_initialized)

    async def test_expired_cache_refetches_after_five_minutes(self):
        first = await self.client.get("/market/base-tokens")
        self.assertEqual(first.status_code, 200)
        self.clock += 300
        self.candidates = [cg_coin("new-coin")]
        self.address_cache["new-coin"] = ADDR_B
        self.gt_tokens = {ADDR_B: gt_token(ADDR_B, cg_id="new-coin")}
        second = await self.client.get("/market/base-tokens")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["tokens"][0]["id"], "new-coin")
        self.assertEqual(
            len(self.path_requests("coingecko.test", "/api/v3/coins/markets")), 2
        )

    async def test_expired_cache_failure_does_not_extend_or_replace_success(self):
        first = await self.client.get("/market/base-tokens")
        self.assertEqual(first.status_code, 200)
        snapshot = routes_market._base_tokens_cache["market_cap"]
        timestamp = routes_market._base_tokens_timestamp["market_cap"]
        self.clock += 300
        self.fail_hosts.add("geckoterminal.test")
        for _ in range(2):
            response = await self.client.get("/market/base-tokens")
            self.assertEqual(response.status_code, 502)
        self.assertIs(routes_market._base_tokens_cache["market_cap"], snapshot)
        self.assertEqual(routes_market._base_tokens_timestamp["market_cap"], timestamp)
        self.fail_hosts.clear()
        self.gt_tokens[ADDR_A] = gt_token(ADDR_A, name="Recovered")
        recovered = await self.client.get("/market/base-tokens")
        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(recovered.json()["tokens"][0]["name"], "Recovered")

    async def test_concurrent_requests_share_one_fetch_and_cache_completion_time(self):
        # Fail immediately on a missing route instead of waiting for the provider.
        self.assertTrue(any(r.path == "/market/base-tokens" for r in self.client._transport.app.routes))
        self.upstream_release.clear()
        tasks = [asyncio.create_task(self.client.get("/market/base-tokens")) for _ in range(8)]
        try:
            await asyncio.wait_for(self.upstream_started.wait(), timeout=2)
            self.assertEqual(len(self.requests), 1)
            self.clock += 10
            self.upstream_release.set()
            responses = await asyncio.wait_for(asyncio.gather(*tasks), timeout=2)
        finally:
            self.upstream_release.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        self.assertTrue(all(response.status_code == 200 for response in responses))
        self.assertTrue(all(response.json() == responses[0].json() for response in responses))
        self.assertEqual(len(self.host_requests("coingecko.test")), 1)
        self.assertEqual(len(self.host_requests("geckoterminal.test")), 1)
        self.clock += 299
        cached = await self.client.get("/market/base-tokens")
        self.assertEqual(cached.status_code, 200)
        self.assertEqual(len(self.requests), 2)

    async def test_invalid_sort_is_422_without_provider_call(self):
        for value in ("", "volume", "volume_desc", "market_cap_desc", "MARKET_CAP", "null"):
            with self.subTest(sort_by=value):
                response = await self.client.get(
                    "/market/base-tokens", params={"sort_by": value}
                )
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["detail"][0]["loc"], ["query", "sort_by"])
        self.assertEqual(self.requests, [])

    async def test_volume_fetch_is_not_served_from_cap_cache(self):
        cap = await self.client.get("/market/base-tokens?sort_by=market_cap")
        self.assertEqual(cap.status_code, 200)
        self.gt_pools = [gt_pool(ADDR_B, WETH, 900)]
        self.gt_tokens[ADDR_B] = gt_token(ADDR_B, cg_id="volume-only")
        volume = await self.client.get("/market/base-tokens?sort_by=volume_24h")
        self.assertEqual(volume.status_code, 200)
        self.assertEqual([t["id"] for t in volume.json()["tokens"]], ["volume-only"])
        self.assertNotEqual(volume.json(), cap.json())
        cached_cap = await self.client.get("/market/base-tokens?sort_by=market_cap")
        self.assertEqual(cached_cap.json(), cap.json())

    async def test_rank_caches_expire_independently_after_five_minutes(self):
        cap = await self.client.get("/market/base-tokens")
        self.assertEqual(cap.status_code, 200)
        self.clock += 100
        self.gt_pools = [gt_pool(ADDR_B, WETH, 900)]
        self.gt_tokens[ADDR_B] = gt_token(ADDR_B, cg_id="volume-list")
        volume = await self.client.get("/market/base-tokens?sort_by=volume_24h")
        self.assertEqual(volume.status_code, 200)
        self.assertEqual(volume.json()["tokens"][0]["id"], "volume-list")
        self.clock += 199
        for sort_by, expected in (("market_cap", cap), ("volume_24h", volume)):
            cached = await self.client.get(
                "/market/base-tokens", params={"sort_by": sort_by, "refresh": "true"}
            )
            self.assertEqual(cached.json(), expected.json())
        cg_markets = len(self.path_requests("coingecko.test", "/api/v3/coins/markets"))
        pools = len(self.path_requests("geckoterminal.test", "/api/v2/networks/base/pools"))
        self.clock += 1
        self.candidates = [cg_coin("new-cap")]
        self.address_cache["new-cap"] = ADDR_C
        self.gt_tokens[ADDR_C] = gt_token(ADDR_C, cg_id="new-cap")
        cap = await self.client.get("/market/base-tokens?sort_by=market_cap")
        self.assertEqual(cap.json()["tokens"][0]["id"], "new-cap")
        self.assertEqual(
            len(self.path_requests("coingecko.test", "/api/v3/coins/markets")),
            cg_markets + 1,
        )
        self.clock += 99
        cached_volume = await self.client.get("/market/base-tokens?sort_by=volume_24h")
        self.assertEqual(cached_volume.json(), volume.json())
        self.clock += 1
        self.gt_pools = [gt_pool(ADDR_D, WETH, 500)]
        self.gt_tokens[ADDR_D] = gt_token(ADDR_D, cg_id="new-volume")
        volume = await self.client.get("/market/base-tokens?sort_by=volume_24h")
        self.assertEqual(volume.json()["tokens"][0]["id"], "new-volume")
        self.assertEqual(
            len(self.path_requests("geckoterminal.test", "/api/v2/networks/base/pools")),
            pools + 1,
        )
        cached_cap = await self.client.get("/market/base-tokens")
        self.assertEqual(cached_cap.json(), cap.json())

    async def test_concurrent_ranks_share_one_provider_fetch_per_sort(self):
        self.gt_pools = [gt_pool(ADDR_B, WETH, 900)]
        self.gt_tokens[ADDR_B] = gt_token(ADDR_B, cg_id="volume-list")
        self.upstream_release.clear()
        sorts = ["market_cap", "volume_24h"] * 4
        tasks = [
            asyncio.create_task(self.client.get("/market/base-tokens", params={"sort_by": sort_by}))
            for sort_by in sorts
        ]
        try:
            await asyncio.wait_for(self.upstream_started.wait(), timeout=2)
            self.upstream_release.set()
            responses = await asyncio.wait_for(asyncio.gather(*tasks), timeout=2)
        finally:
            self.upstream_release.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        self.assertTrue(all(response.status_code == 200 for response in responses))
        cg_markets = [
            r
            for r in self.path_requests("coingecko.test", "/api/v3/coins/markets")
            if "ids" not in r.url.params
        ]
        self.assertEqual(len(cg_markets), 1)
        pools = self.path_requests("geckoterminal.test", "/api/v2/networks/base/pools")
        self.assertEqual(len(pools), 1)


if __name__ == "__main__":
    unittest.main()
