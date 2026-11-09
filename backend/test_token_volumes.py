import asyncio
from collections import OrderedDict
import json
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI

from app.api import routes_market
from app.services import geckoterminal


HTTPX_CLIENT = httpx.AsyncClient
ADDR_A = "0x" + "aa" * 20
ADDR_B = "0x" + "bb" * 20
ADDR_C = "0x" + "cc" * 20
MISSING = object()


def numbered_address(index):
    return f"0x{index:040x}"


def token(address, volume="6511000", **attributes):
    # Deliberately omit name, symbol, price, and CoinGecko ID.
    return {"attributes": {"address": address, "volume_usd": {"h24": volume}, **attributes}}


class TokenVolumeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Never import app.main or run startup/trading/runtime-file operations.
        app = FastAPI()
        app.include_router(routes_market.router, prefix="/market")
        self.client = HTTPX_CLIENT(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        )
        self.addAsyncCleanup(self.client.aclose)
        self.requests = []
        self.tokens = {network: {ADDR_A: token(ADDR_A)} for network in ("eth", "base", "arbitrum")}
        self.extra_tokens = []
        self.statuses = []
        self.failure = None
        self.failure_address = None
        self.raw_content = None
        self.envelope = MISSING
        self.clock = 1000.0
        self.upstream_started = asyncio.Event()
        self.upstream_release = asyncio.Event()
        self.upstream_release.set()
        # create=True lets the initial red run fail on the absent endpoint,
        # rather than on cache internals that do not exist yet.
        self.start_patch(patch.object(routes_market, "_token_volumes_cache", OrderedDict(), create=True))
        self.start_patch(patch.object(routes_market, "_token_volumes_lock", asyncio.Lock(), create=True))
        self.start_patch(patch.object(routes_market, "time", monotonic=lambda: self.clock))
        self.start_patch(patch.object(geckoterminal, "GECKOTERMINAL_BASE_URL", "https://geckoterminal.test/api/v2"))
        self.start_patch(patch.object(geckoterminal, "RATE_LIMIT_RETRY_DELAY", 0))
        self.start_patch(patch.object(httpx, "AsyncClient", side_effect=lambda **kwargs: HTTPX_CLIENT(
            transport=httpx.MockTransport(self.upstream), **kwargs
        )))

    def start_patch(self, patcher):
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def respond(self, payload, status=200):
        # Allow nonfinite upstream JSON values so the parser must reject them.
        return httpx.Response(status, content=json.dumps(payload), headers={"Content-Type": "application/json"})

    async def upstream(self, request):
        self.requests.append(request)
        self.upstream_started.set()
        await self.upstream_release.wait()
        self.assertEqual(request.url.host, "geckoterminal.test", "No global/CG fallback permitted")
        parts = request.url.path.split("/")
        self.assertEqual(parts[:4], ["", "api", "v2", "networks"])
        self.assertIn(parts[4], ("eth", "base", "arbitrum"))
        self.assertEqual(parts[5:7], ["tokens", "multi"])
        self.assertEqual(len(parts), 8)
        self.assertFalse(request.url.query)
        addresses = parts[7].split(",")
        self.assertLessEqual(len(addresses), 30)
        if self.failure and (self.failure_address is None or self.failure_address in addresses):
            if self.failure == "timeout":
                raise httpx.ReadTimeout("private provider URL/key", request=request)
            return self.respond({"error": "private provider URL/key"}, status=503)
        if self.statuses:
            return self.respond({"error": "private rate limit"}, status=self.statuses.pop(0))
        if self.raw_content is not None:
            return httpx.Response(200, content=self.raw_content, headers={"Content-Type": "application/json"})
        if self.envelope is not MISSING:
            return self.respond(self.envelope)
        data = [self.tokens[parts[4]][address] for address in addresses if address in self.tokens[parts[4]]]
        return self.respond({"data": data + self.extra_tokens})

    async def get_volumes(self, addresses=ADDR_A, chain_id=8453, **extra):
        return await self.client.get("/market/token-volumes", params={
            "chain_id": chain_id, "addresses": addresses, **extra,
        })

    def assert_volumes(self, response, volumes, chain_id=8453):
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"chain_id": chain_id, "volumes": volumes})

    def requested_batches(self):
        return [request.url.path.rsplit("/", 1)[1].split(",") for request in self.requests]

    def assert_safe_failure(self, response):
        self.assertEqual(response.status_code, 502, response.text)
        self.assertEqual(response.json(), {"detail": "Unable to fetch token volumes"})
        self.assertNotIn("private", response.text)
        self.assertNotIn("geckoterminal", response.text)

    async def test_chain_mappings_and_volume_without_price_name_symbol_or_global_lookup(self):
        for chain_id, network, volume in ((1, "eth", 10), (8453, "base", 6511000), (42161, "arbitrum", 30)):
            with self.subTest(chain_id=chain_id):
                self.tokens[network][ADDR_A] = token(ADDR_A, str(volume), price_usd=None)
                response = await self.get_volumes(chain_id=chain_id)
                self.assert_volumes(response, {ADDR_A: float(volume)}, chain_id)
                self.assertIn(f"/networks/{network}/tokens/multi/", self.requests[-1].url.path)

    async def test_normalizes_deduplicates_and_includes_unknown_tokens(self):
        upper_a = "0x" + "Aa" * 20
        self.tokens["base"][ADDR_A] = token(upper_a)
        response = await self.get_volumes(f"{upper_a},{ADDR_B},{ADDR_A},{upper_a}")
        self.assert_volumes(response, {ADDR_A: 6511000.0, ADDR_B: None})
        self.assertEqual(self.requested_batches(), [[ADDR_A, ADDR_B]])
        self.assertEqual(self.requests[0].headers["Accept"], "application/json")
        self.assertNotIn("x-cg-demo-api-key", self.requests[0].headers)

    async def test_volume_service_filters_unrequested_tokens_and_preserves_nulls(self):
        self.assertTrue(hasattr(geckoterminal, "fetch_token_volumes"))
        self.extra_tokens = [token(ADDR_C, "99")]
        result = await geckoterminal.fetch_token_volumes("base", ["0x" + "AA" * 20, ADDR_A, ADDR_B])
        self.assertEqual(result, {ADDR_A: 6511000.0, ADDR_B: None})
        self.assertEqual(self.requested_batches(), [[ADDR_A, ADDR_B]])

    async def test_volume_service_rejects_arbitrary_network_names(self):
        self.assertTrue(hasattr(geckoterminal, "fetch_token_volumes"))
        for network in ("ethereum", "BASE", "optimism", "../eth", "https://evil.test"):
            with self.subTest(network=network), self.assertRaises(ValueError):
                await geckoterminal.fetch_token_volumes(network, [ADDR_A])
        self.assertEqual(self.requests, [])

    async def test_shared_fetch_preserves_base_parser_behavior_for_duplicate_entries(self):
        self.tokens["base"][ADDR_A] = token(
            ADDR_A, name="Token", symbol="TOK", price_usd="2.5", fdv_usd="100"
        )
        # The existing metrics parser skips an invalid duplicate rather than
        # discarding the valid metrics it already parsed for the same address.
        self.extra_tokens = [
            token(ADDR_A, name="Broken", symbol="BAD", price_usd=None),
            token(ADDR_B, name="Unrequested", symbol="OTHER", price_usd="999"),
        ]
        metrics = await geckoterminal.fetch_base_token_metrics([ADDR_A])
        self.assertEqual(set(metrics), {ADDR_A})
        self.assertEqual(metrics[ADDR_A].name, "Token")
        self.assertEqual(metrics[ADDR_A].price, 2.5)
        self.assertEqual(metrics[ADDR_A].fdv, 100.0)
        self.assertEqual(metrics[ADDR_A].volume_24h, 6511000.0)

    async def test_one_hundred_addresses_are_batched_by_thirty(self):
        addresses = [numbered_address(i) for i in range(100)]
        self.tokens["base"] = {address: token(address, str(i)) for i, address in enumerate(addresses)}
        response = await self.get_volumes(",".join(addresses))
        self.assert_volumes(response, {address: float(i) for i, address in enumerate(addresses)})
        self.assertEqual([len(batch) for batch in self.requested_batches()], [30, 30, 30, 10])
        self.assertEqual([a for batch in self.requested_batches() for a in batch], addresses)

    async def test_unrequested_provider_tokens_are_not_returned_or_cached(self):
        self.extra_tokens = [token(ADDR_B, "999999")]
        first = await self.get_volumes()
        self.assert_volumes(first, {ADDR_A: 6511000.0})
        self.assertNotIn((8453, ADDR_B), routes_market._token_volumes_cache)
        self.extra_tokens.clear()
        self.assert_volumes(await self.get_volumes(ADDR_B), {ADDR_B: None})
        self.assertEqual(self.requested_batches(), [[ADDR_A], [ADDR_B]])

    async def test_volume_zero_is_preserved_and_invalid_values_are_null(self):
        values = ["0", 0, "1.25", 8, None, -1, "-0.1", True, False, "NaN", "Infinity", "-Infinity",
                  float("nan"), float("inf"), float("-inf"), "1e9999", "bad", "", {}, []]
        addresses = [numbered_address(i) for i in range(len(values))]
        self.tokens["base"] = {address: token(address, value) for address, value in zip(addresses, values)}
        expected = dict.fromkeys(addresses)
        expected.update(zip(addresses[:4], (0.0, 0.0, 1.25, 8.0)))
        self.assert_volumes(await self.get_volumes(",".join(addresses)), expected)

    async def test_missing_volume_and_malformed_token_entries_become_null(self):
        entries = [
            {"attributes": {"address": ADDR_A}},
            {"attributes": {"address": ADDR_A, "volume_usd": {}}},
            {"attributes": {"address": ADDR_A, "volume_usd": None}},
            {"attributes": {"address": ADDR_A, "volume_usd": []}},
            {"attributes": {"address": ADDR_A, "volume_usd": "10"}},
            {"attributes": {"address": ADDR_A, "volume_usd": {"h1": "10"}}},
            None, [], {}, {"attributes": None}, {"attributes": []},
            {"attributes": {"address": True}}, {"attributes": {"address": [ADDR_A]}},
        ]
        for entry in entries:
            with self.subTest(entry=entry):
                routes_market._token_volumes_cache.clear()
                self.envelope = {"data": [entry]}
                self.assert_volumes(await self.get_volumes(), {ADDR_A: None})

    async def test_invalid_or_unsupported_chain_is_422_before_provider(self):
        for chain_id in ("", "base", "eth", "https://evil.test", "8453.0", "8.453e3", "true", "null",
                         "-1", "0", "10", "56", "137", "84532", "1" * 10000):
            with self.subTest(chain_id=chain_id):
                self.assertEqual((await self.get_volumes(chain_id=chain_id)).status_code, 422)
        self.assertEqual(self.requests, [])

    async def test_invalid_addresses_and_bounded_length_are_422_before_provider(self):
        invalid = ["", "0x", "ETH", "native", "0x" + "a" * 39, "0x" + "a" * 41,
                   "0x" + "g" * 40, "0X" + "a" * 40, " " + ADDR_A, ADDR_A + " ",
                   ADDR_A + "\n", ADDR_A + ",", "," + ADDR_A, ADDR_A + ",," + ADDR_B,
                   ADDR_A + ",ETH", ADDR_A + "/../pools", "a" * 10000]
        for addresses in invalid:
            with self.subTest(addresses=addresses):
                self.assertEqual((await self.get_volumes(addresses)).status_code, 422)
        self.assertEqual(self.requests, [])

    async def test_too_many_supplied_addresses_are_rejected_even_if_duplicates(self):
        for addresses in ([numbered_address(i) for i in range(101)], [ADDR_A] * 101):
            with self.subTest(unique=len(set(addresses))):
                self.assertEqual((await self.get_volumes(",".join(addresses))).status_code, 422)
        self.assertEqual(self.requests, [])

    async def test_missing_parameters_are_422_before_provider(self):
        for params in ({}, {"chain_id": "8453"}, {"addresses": ADDR_A}):
            with self.subTest(params=params):
                response = await self.client.get("/market/token-volumes", params=params)
                self.assertEqual(response.status_code, 422)
        self.assertEqual(self.requests, [])

    async def test_entire_query_length_is_bounded_before_provider(self):
        response = await self.get_volumes(unused="x" * 10000)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.requests, [])

    async def test_duplicate_query_fields_are_422_before_provider(self):
        for field, value in (("chain_id", "1"), ("addresses", ADDR_B)):
            with self.subTest(field=field):
                response = await self.client.get("/market/token-volumes", params=[
                    ("chain_id", "8453"), ("addresses", ADDR_A), (field, value),
                ])
                self.assertEqual(response.status_code, 422)
        self.assertEqual(self.requests, [])

    async def test_http_and_timeout_failures_are_safe_and_never_cached(self):
        for failure in ("http", "timeout"):
            with self.subTest(failure=failure):
                self.failure = failure
                before = len(self.requests)
                for _ in range(2):
                    self.assert_safe_failure(await self.get_volumes())
                self.assertEqual(len(self.requests), before + 2)
                self.assertEqual(len(routes_market._token_volumes_cache), 0)
        self.failure = None
        self.assert_volumes(await self.get_volumes(), {ADDR_A: 6511000.0})

    async def test_malformed_envelopes_and_json_are_safe_and_never_cached(self):
        for envelope in (None, [], "private provider details", {}, {"errors": ["private"]},
                         {"data": None}, {"data": {}}, {"data": "private"}):
            with self.subTest(envelope=envelope):
                self.envelope = envelope
                before = len(self.requests)
                for _ in range(2):
                    self.assert_safe_failure(await self.get_volumes())
                self.assertEqual(len(self.requests), before + 2)
                self.assertFalse(routes_market._token_volumes_cache)
        self.envelope = MISSING
        self.raw_content = "not JSON: private provider details"
        for _ in range(2):
            self.assert_safe_failure(await self.get_volumes())
        self.assertFalse(routes_market._token_volumes_cache)
        self.raw_content = None
        self.assert_volumes(await self.get_volumes(), {ADDR_A: 6511000.0})

    async def test_rate_limit_reuses_existing_retry(self):
        self.statuses = [429]
        self.assert_volumes(await self.get_volumes(), {ADDR_A: 6511000.0})
        self.assertEqual(self.requested_batches(), [[ADDR_A], [ADDR_A]])

    async def test_persistent_rate_limit_is_safe_and_not_cached(self):
        self.statuses = [429, 429, 429, 429]
        for _ in range(2):
            self.assert_safe_failure(await self.get_volumes())
        self.assertEqual(len(self.requests), 4)
        self.assertFalse(routes_market._token_volumes_cache)

    async def test_later_batch_failure_does_not_cache_partial_success(self):
        addresses = [numbered_address(i) for i in range(31)]
        self.tokens["base"] = {address: token(address, "10") for address in addresses}
        self.failure = "http"
        self.failure_address = addresses[-1]
        for _ in range(2):
            self.assert_safe_failure(await self.get_volumes(",".join(addresses)))
            self.assertFalse(routes_market._token_volumes_cache)
        self.assertEqual([len(batch) for batch in self.requested_batches()], [30, 1, 30, 1])
        self.failure = None
        self.assert_volumes(await self.get_volumes(",".join(addresses)), dict.fromkeys(addresses, 10.0))
        self.assertEqual([len(batch) for batch in self.requested_batches()], [30, 1, 30, 1, 30, 1])

    async def test_cache_is_by_chain_address_not_order_or_request_set(self):
        self.tokens["base"].update({ADDR_B: token(ADDR_B, "20"), ADDR_C: token(ADDR_C, "30")})
        self.tokens["eth"][ADDR_A] = token(ADDR_A, "40")
        self.assert_volumes(await self.get_volumes(f"{ADDR_A},{ADDR_B}"), {ADDR_A: 6511000.0, ADDR_B: 20.0})
        self.tokens["base"][ADDR_A] = token(ADDR_A, "99")
        self.assert_volumes(await self.get_volumes(f"{ADDR_B},0x{'AA' * 20}", refresh="true"), {ADDR_B: 20.0, ADDR_A: 6511000.0})
        self.assert_volumes(await self.get_volumes(f"{ADDR_C},{ADDR_A}"), {ADDR_C: 30.0, ADDR_A: 6511000.0})
        self.assert_volumes(await self.get_volumes(chain_id=1), {ADDR_A: 40.0}, chain_id=1)
        self.assert_volumes(await self.get_volumes(), {ADDR_A: 6511000.0})
        self.assertEqual(self.requested_batches(), [[ADDR_A, ADDR_B], [ADDR_C], [ADDR_A]])

    async def test_missing_token_null_is_cached_until_ttl(self):
        self.assert_volumes(await self.get_volumes(ADDR_B), {ADDR_B: None})
        self.tokens["base"][ADDR_B] = token(ADDR_B, "5")
        self.clock += 299
        self.assert_volumes(await self.get_volumes(ADDR_B), {ADDR_B: None})
        self.assertEqual(len(self.requests), 1)
        self.clock += 1
        self.assert_volumes(await self.get_volumes(ADDR_B), {ADDR_B: 5.0})
        self.assertEqual(len(self.requests), 2)

    async def test_ttl_expires_independently_per_address_without_sliding_on_hits(self):
        self.assert_volumes(await self.get_volumes(), {ADDR_A: 6511000.0})
        self.clock += 100
        self.tokens["base"][ADDR_B] = token(ADDR_B, "20")
        self.assert_volumes(await self.get_volumes(ADDR_B), {ADDR_B: 20.0})
        self.tokens["base"].update({ADDR_A: token(ADDR_A, "99"), ADDR_B: token(ADDR_B, "88")})
        self.clock += 199
        self.assert_volumes(await self.get_volumes(f"{ADDR_A},{ADDR_B}"), {ADDR_A: 6511000.0, ADDR_B: 20.0})
        self.clock += 1
        self.assert_volumes(await self.get_volumes(f"{ADDR_A},{ADDR_B}"), {ADDR_A: 99.0, ADDR_B: 20.0})
        self.clock += 100
        self.assert_volumes(await self.get_volumes(f"{ADDR_A},{ADDR_B}"), {ADDR_A: 99.0, ADDR_B: 88.0})
        self.assertEqual(self.requested_batches(), [[ADDR_A], [ADDR_B], [ADDR_A], [ADDR_B]])

    async def test_failed_refresh_does_not_replace_or_extend_prior_success(self):
        self.assert_volumes(await self.get_volumes(), {ADDR_A: 6511000.0})
        self.clock += 100
        self.assert_volumes(await self.get_volumes(ADDR_B), {ADDR_B: None})
        prior_cache = routes_market._token_volumes_cache.copy()
        self.clock += 200
        self.failure = "http"
        for _ in range(2):
            self.assert_safe_failure(await self.get_volumes(f"{ADDR_B},{ADDR_A},{ADDR_C}"))
            self.assertEqual(routes_market._token_volumes_cache, prior_cache)
        self.failure = None
        self.tokens["base"][ADDR_A] = token(ADDR_A, "99")
        self.assert_volumes(await self.get_volumes(), {ADDR_A: 99.0})
        self.assertEqual(len(self.requests), 5)

    async def test_cache_does_not_touch_market_or_top50_caches(self):
        market = [object()]
        top50 = {"market_cap": object(), "volume_24h": object()}
        timestamps = {"market_cap": 12.0, "volume_24h": 20.0}
        with (
            patch.object(routes_market, "_market_data_cache", market),
            patch.object(routes_market, "_cache_timestamp", 42.0),
            patch.object(routes_market, "_base_tokens_cache", top50),
            patch.object(routes_market, "_base_tokens_timestamp", timestamps),
        ):
            self.assert_volumes(await self.get_volumes(), {ADDR_A: 6511000.0})
            self.assertIs(routes_market._market_data_cache, market)
            self.assertEqual(routes_market._cache_timestamp, 42.0)
            self.assertIs(routes_market._base_tokens_cache, top50)
            self.assertEqual(routes_market._base_tokens_timestamp, timestamps)

    async def test_cache_is_bounded_lru_and_hits_protect_recent_entries(self):
        # Exercise the real 1000-entry bound, including negative cache entries.
        addresses = [numbered_address(i) for i in range(1000)]
        for start in range(0, len(addresses), 100):
            batch = addresses[start:start + 100]
            self.assert_volumes(await self.get_volumes(",".join(batch)), dict.fromkeys(batch))
        self.assertEqual(len(routes_market._token_volumes_cache), 1000)
        self.assert_volumes(await self.get_volumes(addresses[0]), {addresses[0]: None})
        new_address = numbered_address(1000)
        self.assert_volumes(await self.get_volumes(new_address), {new_address: None})
        self.assertEqual(len(routes_market._token_volumes_cache), 1000)
        self.assertIn((8453, addresses[0]), routes_market._token_volumes_cache)
        self.assertNotIn((8453, addresses[1]), routes_market._token_volumes_cache)
        before = len(self.requests)
        self.assert_volumes(await self.get_volumes(addresses[0]), {addresses[0]: None})
        self.assertEqual(len(self.requests), before)
        self.assert_volumes(await self.get_volumes(addresses[1]), {addresses[1]: None})
        self.assertEqual(len(self.requests), before + 1)
        self.assertEqual(len(routes_market._token_volumes_cache), 1000)

    async def test_concurrent_misses_share_work_and_ttl_starts_at_completion(self):
        self.assertTrue(any(route.path == "/market/token-volumes" for route in self.client._transport.app.routes))
        self.upstream_release.clear()
        tasks = [asyncio.create_task(self.get_volumes(f"{ADDR_A},{ADDR_B}")) for _ in range(8)]
        try:
            await asyncio.wait_for(self.upstream_started.wait(), timeout=2)
            self.assertEqual(len(self.requests), 1)
            self.clock += 40
            self.upstream_release.set()
            responses = await asyncio.wait_for(asyncio.gather(*tasks), timeout=2)
        finally:
            self.upstream_release.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        for response in responses:
            self.assert_volumes(response, {ADDR_A: 6511000.0, ADDR_B: None})
        self.clock += 299
        self.assert_volumes(await self.get_volumes(f"{ADDR_B},{ADDR_A}"), {ADDR_A: 6511000.0, ADDR_B: None})
        self.assertEqual(len(self.requests), 1)
        self.clock += 1
        self.assert_volumes(await self.get_volumes(), {ADDR_A: 6511000.0})
        self.assertEqual(len(self.requests), 2)

    async def test_overlapping_concurrent_sets_only_fetch_each_missing_address_once(self):
        self.assertTrue(any(route.path == "/market/token-volumes" for route in self.client._transport.app.routes))
        self.upstream_release.clear()
        first = asyncio.create_task(self.get_volumes(f"{ADDR_A},{ADDR_B}"))
        tasks = [first]
        try:
            await asyncio.wait_for(self.upstream_started.wait(), timeout=2)
            tasks.extend(asyncio.create_task(self.get_volumes(addresses)) for addresses in (
                f"{ADDR_B},{ADDR_A}", f"{ADDR_B},{ADDR_C}", ADDR_C,
            ))
            self.upstream_release.set()
            responses = await asyncio.wait_for(asyncio.gather(*tasks), timeout=2)
        finally:
            self.upstream_release.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        self.assertTrue(all(response.status_code == 200 for response in responses))
        self.assertEqual(self.requested_batches(), [[ADDR_A, ADDR_B], [ADDR_C]])


if __name__ == "__main__":
    unittest.main()
