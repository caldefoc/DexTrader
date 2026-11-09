import { BrowserProvider, Contract, parseUnits, MaxUint256, solidityPacked } from "ethers";
import { BASE_TOKENS, BASE_V3_ROUTER, BASE_V3_QUOTER } from "../constants/tokens";

export const AUTO_TRADE_TARGETS: readonly string[] = ["ETH", "WETH", "VVV", "VIRTUAL", "AERO", "TIBBIR", "AVNT"];
const BASE_CHAIN_ID = 8453;
const V3_FEE_TIERS = [100, 500, 3000, 10000]; // 0.01%, 0.05%, 0.3%, 1%
// High-liquidity intermediaries for multi-hop routing on Base
const BASE_INTERMEDIATE_SYMBOLS = ["WETH", "USDC", "AERO", "VIRTUAL", "CBBTC"];
// Volatile low-cap tokens need a slippage floor to avoid reverts during the
// MetaMask confirmation window (0.5% is too tight for these pairs)
const VOLATILE_TOKENS = ["DEGEN", "TIBBIR", "TOSHI", "BRETT", "FAI", "LUNA"];
const MIN_SLIPPAGE_VOLATILE_PCT = 1.0;

const decimalsCache: Record<string, number> = {};

async function getTokenDecimals(address: string, symbol: string, provider: BrowserProvider): Promise<number> {
  const key = address.toLowerCase();
  if (decimalsCache[key]) return decimalsCache[key];
  let decimals = symbol === "USDC" ? 6 : 18;
  try {
    const token = new Contract(address, ["function decimals() view returns (uint8)"], provider);
    decimals = Number(await token.decimals());
  } catch {
    // keep fallback
  }
  decimalsCache[key] = decimals;
  return decimals;
}

export interface AutoTradeParams {
  tokenIn: string;      // e.g. "USDC", "ETH", "DEGEN", ...
  tokenOut: string;     // e.g. "USDC", "ETH", "DEGEN", ...
  amountIn: string;     // human-readable amount
  slippage: string;     // e.g. "0.5"
  gasPriceGwei: string; // e.g. "0.01"
}

export interface AutoTradeResult {
  success: boolean;
  txHash?: string;
  error?: string;
}

