const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");
const ts = require("../frontend/node_modules/typescript");

const root = path.resolve(__dirname, "..");
const targets = ["ETH", "WETH", "VVV", "VIRTUAL", "AERO", "TIBBIR", "AVNT"];
const excluded = [
  "DEGEN", "TOSHI", "BRETT", "FAI", "LUNA", "CLANKER", "SHIB", "AIXBT",
  "ARB", "ETHY", "AAVE", "UNI", "LINK", "CBBTC", "BTC", "USDT", "UNKNOWN",
  "ENA", "ICP", "MORPHO", "ETHFI", "ZRO",
];
const quiet = { log() {}, warn() {}, error() {} };
const source = (file) => fs.readFileSync(path.join(root, file), "utf8");

// Evaluate real TypeScript in memory; only external boundaries are mocked.
function load(file, imports, globals = {}) {
  const { outputText, diagnostics } = ts.transpileModule(source(file), {
    fileName: file,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
    reportDiagnostics: true,
  });
  assert.equal(diagnostics.length, 0);
  const exports = {};
  vm.runInNewContext(outputText, {
    exports, console: quiet,
    require(name) {
      assert.ok(Object.hasOwn(imports, name), `Unexpected import: ${name}`);
      return imports[name];
    },
    ...globals,
  }, { filename: file });
  return exports;
}

function executor(chainId = 1) {
  const calls = { providers: 0, wallet: [], signers: 0, contracts: 0 };
  const ethereum = { request: async (request) => {
    calls.wallet.push(request);
    return `0x${chainId.toString(16)}`;
  } };
  const api = load("frontend/lib/autoTradeExecutor.ts", {
    ethers: {
      BrowserProvider: class {
        constructor() { calls.providers++; }
        async getNetwork() {
          return { chainId: BigInt(await ethereum.request({ method: "eth_chainId" })) };
        }
        async getSigner() { calls.signers++; throw new Error("TEST_SIGNER_BOUNDARY"); }
      },
      Contract: class {
        constructor() { calls.contracts++; throw new Error("Unexpected contract access"); }
      },
    },
    "../constants/tokens": { BASE_TOKENS: {} },
  }, { window: { ethereum } });
  return { ...api, calls };
}

const params = (tokenIn, tokenOut) => ({
  tokenIn, tokenOut, amountIn: "1", slippage: "0.5", gasPriceGwei: "0.01",
});

for (const target of targets) {
  test(`${target}: USDC buys and sells accept upper/lower-case symbols`, async () => {
    const api = executor();
    for (const symbol of [target, target.toLowerCase()]) {
      for (const [tokenIn, tokenOut] of [["usdc", symbol], [symbol, "USDC"]]) {
        assert.equal(api.isAutoTradeEligible(tokenIn, tokenOut), true);
        const result = await api.executeAutoSwap(params(tokenIn, tokenOut));
        assert.equal(result.success, false);
        assert.match(result.error, /requires Base network/);
      }
    }
    assert.equal(api.calls.wallet.length, 4);
    assert.equal(api.calls.signers, 0);
  });
}

test("one exported list contains exactly the seven strategy targets, not USDC", () => {
  assert.deepEqual(Array.from(executor().AUTO_TRADE_TARGETS ?? []), targets);
});

const invalidPairs = [
  ...excluded.flatMap((symbol) => [
    ["USDC", symbol], [symbol, "USDC"], ["eth", symbol.toLowerCase()],
    [symbol.toLowerCase(), "weth"],
  ]),
  ...[...targets, "USDC"].map((symbol) => [symbol, symbol.toLowerCase()]),
  ...["", " ", null, undefined, 7, {}].flatMap((value) => [
    [value, "USDC"], ["USDC", value], [value, "ETH"], ["ETH", value],
  ]),
  ["USDT", "DAI"],
];

test("excluded, same-symbol and invalid sides fail closed without wallet access", async () => {
  const api = executor();
  for (const [tokenIn, tokenOut] of invalidPairs) {
    const label = `${String(tokenIn)} -> ${String(tokenOut)}`;
    assert.equal(api.isAutoTradeEligible(tokenIn, tokenOut), false, label);
    const result = await api.executeAutoSwap(params(tokenIn, tokenOut));
    assert.equal(result.success, false, label);
    assert.match(result.error, /auto-trade/i, label);
  }
  assert.deepEqual(api.calls, { providers: 0, wallet: [], signers: 0, contracts: 0 });
});

test("distinct target-to-target pairs remain eligible", () => {
  const api = executor();
  for (const tokenIn of targets) {
    for (const tokenOut of targets) {
      assert.equal(api.isAutoTradeEligible(tokenIn, tokenOut), tokenIn !== tokenOut);
    }
  }
});

test("Base allowed pair reaches only the mocked signer boundary", async () => {
  const api = executor(8453);
  const result = await api.executeAutoSwap(params("USDC", "VVV"));
  assert.equal(result.error, "TEST_SIGNER_BOUNDARY");
  assert.equal(api.calls.signers, 1);
  assert.equal(api.calls.contracts, 0);
});

