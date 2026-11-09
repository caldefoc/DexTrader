import os
import re
import unittest
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright


URL = os.environ.get("PORTFOLIO_TEST_URL", "http://127.0.0.1:3000")
TOKENS = [
    {
        "id": f"test-token-{i}", "name": f"Test Token {i}", "symbol": f"TEST{i}",
        "price": 0.000123 if i == 50 else i,
        "change_24h": None if i == 50 else (-2 if i % 2 else 3),
        "volume_24h": None if i == 50 else 1500000,
        "market_cap": (51 - i) * 1000000,
    }
    for i in range(1, 51)
]
MARKET = [
    {"base_symbol": "ETH", "price": 2000, "change_24h": 2, "volume_24h": 3925567185},
    {"base_symbol": "WETH", "price": 2000, "change_24h": 2, "volume_24h": 1500000},
    {"base_symbol": "USDC", "price": 1, "change_24h": 0, "volume_24h": 12345000},
]
CHAIN_TOKENS = {
    8453: ("0x4200000000000000000000000000000000000006", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"),
    1: ("0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"),
    42161: ("0x82af49447d8a07e3bd95bd0d56f35241523fbab1", "0xaf88d065e77c8cc2239327c5edb3a432268e5831"),
}
WALLET = """() => {
  localStorage.setItem('dexTrader_autoTrading', 'false');
  localStorage.setItem('dexTrader_network', 'base');
  window.__walletRequests = [];
  window.__chainId = '0x2105';
  const listeners = {};
  window.__switchChain = chainId => {
    window.__chainId = chainId;
    (listeners.chainChanged || []).forEach(handler => handler(chainId));
  };
  window.__changeAccounts = accounts => {
    (listeners.accountsChanged || []).forEach(handler => handler(accounts));
  };
  window.ethereum = {
    on(event, handler) { (listeners[event] ||= []).push(handler); },
    removeListener(event, handler) {
      listeners[event] = (listeners[event] || []).filter(fn => fn !== handler);
    },
    async request({method, params}) {
      window.__walletRequests.push({method, params});
      if (method === 'wallet_watchAsset') {
        window.__watchedAsset = params.options;
        return true;
      }
      if (method === 'eth_accounts' || method === 'eth_requestAccounts')
        return ['0x1111111111111111111111111111111111111111'];
      if (method === 'eth_chainId') return window.__chainId;
      if (method === 'eth_getBalance') return '0xde0b6b3a7640000';
      if (method === 'eth_call') {
        const to = params[0].to.toLowerCase();
        const chainTokens = {
          '0x1': ['0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2', '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48'],
          '0xa4b1': ['0x82af49447d8a07e3bd95bd0d56f35241523fbab1', '0xaf88d065e77c8cc2239327c5edb3a432268e5831']
        }[window.__chainId];
        if (chainTokens) {
          const value = params[0].data.startsWith('0x313ce567') ? (to === chainTokens[1] ? 6n : 18n) :
            to === chainTokens[0] ? 3000000000000000000n : to === chainTokens[1] ? 200000000n : 0n;
          return '0x' + value.toString(16).padStart(64, '0');
        }
        const balances = {
          '0x4200000000000000000000000000000000000006': 2000000000000000000n,
          '0x833589fcd6edb6e08f4c7c32d4f71b54bda02913': 100000000n
        };
        const decimals = to === '0x00f3c42833c3170159af4e92dbb451fb3f708917' ? 8n :
          to === '0x833589fcd6edb6e08f4c7c32d4f71b54bda02913' ? 6n : 18n;
        const value = params[0].data.startsWith('0x313ce567') ? decimals : (balances[to] || 0n);
        return '0x' + value.toString(16).padStart(64, '0');
      }
      throw new Error('Unexpected wallet request: ' + method);
    }
  };
}"""


class PortfolioDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel="chrome", headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 1000})
        self.page = self.context.new_page()
        self.tokens = TOKENS
        self.volume_tokens = [{**token, "id": f"volume-{index}", "name": f"Volume Token {index}",
                               "volume_24h": (51 - index) * 1000000} for index, token in enumerate(TOKENS, 1)]
        self.market = [dict(pair) for pair in MARKET]
        self.wallet_script = WALLET
        self.base_status = 200
        self.base_requests = 0
        self.requested_rankings = []
        self.market_limits = []
        self.volume_requests = []
        self.volume_status = 200
        self.volumes = {
            chain: {addresses[0]: 1500000 * index, addresses[1]: 12345000 * index}
            for index, (chain, addresses) in enumerate(CHAIN_TOKENS.items(), 1)
        }
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.context.route("**/*", self.route)

    def tearDown(self):
        self.context.close()

    def route(self, route):
        url = urlparse(route.request.url)
        if url.netloc == urlparse(URL).netloc:
            route.continue_()
        elif url.path == "/market/base-tokens":
            self.base_requests += 1
            ranking = parse_qs(url.query).get("sort_by", ["market_cap"])[0]
            self.requested_rankings.append(ranking)
            tokens = self.volume_tokens if ranking == "volume_24h" else self.tokens
            route.fulfill(status=self.base_status, json={"tokens": tokens})
        elif url.path == "/market/token-volumes":
            params = parse_qs(url.query)
            chain = int(params["chain_id"][0])
            addresses = params["addresses"][0].split(",")
            self.volume_requests.append((chain, addresses))
            route.fulfill(status=self.volume_status, json={
                "chain_id": chain,
                "volumes": {address: self.volumes.get(chain, {}).get(address) for address in addresses},
            })
        elif url.path == "/health":
            route.fulfill(json={"status": "ok"})
        elif url.path.rstrip("/") == "/market":
            self.market_limits.append(parse_qs(url.query).get("limit", ["50"])[0])
            route.fulfill(json={"pairs": self.market})
        elif url.path == "/market/gainers-losers":
            route.fulfill(json={"gainers": [], "losers": []})
        elif url.path.startswith("/signals"):
            route.fulfill(json=[])
        elif url.path in ("/agents/logs", "/agents/proposals"):
            route.fulfill(json=[])
        elif url.path == "/agents/status":
            route.fulfill(json={"running": False, "current_step": "idle", "last_run": None})
        elif url.path.startswith("/agents") or url.path.startswith("/portfolio/"):
            route.fulfill(json={})
        elif "exchangerate-api" in url.netloc:
            route.fulfill(json={"rates": {"EUR": 0.85}})
        else:
            route.fulfill(json={})

    def open_portfolio(self, wallet=False):
        if wallet:
            self.context.add_init_script(f"({self.wallet_script})();")
        self.page.goto(f"{URL}/portfolio")
        self.page.wait_for_load_state("networkidle")

    def test_volume_column_and_wallet_values(self):
        self.open_portfolio(wallet=True)
        headers = self.page.locator("table thead th").all_text_contents()
        self.assertIn("Volume", headers[5])
        self.assertIn("24h PnL", headers[4])
        self.assertIn("Trade", headers[6])
        for symbol, volume in [("ETH", "$1.5M"), ("WETH", "$1.5M"), ("USDC", "$12.345M")]:
            row = self.page.get_by_role("row").filter(has=self.page.get_by_role("cell", name=symbol, exact=True))
            expect(row.get_by_role("cell").nth(5)).to_have_text(volume)
        expect(self.page.get_by_text("24h DEX volume on Base · ETH uses WETH volume")).to_be_visible()
        self.assertEqual(set(self.volume_requests[-1][1]), set(CHAIN_TOKENS[8453]))
        self.page.get_by_role("button", name=re.compile("^Volume")).click()
        expect(self.page.locator("tbody tr td:first-child")).to_have_text(["USDC", "ETH", "WETH"])
        self.page.get_by_role("button", name=re.compile("^Volume")).click()
        expect(self.page.locator("tbody tr td:first-child")).to_have_text(["ETH", "WETH", "USDC"])
        self.assertEqual(self.errors, [])

    def test_missing_and_zero_volume(self):
        self.volumes[8453] = {CHAIN_TOKENS[8453][0]: 0}
        self.open_portfolio(wallet=True)
        for symbol, volume in [("ETH", "$0"), ("WETH", "$0"), ("USDC", "—")]:
            row = self.page.get_by_role("row").filter(has=self.page.get_by_role("cell", name=symbol, exact=True))
            expect(row.get_by_role("cell").nth(5)).to_have_text(volume)

    def test_vvv_volume_is_base_only_and_price_unchanged(self):
        vvv = "0xacfe6019ed1a7dc6f7b508c02d1b04ec88cc21bf"
        self.wallet_script = WALLET.replace("const balances = {", f"const balances = {{'{vvv}':10000000000000000000n,")
        self.market.append({"base_symbol": "VVV", "price": 7, "change_24h": 2, "volume_24h": 27991000})
        self.volumes[8453][vvv] = 6511000
        self.open_portfolio(wallet=True)
        row = self.page.get_by_role("row").filter(has=self.page.get_by_role("cell", name="VVV", exact=True))
        expect(row.get_by_role("cell").nth(5)).to_have_text("$6.511M")
        expect(row.get_by_role("cell").nth(2)).to_have_text("$7.00")
        expect(row.get_by_role("cell").nth(3)).to_have_text("$70.00")
        self.assertEqual(self.errors, [])

    def test_volume_follows_wallet_chain_not_saved_app_setting(self):
        self.open_portfolio(wallet=True)
        for chain, label, expected in [(1, "Ethereum Mainnet", "$3M"), (42161, "Arbitrum One", "$4.5M"), (8453, "Base", "$1.5M")]:
            self.page.evaluate("chain => window.__switchChain(chain)", hex(chain))
            expect(self.page.get_by_text(f"24h DEX volume on {label} · ETH uses WETH volume")).to_be_visible()
            row = self.page.get_by_role("row").filter(has=self.page.get_by_role("cell", name="WETH", exact=True))
            expect(row.get_by_role("cell").nth(5)).to_have_text(expected)
            expect(row.get_by_role("cell").nth(1)).to_have_text("2" if chain == 8453 else "3")
            self.assertEqual(self.volume_requests[-1][0], chain)
            self.assertEqual(set(self.volume_requests[-1][1]), set(CHAIN_TOKENS[chain]))
            self.assertEqual(self.page.evaluate("localStorage.getItem('dexTrader_network')"), "base")
            if chain != 8453:
                expect(row.get_by_role("button", name="Trade", exact=True)).to_be_disabled()
        self.assertEqual(self.errors, [])

    def test_initial_wallet_network_overrides_saved_base_setting(self):
        self.wallet_script = WALLET.replace("window.__chainId = '0x2105';", "window.__chainId = '0xa4b1';")
        self.open_portfolio(wallet=True)
        expect(self.page.get_by_text("24h DEX volume on Arbitrum One · ETH uses WETH volume")).to_be_visible()
        row = self.page.get_by_role("row").filter(has=self.page.get_by_role("cell", name="WETH", exact=True))
        expect(row.get_by_role("cell").nth(5)).to_have_text("$4.5M")
        self.assertTrue(all(chain == 42161 for chain, _ in self.volume_requests))
        self.assertEqual(self.errors, [])

    def test_unavailable_volume_never_falls_back_to_global(self):
        self.volume_status = 502
        self.open_portfolio(wallet=True)
        expect(self.page.locator("tbody tr td:nth-child(6)")).to_have_text(["—", "—", "—"])
        self.assertGreater(len(self.volume_requests), 0)
        self.assertEqual(self.errors, [])

    def test_refresh_failure_clears_old_volumes_and_retry_recovers(self):
        self.open_portfolio(wallet=True)
        row = self.page.get_by_role("row").filter(has=self.page.get_by_role("cell", name="WETH", exact=True))
        expect(row.get_by_role("cell").nth(5)).to_have_text("$1.5M")
        self.volume_status = 502
        with self.page.expect_response(lambda response: "/market/token-volumes?" in response.url and response.status == 502):
            self.page.get_by_role("button", name="Refresh", exact=True).click()
        expect(self.page.locator("tbody tr td:nth-child(6)")).to_have_text(["—", "—", "—"])
        self.volume_status = 200
        self.page.get_by_role("button", name="Refresh", exact=True).click()
        expect(row.get_by_role("cell").nth(5)).to_have_text("$1.5M")
        self.assertEqual(self.errors, [])

    def test_sepolia_does_not_request_mainnet_volumes(self):
        self.wallet_script = WALLET.replace("window.__chainId = '0x2105';", "window.__chainId = '0xaa36a7';")
        self.open_portfolio(wallet=True)
        expect(self.page.get_by_text("DEX volume unavailable on this network")).to_be_visible()
        expect(self.page.locator("tbody tr td:nth-child(6)")).to_have_text(["—"])
        self.assertEqual(self.volume_requests, [])
        self.assertEqual(self.errors, [])

    def test_unsupported_chain_and_disconnect_clear_previous_volume(self):
        self.open_portfolio(wallet=True)
        self.page.evaluate("window.__switchChain('0x89')")
        expect(self.page.get_by_text("DEX volume unavailable on this network")).to_be_visible()
        expect(self.page.locator("tbody tr td:nth-child(6)")).to_have_text(["—"])
        self.assertTrue(all(chain == 8453 for chain, _ in self.volume_requests))
        self.page.evaluate("window.__changeAccounts([])")
        expect(self.page.get_by_text("Connect a wallet to view holdings.")).to_be_visible()
        expect(self.page.locator("tbody tr td:nth-child(6)")).to_have_count(0)
        self.assertEqual(self.errors, [])

    def test_late_base_volume_cannot_overwrite_new_chain(self):
        self.wallet_script = WALLET.replace("window.__walletRequests = [];", """
          window.__walletRequests = [];
          const originalFetch = window.fetch.bind(window);
          window.fetch = (input, options) => {
            const url = new URL(String(input), location.origin);
            if (url.pathname === '/market/token-volumes' && url.searchParams.get('chain_id') === '8453') {
              return new Promise(resolve => {
                window.__releaseBaseVolume = () => resolve(new Response(JSON.stringify({
                  chain_id: 8453, volumes: {'0x4200000000000000000000000000000000000006': 999999999}
                }), {status: 200}));
              });
            }
            return originalFetch(input, options);
          };
        """)
        self.open_portfolio(wallet=True)
        self.page.wait_for_function("typeof window.__releaseBaseVolume === 'function'", timeout=5000)
        self.page.evaluate("window.__switchChain('0x1')")
        row = self.page.get_by_role("row").filter(has=self.page.get_by_role("cell", name="ETH", exact=True))
        expect(row.get_by_role("cell").nth(5)).to_have_text("$3M")
        self.page.evaluate("async () => { window.__releaseBaseVolume(); await new Promise(requestAnimationFrame); }")
        expect(row.get_by_role("cell").nth(5)).to_have_text("$3M")
        self.assertEqual(self.errors, [])

    def test_ranked_scrollable_panel_and_dashboard_signals(self):
        self.open_portfolio()
        expect(self.page.get_by_role("heading", name="Top 50 Base Tokens")).to_be_visible()
        expect(self.page.get_by_role("heading", name="Signals", exact=True)).to_have_count(0)
        panel = self.page.get_by_role("region", name="Base tokens ranked by market cap")
        expect(panel.get_by_role("listitem")).to_have_count(50)
        expect(panel.get_by_role("listitem").first).to_contain_text("Test Token 1")
        self.assertTrue(panel.evaluate("el => el.scrollHeight > el.clientHeight"))
        panel.get_by_role("listitem").last.scroll_into_view_if_needed()
        self.assertGreater(panel.evaluate("el => el.scrollTop"), 0)
        expect(panel.get_by_role("listitem").last).to_contain_text("$0.000123")
        self.page.get_by_role("button", name="Refresh Base tokens").click()
        expect(self.page.get_by_role("button", name="Refresh Base tokens")).to_be_enabled()
        self.assertGreaterEqual(self.base_requests, 2)
        self.page.goto(f"{URL}/dashboard")
        expect(self.page.get_by_role("heading", name="Signals", exact=True)).to_be_visible()
        self.assertEqual(self.errors, [])

    def test_empty_error_and_retry(self):
        self.tokens = []
        self.open_portfolio()
        expect(self.page.get_by_text("No Base tokens available. Try refreshing.")).to_be_visible()
        self.base_status = 502
        self.page.get_by_role("button", name="Refresh Base tokens").click()
        alert = self.page.get_by_role("alert").filter(has_text="Unable to load Base tokens")
        expect(alert).to_be_visible()
        self.base_status = 200
        self.tokens = TOKENS
        self.page.get_by_role("button", name="Refresh Base tokens").click()
        expect(self.page.get_by_role("listitem")).to_have_count(50)
        expect(alert).to_have_count(0)

    def test_mobile_and_disconnected_holdings(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.open_portfolio()
        expect(self.page.get_by_text("Connect a wallet to view holdings.")).to_have_attribute("colspan", "7")
        expect(self.page.get_by_role("heading", name="Top 50 Base Tokens")).to_be_visible()
        self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
        self.page.get_by_role("combobox", name="Rank Base tokens").select_option("volume_24h")
        panel = self.page.get_by_role("region", name="Base tokens ranked by 24hr volume")
        expect(panel.get_by_role("listitem")).to_have_count(50)
        self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))

    def test_switch_rankings_fetches_distinct_top_50_and_resets_scroll(self):
        self.open_portfolio()
        selector = self.page.get_by_role("combobox", name="Rank Base tokens")
        expect(selector).to_have_value("market_cap")
        cap_panel = self.page.get_by_role("region", name="Base tokens ranked by market cap")
        cap_panel.get_by_role("listitem").last.scroll_into_view_if_needed()
        selector.select_option(label="Rank by 24hr Volume")
        panel = self.page.get_by_role("region", name="Base tokens ranked by 24hr volume")
        expect(panel.get_by_role("listitem")).to_have_count(50)
        expect(panel.get_by_role("listitem").first).to_contain_text("Volume Token 1")
        self.assertEqual(panel.evaluate("el => el.scrollTop"), 0)
        self.assertIn("volume_24h", self.requested_rankings)
        self.page.get_by_role("button", name="Refresh Base tokens").click()
        expect(self.page.get_by_role("button", name="Refresh Base tokens")).to_be_enabled()
        self.assertEqual(self.requested_rankings[-1], "volume_24h")
        selector.select_option(label="Rank by Market Cap")
        expect(cap_panel.get_by_role("listitem").first).to_contain_text("Test Token 1")
        self.assertEqual(self.errors, [])

    def test_failed_rank_change_does_not_mislabel_old_data(self):
        self.open_portfolio()
        self.base_status = 502
        self.page.get_by_role("combobox", name="Rank Base tokens").select_option("volume_24h")
        expect(self.page.get_by_role("alert").filter(has_text="Unable to load Base tokens")).to_be_visible()
        expect(self.page.get_by_role("listitem")).to_have_count(0)
        self.base_status = 200
        self.page.get_by_role("button", name="Refresh Base tokens").click()
        expect(self.page.get_by_role("listitem").first).to_contain_text("Volume Token 1")

    def test_new_tokens_available_in_manual_base_trade(self):
        self.open_portfolio(wallet=True)
        eth_row = self.page.get_by_role("row").filter(has=self.page.get_by_role("cell", name="ETH", exact=True))
        eth_row.get_by_role("button", name="Trade", exact=True).click()
        expect(self.page.get_by_role("heading", name="Execute Trade")).to_be_visible()
        selector = self.page.locator(".fixed select")
        for symbol in ("ENA", "ICP", "MORPHO", "ETHFI", "ZRO"):
            expect(selector.locator(f'option[value="{symbol}"]')).to_have_count(1)
            selector.select_option(symbol)
            expect(selector).to_have_value(symbol)
        self.page.wait_for_load_state("networkidle")
        self.assertEqual(self.market_limits[-1], "500")
        self.assertFalse(self.page.evaluate("window.__walletRequests.some(r => /sendTransaction|sign/i.test(r.method))"))
        self.assertEqual(self.errors, [])

    def test_icp_holdings_and_wallet_import_use_eight_decimals(self):
        self.wallet_script = WALLET.replace("const balances = {", "const balances = {'0x00f3c42833c3170159af4e92dbb451fb3f708917':1250000000n,")
        self.market.append({"base_symbol": "ICP", "price": 5, "change_24h": 1, "volume_24h": 5000000})
        self.open_portfolio(wallet=True)
        row = self.page.get_by_role("row").filter(has=self.page.get_by_role("cell", name="ICP", exact=True))
        expect(row.get_by_role("cell").nth(1)).to_have_text("12.5")
        expect(row.get_by_role("cell").nth(3)).to_have_text("$62.50")
        row.get_by_title("Add to MetaMask", exact=True).click()
        self.page.wait_for_function("window.__watchedAsset !== undefined")
        watched = self.page.evaluate("window.__watchedAsset")
        self.assertEqual(watched["symbol"], "ICP")
        self.assertEqual(watched["decimals"], 8)
        self.assertEqual(watched["address"].lower(), "0x00f3c42833c3170159af4e92dbb451fb3f708917")
        row.get_by_role("button", name="Trade", exact=True).click()
        expect(self.page.get_by_text("Available: 12.5000 ICP", exact=True)).to_be_visible()
        self.assertEqual(self.errors, [])

    def test_icp_quote_decimal_fallback_for_input_and_output(self):
        icp = "0x00f3c42833c3170159af4e92dbb451fb3f708917"
        self.wallet_script = WALLET.replace("const balances = {", f"const balances = {{'{icp}':1250000000n,")
        self.wallet_script = self.wallet_script.replace("const decimals = to ===", """
        if (to === '0x00f3c42833c3170159af4e92dbb451fb3f708917' && params[0].data.startsWith('0x313ce567'))
          throw new Error('Simulated decimals RPC failure');
        if (to === '0x3d4e44eb1374240ce5f1b871ab261cd16335b76a') {
          const data = params[0].data.slice(10);
          const output = '0x' + data.slice(64 + 24, 128);
          const amount = BigInt('0x' + data.slice(128, 192));
          (window.__quotes ||= []).push({output, amount: amount.toString()});
          const out = output === '0x00f3c42833c3170159af4e92dbb451fb3f708917' ? 250000000n : 5000000n;
          return '0x' + [out, 79228162514264337593543950336n, 0n, 100000n].map(n => n.toString(16).padStart(64, '0')).join('');
        }
        const decimals = to ===""")
        self.open_portfolio(wallet=True)
        row = self.page.get_by_role("row").filter(has=self.page.get_by_role("cell", name="ICP", exact=True))
        row.get_by_role("button", name="Trade", exact=True).click()
        expect(self.page.get_by_text("Available: 12.5000 ICP", exact=True)).to_be_visible()
        self.page.get_by_placeholder("0.0", exact=True).fill("1.25")
        expect(self.page.get_by_text("5.000000", exact=True)).to_be_visible()
        self.assertTrue(self.page.evaluate("window.__quotes.some(q => q.amount === '125000000')"))
        self.assertFalse(self.page.evaluate("window.__quotes.some(q => q.amount === '1250000000000000000')"))
        self.page.reload()
        eth_row = self.page.get_by_role("row").filter(has=self.page.get_by_role("cell", name="ETH", exact=True))
        eth_row.get_by_role("button", name="Trade", exact=True).click()
        self.page.locator(".fixed select").select_option("ICP")
        self.page.get_by_placeholder("0.0", exact=True).fill("0.01")
        expect(self.page.get_by_text("2.500000", exact=True)).to_be_visible()
        self.assertFalse(self.page.evaluate("window.__walletRequests.some(r => /sendTransaction|sign/i.test(r.method))"))
        self.assertEqual(self.errors, [])

    def test_partial_fill_quote_is_rejected_as_no_route(self):
        quoter = "0x3d4e44eb1374240ce5f1b871ab261cd16335b76a"
        boundary = "1461446703485210103287273052203988822378723970341"  # MAX_SQRT_RATIO - 1
        wallet = WALLET.replace("const balances = {", "const balances = {'0x58538e6a46e07434d7e7375bc268d3cb839c0133':100000000000000000000n,")
        wallet = wallet.replace("const decimals = to ===", f"""
        if (to === '{quoter}') {{
          const word0 = params[0].data.slice(10, 74);
          if (BigInt('0x' + word0) === 64n) {{
            return '0x' + [0n, 128n, 160n, 100000n, 0n, 0n].map(n => n.toString(16).padStart(64, '0')).join('');
          }}
          return '0x' + [1n, {boundary}n, 0n, 100000n].map(n => n.toString(16).padStart(64, '0')).join('');
        }}
        const decimals = to ===""")
        self.wallet_script = wallet
        self.market.append({"base_symbol": "ENA", "price": 0.3, "change_24h": 1, "volume_24h": 466000000})
        self.open_portfolio(wallet=True)
        row = self.page.get_by_role("row").filter(has=self.page.get_by_role("cell", name="ENA", exact=True))
        row.get_by_role("button", name="Trade", exact=True).click()
        self.page.locator(".fixed select").select_option("WETH")
        self.page.get_by_placeholder("0.0", exact=True).fill("10")
        expect(self.page.get_by_text(re.compile("No route found"))).to_be_visible()
        expect(self.page.get_by_text("Price Impact", exact=True)).to_have_count(0)
        self.assertFalse(self.page.evaluate("window.__walletRequests.some(r => /sendTransaction|sign/i.test(r.method))"))
        self.assertEqual(self.errors, [])

    def test_agents_sync_icp_balance_when_decimals_rpc_fails(self):
        wallet = WALLET.replace("const balances = {", "const balances = {'0x00f3c42833c3170159af4e92dbb451fb3f708917':1250000000n,")
        wallet = wallet.replace("const decimals = to ===", """
        if (to === '0x00f3c42833c3170159af4e92dbb451fb3f708917' && params[0].data.startsWith('0x313ce567'))
          throw new Error('Simulated decimals RPC failure');
        const decimals = to ===""")
        self.context.add_init_script(f"({wallet})();")
        with self.page.expect_request(lambda request: urlparse(request.url).path == "/agents/holdings" and request.method == "POST") as sync:
            self.page.goto(f"{URL}/agents")
        self.assertEqual(sync.value.post_data_json["ICP"], 12.5)
        self.assertEqual(self.errors, [])

    def test_agents_monitored_defaults_and_auto_targets(self):
        self.page.goto(f"{URL}/agents")
        self.page.wait_for_load_state("networkidle")
        monitored = self.page.get_by_placeholder("ETH, BTC, SOL...")
        tokens = {token.strip().upper() for token in monitored.input_value().split(",")}
        self.assertTrue({"FAI", "LUNA", "CLANKER", "BRETT"}.isdisjoint(tokens))
        self.assertTrue({"ETH", "WETH", "VVV", "VIRTUAL", "AERO", "TIBBIR", "AVNT"} <= tokens)
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
