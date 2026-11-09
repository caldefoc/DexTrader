const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("../frontend/node_modules/typescript");

const source = fs.readFileSync(path.join(__dirname, "../frontend/constants/tokens.ts"), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const tokenModule = { exports: {} };
new Function("exports", compiled)(tokenModule.exports);
const { BASE_TOKENS, BASE_TOKEN_DECIMALS, MAINNET_TOKENS, ARBITRUM_TOKENS, SEPOLIA_TOKENS, getTokenAddress } = tokenModule.exports;

const expected = {
  ENA: "0x58538e6a46e07434d7e7375bc268d3cb839c0133",
  ICP: "0x00f3c42833c3170159af4e92dbb451fb3f708917",
  MORPHO: "0xbaa5cc21fd487b8fcc2f632f3f4e8d37262a0842",
  ETHFI: "0x6c240dda6b5c336df09a4d011139beaaa1ea2aa2",
  ZRO: "0x6985884c4392d348587b19cb9eaaf157f13271cd",
};

test("new manual tokens resolve to their verified Base contracts", () => {
  for (const [symbol, address] of Object.entries(expected)) {
    assert.equal(BASE_TOKENS[symbol]?.toLowerCase(), address, symbol);
    assert.equal(getTokenAddress(symbol.toLowerCase(), "base")?.toLowerCase(), address, symbol);
  }
});

test("new tokens are not enabled on other networks", () => {
  for (const symbol of Object.keys(expected)) {
    for (const tokens of [MAINNET_TOKENS, ARBITRUM_TOKENS, SEPOLIA_TOKENS]) {
      assert.equal(tokens[symbol], undefined, symbol);
    }
  }
});

test("verified decimal defaults preserve eight-decimal ICP amounts", () => {
  assert.equal(BASE_TOKEN_DECIMALS?.ICP, 8);
  for (const symbol of ["ENA", "MORPHO", "ETHFI", "ZRO"]) {
    assert.equal(BASE_TOKEN_DECIMALS[symbol], 18, symbol);
  }
});