/** Execute an automated swap on Base Uniswap V3. */
export async function executeAutoSwap(params: AutoTradeParams): Promise<AutoTradeResult> {
  try {
    if (!isAutoTradeEligible(params.tokenIn, params.tokenOut)) {
      return { success: false, error: `Auto-trade requires distinct symbols from ${AUTO_TRADE_TARGETS.join(", ")}, with USDC allowed only as settlement` };
    }

    if (typeof window === "undefined" || !(window as any).ethereum) {
      return { success: false, error: "No wallet available" };
    }

    const upperIn = params.tokenIn.toUpperCase();
    const upperOut = params.tokenOut.toUpperCase();
    const provider = new BrowserProvider((window as any).ethereum);
    const net = await provider.getNetwork();
    const chainId = Number(net.chainId);

    if (chainId !== BASE_CHAIN_ID) {
      return { success: false, error: `Auto-trade requires Base network (chainId ${BASE_CHAIN_ID}), got ${chainId}` };
    }

    const signer = await provider.getSigner();
    const signerAddress = await signer.getAddress();

    // Resolve addresses
    const inputIsEth = upperIn === "ETH";
    const outputIsEth = upperOut === "ETH";
    const inputAddress = inputIsEth ? BASE_TOKENS.WETH : BASE_TOKENS[upperIn];
    const outputAddress = outputIsEth ? BASE_TOKENS.WETH : BASE_TOKENS[upperOut];

    if (!inputAddress || !outputAddress) {
      return { success: false, error: `Token address not found for ${upperIn} or ${upperOut}` };
    }

    // Determine decimals (dynamic lookup with sensible fallbacks)
    const inputDecimals = inputIsEth ? 18 : await getTokenDecimals(inputAddress, upperIn, provider);

    // Parse amount
    const amountIn = parseUnits(params.amountIn, inputDecimals);

    // Get quote from V3 Quoter
    const quoter = new Contract(
      BASE_V3_QUOTER,
      [
        "function quoteExactInputSingle(tuple(address tokenIn, address tokenOut, uint256 amountIn, uint24 fee, uint160 sqrtPriceLimitX96) params) external returns (uint256 amountOut, uint160 sqrtPriceX96After, uint32 initializedTicksCrossed, uint256 gasEstimate)",
        "function quoteExactInput(bytes path, uint256 amountIn) external returns (uint256 amountOut, uint160[] sqrtPriceX96AfterList, uint32 initializedTicksCrossedList, uint256 gasEstimate)"
      ],
      provider
    );

    // 1) Try direct pools across all fee tiers, keep the best quote
    let bestOut = BigInt(0);
    let bestFee = 3000;
    let bestPath: string | null = null;

    for (const fee of V3_FEE_TIERS) {
      try {
        const quoteParams = {
          tokenIn: inputAddress,
          tokenOut: outputAddress,
          amountIn: amountIn,
          fee: fee,
          sqrtPriceLimitX96: 0
        };
        const quoteResult = await quoter.quoteExactInputSingle.staticCall(quoteParams);
        const out = quoteResult[0];
        if (out > bestOut) {
          bestOut = out;
          bestFee = fee;
          bestPath = null; // direct route
        }
      } catch {
        // Pool doesn't exist at this fee tier, try next
      }
    }

    // 2) If no direct pool, try multi-hop via high-liquidity intermediaries
    if (bestOut === BigInt(0)) {
      for (const symbol of BASE_INTERMEDIATE_SYMBOLS) {
        const intermediate = BASE_TOKENS[symbol];
        if (!intermediate) continue;
        if (intermediate.toLowerCase() === inputAddress.toLowerCase() ||
            intermediate.toLowerCase() === outputAddress.toLowerCase()) {
          continue;
        }

        for (const fee1 of V3_FEE_TIERS) {
          for (const fee2 of V3_FEE_TIERS) {
            try {
              const path = solidityPacked(
                ["address", "uint24", "address", "uint24", "address"],
                [inputAddress, fee1, intermediate, fee2, outputAddress]
              );
              const quoteResult = await quoter.quoteExactInput.staticCall(path, amountIn);
              const out = quoteResult[0];
              if (out > bestOut) {
                bestOut = out;
                bestPath = path;
              }
            } catch {
              // Route doesn't exist, try next
            }
          }
        }
      }
    }

    if (bestOut <= BigInt(0)) {
      return { success: false, error: `No liquidity route found for ${upperIn} -> ${upperOut} (direct + multi-hop)` };
    }

    console.log(`[AutoTrade] Route found: ${bestPath ? "multi-hop" : `direct (fee ${bestFee})`}`);

    // Calculate minOut with slippage (volatile low-caps get a higher floor)
    const requestedSlippage = parseFloat(params.slippage) || 0.5;
    const involvesVolatile = VOLATILE_TOKENS.includes(upperIn) || VOLATILE_TOKENS.includes(upperOut);
    const effectiveSlippage = involvesVolatile
      ? Math.max(requestedSlippage, MIN_SLIPPAGE_VOLATILE_PCT)
      : requestedSlippage;
    const slippageBps = BigInt(Math.floor(effectiveSlippage * 100));
    const minOut = bestOut - (bestOut * slippageBps) / BigInt(10000);

    // Handle approval for non-ETH inputs
    if (!inputIsEth) {
      const tokenContract = new Contract(
        inputAddress,
        [
          "function approve(address spender, uint256 amount) returns (bool)",
          "function allowance(address owner, address spender) view returns (uint256)"
        ],
        signer
      );

      const currentAllowance: bigint = await tokenContract.allowance(signerAddress, BASE_V3_ROUTER);
      if (currentAllowance < amountIn) {
        const approveTx = await tokenContract.approve(BASE_V3_ROUTER, MaxUint256, {
          gasLimit: BigInt(100000)
        });
        await approveTx.wait();
      }
    }

    // Execute swap via V3 Router
    const v3Router = new Contract(
      BASE_V3_ROUTER,
      [
        "function exactInputSingle(tuple(address tokenIn, address tokenOut, uint24 fee, address recipient, uint256 amountIn, uint256 amountOutMinimum, uint160 sqrtPriceLimitX96) params) external payable returns (uint256 amountOut)",
        "function exactInput(tuple(bytes path, address recipient, uint256 amountIn, uint256 amountOutMinimum) params) external payable returns (uint256 amountOut)"
      ],
      signer
    );

    const overrides: any = {
      gasLimit: bestPath ? BigInt(800000) : BigInt(500000), // multi-hop consumes more gas
    };

    if (inputIsEth) {
      overrides.value = amountIn;
    }

    // Gas price
    if (params.gasPriceGwei) {
      try {
        const gasWei = parseUnits(params.gasPriceGwei, "gwei");
        const feeData = await provider.getFeeData();
        if (feeData.maxFeePerGas) {
          // Never go below the network's suggested max fee: a maxFee under the
          // live requirement is unincludable on any path (mempool or wallet relay).
          overrides.maxFeePerGas = gasWei > feeData.maxFeePerGas ? gasWei : feeData.maxFeePerGas;
          overrides.maxPriorityFeePerGas = parseUnits("0.1", "gwei");
          if (overrides.maxPriorityFeePerGas > overrides.maxFeePerGas) {
            overrides.maxPriorityFeePerGas = overrides.maxFeePerGas;
          }
        } else {
          overrides.gasPrice = gasWei;
        }
      } catch (e) {
        console.warn("Invalid gas price for auto-trade, using default", e);
      }
    }

    // Do NOT pin a nonce: it breaks MetaMask's relay path (pay-gas-in-token /
    // EIP-7702 Gas Station -> FAILED_TIMEOUT). Ethers v6 populates it from the
    // network for normal transactions.

    let tx: any;
    try {
      if (bestPath) {
        // Multi-hop route
        tx = await v3Router.exactInput({
          path: bestPath,
          recipient: signerAddress,
          amountIn: amountIn,
          amountOutMinimum: minOut
        }, overrides);
      } else {
        // Direct route
        tx = await v3Router.exactInputSingle({
          tokenIn: inputAddress,
          tokenOut: outputAddress,
          fee: bestFee,
          recipient: signerAddress,
          amountIn: amountIn,
          amountOutMinimum: minOut,
          sqrtPriceLimitX96: 0
        }, overrides);
      }
    } catch (execErr: any) {
      if (execErr?.value?.hash) {
        tx = {
          hash: execErr.value.hash,
          wait: async () => provider.waitForTransaction(execErr.value.hash)
        };
      } else {
        throw execErr;
      }
    }

    await tx.wait();
    return { success: true, txHash: tx.hash };

  } catch (err: any) {
    console.error("Auto-trade execution failed:", err);
    return { success: false, error: err.message || "Unknown execution error" };
  }
}

/**
 * Check if a token pair is eligible for auto-trading.
 */
export function isAutoTradeEligible(tokenIn: string, tokenOut: string): boolean {
  if (typeof tokenIn !== "string" || typeof tokenOut !== "string") return false;
  const upperIn = tokenIn.toUpperCase();
  const upperOut = tokenOut.toUpperCase();
  const inputIsTarget = AUTO_TRADE_TARGETS.includes(upperIn);
  const outputIsTarget = AUTO_TRADE_TARGETS.includes(upperOut);
  return upperIn !== upperOut
    && (inputIsTarget || outputIsTarget)
    && (inputIsTarget || upperIn === "USDC")
    && (outputIsTarget || upperOut === "USDC");
}