async function pollHook(proposals, settings = {}, address = "test-wallet") {
  const swaps = [];
  const requests = [];
  let cleanup;
  let interval;
  const policy = executor();
  const hook = load("frontend/hooks/useAutoTrading.ts", {
    react: {
      useRef: (current) => ({ current }),
      useCallback: (fn) => fn,
      useEffect: (fn) => { cleanup = fn(); },
    },
    "../context/WalletContext": { useWallet: () => ({ address }) },
    "../constants/config": { BACKEND_URL: "http://test-backend" },
    "../context/SettingsContext": {
      useSettings: () => ({ autoTrading: true, network: "base", autoTradingInterval: 60, ...settings }),
    },
    "../lib/autoTradeExecutor": {
      ...policy,
      executeAutoSwap: async (args) => {
        swaps.push(args);
        return { success: true, txHash: "test-hash" };
      },
    },
  }, {
    process: { env: {} },
    fetch: async (url, options) => {
      requests.push({ url, options });
      return { ok: true, json: async () => proposals };
    },
    setInterval: (fn) => { interval = fn; return 1; },
    clearInterval() {},
  });
  hook.useAutoTrading();
  // Drain the initial asynchronous poll without timers, network, or real React mounting.
  await new Promise(setImmediate);
  const firstCount = swaps.length;
  if (interval) await interval();
  assert.equal(swaps.length, firstCount, "previously processed proposals must not replay");
  cleanup?.();
  return { swaps, requests };
}

const proposal = (token, action = "buy", overrides = {}) => ({
  id: `${token}-${action}`, token, action, amount: 2, price: 3,
  status: "pending", slippage: 0.5, timestamp: Date.now() / 1000, ...overrides,
});

test("hook skips excluded pending/old proposals but executes all seven USDC buys/sells", async () => {
  const allowed = targets.flatMap((token) => [proposal(token, "buy"), proposal(token.toLowerCase(), "sell")]);
  const blocked = [...excluded, "USDC"].flatMap((token) => [
    proposal(token), proposal(token.toLowerCase(), "sell"),
    proposal(token, "buy", { id: `${token}-old`, timestamp: 1 }),
  ]);
  const stale = proposal("VVV", "buy", { id: "stale-target", timestamp: 1 });
  const approved = proposal("AERO", "buy", { id: "approved", status: "approved" });
  const { swaps, requests } = await pollHook([...blocked, stale, approved, ...allowed]);
  assert.deepEqual(swaps.map(({ tokenIn, tokenOut }) => [tokenIn, tokenOut]),
    targets.flatMap((token) => [["USDC", token], [token.toLowerCase(), "USDC"]]));
  const completed = requests.filter(({ options }) => options?.method === "POST");
  assert.equal(completed.length, 14);
  assert.ok(completed.every(({ url }) => allowed.some(({ id }) => url.includes(`/proposals/${id}/complete`))));
  assert.ok(blocked.every((p) => p.status === "pending"), "manual-review proposals remain pending");
});

test("hook still requires Base, enabled automation and a connected wallet", async () => {
  for (const settings of [{ network: "mainnet" }, { network: "arbitrum" }, { network: "sepolia" }, { autoTrading: false }]) {
    assert.equal((await pollHook([proposal("ETH")], settings)).requests.length, 0);
  }
  assert.equal((await pollHook([proposal("ETH")], {}, null)).requests.length, 0);
});

test("Agents defaults preserve other monitoring and expose the shared settlement summary", () => {
  const ui = source("frontend/components/AgentsControlPanel.tsx");
  const match = ui.match(/\[tokensInput, setTokensInput\] = useState\("([^"]+)"\)/);
  assert.ok(match, "editable monitored defaults");
  const defaults = match[1].split(",").map((s) => s.trim()).sort();
  assert.deepEqual(defaults, [...targets, "SHIB", "DEGEN", "TOSHI", "AIXBT", "ARB"].sort());
  assert.match(ui, /AUTO_TRADE_TARGETS\.join\(", "\)/);
  assert.match(ui, /Base only/);
  assert.match(ui, /USDC[^<\n]*settlement/i);
  assert.match(ui, /onChange=\{\(e\) => setTokensInput\(e\.target\.value\)\}/);
  assert.match(ui, /monitored_tokens: tokensInput\.split\(","\)\.map\(t => t\.trim\(\)\)\.filter\(t => t\.length > 0\)/);
  assert.match(ui, /Review & Sign/);
});

test("hook uses the shared target list; newly allowed tokens gain no slippage floor", () => {
  assert.match(source("frontend/hooks/useAutoTrading.ts"), /AUTO_TRADE_TARGETS\.includes\(proposal\.token\.toUpperCase\(\)\)/);
  const executionSource = source("frontend/lib/autoTradeExecutor.ts");
  const volatile = executionSource.match(/const VOLATILE_TOKENS = (\[[^;]+\]);/);
  assert.ok(volatile);
  assert.deepEqual(JSON.parse(volatile[1]).filter((symbol) => targets.includes(symbol)), ["TIBBIR"]);
  assert.match(executionSource, /const MIN_SLIPPAGE_VOLATILE_PCT = 1\.0;/);
});
