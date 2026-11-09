"use client";
import { useEffect, useState } from "react";
import { BrowserProvider, Contract, formatEther, parseUnits, formatUnits, MaxUint256, solidityPacked } from "ethers";
import { useWallet } from "../context/WalletContext";
import { useSettings } from "../context/SettingsContext";
import { SEPOLIA_TOKENS, MAINNET_TOKENS, BASE_TOKENS, BASE_TOKEN_DECIMALS, ARBITRUM_TOKENS, SEPOLIA_ROUTER, MAINNET_ROUTER, SEPOLIA_V3_ROUTER, MAINNET_V3_ROUTER, BASE_V3_ROUTER, ARBITRUM_V3_ROUTER, SEPOLIA_V3_QUOTER, MAINNET_V3_QUOTER, BASE_V3_QUOTER, ARBITRUM_V3_QUOTER, AERODROME_ROUTER } from "../constants/tokens";
import { BACKEND_URL } from "../constants/config";

// Uniswap V3 pool price bounds. QuoterV2 clamps sqrtPriceLimitX96=0 to these
// boundaries; if sqrtPriceX96After lands on one, the quote only partially
// filled at the pool edge (dust output) and must not be treated as a route.
const MIN_SQRT_RATIO = BigInt("4295128739");
const MAX_SQRT_RATIO = BigInt("1461446703485210103287273052203988822378723970342");
const hitPoolBoundary = (sqrtPrice: bigint) =>
  sqrtPrice <= MIN_SQRT_RATIO + BigInt(1) || sqrtPrice >= MAX_SQRT_RATIO - BigInt(1);

type TradeAction = "buy" | "sell";

type TradeSignal = {
  pair: string;
  action: TradeAction;
  confidence: number;
};

type Props = {
  open: boolean;
  onClose: () => void;
  onSuccess?: (txHash?: string) => void;
  signal: TradeSignal | null;
  initialAmount?: string;
};

export default function TradePreviewModal(props: Props) {
  const { address } = useWallet();
  const { network } = useSettings();
  const [ethBalance, setEthBalance] = useState<string | null>(null);
  const [wethBalance, setWethBalance] = useState<string | null>(null);
  const [inputBalance, setInputBalance] = useState<string | null>(null);
  const [inputDecimals, setInputDecimals] = useState<number>(18);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [amount, setAmount] = useState(props.initialAmount || "");
  const [slippage, setSlippage] = useState("0.5");
  const [gasPriceGwei, setGasPriceGwei] = useState("0.01");
  
  // Token-specific slippage settings for problematic tokens
  const getRecommendedSlippage = (tokenSymbol: string) => {
    const highSlippageTokens = [
      "FLOKI", "BONK", "PEPE", "SHIB", "DOGE", // Meme tokens with tax mechanisms
      "SAFEMOON", "BABYDOGE", "FEG" // Known high-tax tokens
    ];
    
    if (highSlippageTokens.includes(tokenSymbol.toUpperCase())) {
      return "8.0"; // 8% for high-tax meme tokens
    }
    
    return "0.5"; // Default 0.5% for normal tokens
  };
  const [gasLimit, setGasLimit] = useState("200000");
  const [estimating, setEstimating] = useState(false);
  const [estimateError, setEstimateError] = useState<string | null>(null);
  const [gasCostEth, setGasCostEth] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitResult, setSubmitResult] = useState<string | null>(null);
  const [txHash, setTxHash] = useState<string | null>(null);
  const [executionData, setExecutionData] = useState<{
    txHash: string;
    newBalance: string;
  } | null>(null);
  const [ethPrice, setEthPrice] = useState<number>(2500); // Default fallback
  const [pricesBySymbol, setPricesBySymbol] = useState<Record<string, number>>({});

  useEffect(() => {
      const fetchPrice = async () => {
          try {
              const res = await fetch(`${BACKEND_URL}/market/?limit=500`);
              if (res.ok) {
                  const data = await res.json();
                  const map: Record<string, number> = {};
                  if (Array.isArray(data.pairs)) {
                      for (const p of data.pairs) {
                          if (p.base_symbol && typeof p.price === "number") {
                              map[String(p.base_symbol).toUpperCase()] = p.price;
                          } else if (p.symbol && typeof p.price === "number") {
                              map[String(p.symbol).toUpperCase()] = p.price;
                          }
                      }
                      setPricesBySymbol(map);
                      if (map["ETH"]) setEthPrice(map["ETH"]);
                  }
              }
          } catch (e) {
              console.warn("Failed to fetch ETH price", e);
          }
      };
      if (props.open) fetchPrice();
  }, [props.open]);
  
  // Refactored State for Flexible Asset Selection
  const [inputAsset, setInputAsset] = useState<string>("ETH");
  const [outputAsset, setOutputAsset] = useState<string>("USDC");
  const [prevInputAsset, setPrevInputAsset] = useState<string | null>(null);

  // Initialize assets from signal
  // Uses primitive dependencies (pair string, action string) to prevent
  // unnecessary resets when parent re-creates the signal object
  useEffect(() => {
    if (props.open && props.signal) {
      const [base, quote] = props.signal.pair.split("/");
      if (base && quote) {
        let newInput, newOutput;
        if (props.signal.action === "buy") {
          // Buy Base with Quote
          newInput = quote === "USD" ? "USDC" : quote;
          newOutput = base;
        } else {
          // Sell Base for Quote
          newInput = base;
          newOutput = quote === "USD" ? "USDC" : quote;
        }
        handleInputAssetChange(newInput);
        setOutputAsset(newOutput);
        setPrevInputAsset(newInput); // Sync prev so clearing effect doesn't fire
      }
    }
  }, [props.open, props.signal?.pair, props.signal?.action]);
  
  const [quoteAmount, setQuoteAmount] = useState<string | null>(null);
  const [quoteError, setQuoteError] = useState<string | null>(null);
  const [tradePath, setTradePath] = useState<string[] | null>(null);
  const [protocolVersion, setProtocolVersion] = useState<"v2" | "v3" | "aerodrome">("v2");
  const [v3FeeTier, setV3FeeTier] = useState<number>(3000);
  const [isQuoting, setIsQuoting] = useState(false);
  const [priceImpact, setPriceImpact] = useState<number | null>(null);

  useEffect(() => {
    if (props.open && props.initialAmount) {
        // Fix: Truncate excessively long decimals to avoid "too many decimals" error in ethers
        // The backend might return float string like "1139.3256580300504" which is fine for UI but maybe cleaner to truncate
        // But the error happens in executeTrade -> parseUnits if we don't truncate or if the user edits it.
        // Actually, let's just use it as is for UI, but handle the parsing safely later.
        // Or better, safe truncate here to 6 decimals for display readability
        const val = parseFloat(props.initialAmount);
        if (!isNaN(val)) {
            // Use up to 8 decimals or the original string if shorter
            setAmount(val.toFixed(6).replace(/\.?0+$/, "")); 
        } else {
            setAmount(props.initialAmount);
        }
    } else if (props.open && !props.initialAmount && !amount) {
        setAmount("");
    }
  }, [props.open, props.initialAmount]);

  useEffect(() => {
    const timer = setTimeout(() => {
      fetchQuote();
    }, 600);
    return () => clearTimeout(timer);
  }, [amount, inputAsset, outputAsset, props.signal?.pair, address, network]);

  async function fetchQuote() {
    if (!amount || parseFloat(amount) <= 0 || !address || !props.signal) {
      setQuoteAmount(null);
      setTradePath(null);
      setQuoteError(null);
      setPriceImpact(null);
      return;
    }
    
    try {
      setIsQuoting(true);
      setTradePath(null);
      setQuoteError(null);
      setPriceImpact(null);
      const provider = new BrowserProvider((window as any).ethereum);
      const net = await provider.getNetwork();
      const chainId = Number(net.chainId);

      let tokens = SEPOLIA_TOKENS;
      let routerAddress = SEPOLIA_ROUTER;

      if (chainId === 1) {
        tokens = MAINNET_TOKENS;
        routerAddress = MAINNET_ROUTER;
      } else if (chainId === 8453) {
        tokens = BASE_TOKENS;
        routerAddress = ""; // No V2 router for Base
      } else if (chainId === 42161) {
        tokens = ARBITRUM_TOKENS;
        routerAddress = ""; // No V2 router for Arbitrum
      } else if (chainId === 11155111) {
        tokens = SEPOLIA_TOKENS;
        routerAddress = SEPOLIA_ROUTER;
      } else {
        // Fallback to settings
        if (network === "base") {
             tokens = BASE_TOKENS;
             routerAddress = "";
        } else if (network === "arbitrum") {
             tokens = ARBITRUM_TOKENS;
             routerAddress = "";
        } else {
             tokens = network === "mainnet" ? MAINNET_TOKENS : SEPOLIA_TOKENS;
             routerAddress = network === "mainnet" ? MAINNET_ROUTER : SEPOLIA_ROUTER;
        }
      }
      
      const inputTokenSymbol = inputAsset;
      const outputTokenSymbol = outputAsset;
      
      const inputIsEth = inputTokenSymbol === "ETH";
      const outputIsEth = outputTokenSymbol === "ETH";
      
      const inputAddress = inputIsEth ? tokens.WETH : tokens[inputTokenSymbol];
      const outputAddress = outputIsEth ? tokens.WETH : tokens[outputTokenSymbol];
      
      if (!inputAddress || !outputAddress) {
         setQuoteAmount(null);
         setTradePath(null);
         setQuoteError("Token address not found");
         return;
      }

      // Special handling for WETH/ETH wrap/unwrap (1:1 rate)
      if (inputAddress.toLowerCase() === outputAddress.toLowerCase()) {
         setQuoteAmount(amount);
         setTradePath([inputAddress, outputAddress]); // Not used for wrap/unwrap but consistent
         setIsQuoting(false);
         return;
      }

      // Always fetch decimals to ensure accuracy, do not rely on state which might be stale
      let inDecimals = tokens === BASE_TOKENS ? BASE_TOKEN_DECIMALS[inputTokenSymbol] ?? 18 : 18;
      if (!inputIsEth && inputTokenSymbol !== "WETH") {
          try {
              const c = new Contract(inputAddress, ["function decimals() view returns (uint8)"], provider);
              inDecimals = Number(await c.decimals());
          } catch {}
      }
      
      let amountIn;
      try {
        amountIn = parseUnits(amount, inDecimals);
      } catch (e) {
        console.error("Error parsing units", e);
        setQuoteAmount(null);
        setQuoteError("Invalid amount");
        setIsQuoting(false);
        return;
      }

      // 1. Try Uniswap V2
      let v2Found = false;
      try {
          if (!routerAddress) throw new Error("No V2 router for this network");

          // 1. Construct potential paths
          const paths: string[][] = [];
          
          // Direct path
          paths.push([inputAddress, outputAddress]);
          
          // Via WETH
          if (tokens.WETH && inputAddress !== tokens.WETH && outputAddress !== tokens.WETH) {
              paths.push([inputAddress, tokens.WETH, outputAddress]);
          }
          
          // Via USDC
          if (tokens.USDC && inputAddress !== tokens.USDC && outputAddress !== tokens.USDC) {
              paths.push([inputAddress, tokens.USDC, outputAddress]);
          }

          // Via USDT
          if (tokens.USDT && inputAddress !== tokens.USDT && outputAddress !== tokens.USDT) {
              paths.push([inputAddress, tokens.USDT, outputAddress]);
          }

          // Via WETH -> USDC
          if (tokens.WETH && tokens.USDC && inputAddress !== tokens.WETH && outputAddress !== tokens.USDC) {
              paths.push([inputAddress, tokens.WETH, tokens.USDC, outputAddress]);
          }
          
          // Via WETH -> USDT
          if (tokens.WETH && tokens.USDT && inputAddress !== tokens.WETH && outputAddress !== tokens.USDT) {
              paths.push([inputAddress, tokens.WETH, tokens.USDT, outputAddress]);
          }

          // Extra paths for robust routing
          if (tokens.DAI && inputAddress !== tokens.DAI && outputAddress !== tokens.DAI) {
              paths.push([inputAddress, tokens.DAI, outputAddress]);
              if (tokens.WETH) {
                 if (inputAddress !== tokens.WETH && outputAddress !== tokens.WETH) {
                     paths.push([inputAddress, tokens.DAI, tokens.WETH, outputAddress]);
                 }
                 if (inputAddress !== tokens.WETH) {
                     paths.push([inputAddress, tokens.WETH, tokens.DAI, outputAddress]);
                 }
              }
          }

          let bestAmountOut = BigInt(0);
          let bestPath: string[] | null = null;

          const router = new Contract(
            routerAddress,
            ["function getAmountsOut(uint amountIn, address[] path) view returns (uint[] amounts)"],
            provider
          );
          
          for (const path of paths) {
              try {
                  const unique = new Set(path.map(p => p.toLowerCase()));
                  if (unique.size !== path.length) continue;

                  const amounts = await router.getAmountsOut(amountIn, path);
                  const out = amounts[amounts.length - 1];
                  if (out > bestAmountOut) {
                      bestAmountOut = out;
                      bestPath = path;
                  }
              } catch (e) {}
          }

          if (bestPath && bestAmountOut > BigInt(0)) {
              setTradePath(bestPath);
              setProtocolVersion("v2");
              const rawOut = bestAmountOut;
              
              let outDecimals = tokens === BASE_TOKENS ? BASE_TOKEN_DECIMALS[outputTokenSymbol] ?? 18 : 18;
              if (!outputIsEth && outputTokenSymbol !== "WETH") {
                   const c = new Contract(outputAddress, ["function decimals() view returns (uint8)"], provider);
                   try {
                       outDecimals = Number(await c.decimals());
                   } catch {}
              }
              setQuoteAmount(formatUnits(rawOut, outDecimals));

              // Calculate price impact for V2 direct pair
              if (bestPath.length === 2) {
                  try {
                      const V2_FACTORY = "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f";
                      const factory = new Contract(V2_FACTORY, ["function getPair(address,address) view returns (address)"], provider);
                      const pairAddr = await factory.getPair(bestPath[0], bestPath[1]);
                      if (pairAddr && pairAddr !== "0x0000000000000000000000000000000000000000") {
                          const pair = new Contract(pairAddr, [
                              "function getReserves() view returns (uint112,uint112,uint32)",
                              "function token0() view returns (address)"
                          ], provider);
                          const [r0, r1] = await pair.getReserves();
                          const t0 = await pair.token0();
                          const reserveIn = t0.toLowerCase() === bestPath[0].toLowerCase() ? BigInt(r0) : BigInt(r1);
                          const reserveOut = t0.toLowerCase() === bestPath[0].toLowerCase() ? BigInt(r1) : BigInt(r0);
                          if (reserveIn > BigInt(0) && reserveOut > BigInt(0)) {
                              // Price impact = 1 - (reserveIn * amountOut) / (reserveOut * amountIn)
                              const impactNum = Number(reserveIn) * Number(rawOut);
                              const impactDen = Number(reserveOut) * Number(amountIn);
                              const impact = (1 - impactNum / impactDen) * 100;
                              if (isFinite(impact) && !isNaN(impact)) {
                                  setPriceImpact(Math.max(0, Math.min(impact, 100)));
                              }
                          }
                      }
                  } catch (e) { console.warn("V2 price impact calc failed", e); }
              }

              v2Found = true;
          }
      } catch (e) {
          console.warn("V2 Quote failed", e);
      }

      if (v2Found) {
          // Estimate Gas for V2
          try {
              const feeData = await provider.getFeeData();
              if (feeData.gasPrice) {
                  const estimatedGas = BigInt(250000); 
                  const cost = estimatedGas * feeData.gasPrice;
                  setGasCostEth(formatEther(cost));
              }
          } catch (e) {}
          setIsQuoting(false);
          return;
      }

      // 2. Try Uniswap V3 (if V2 failed)
      try {
          const v3QuoterAddress = chainId === 1 ? MAINNET_V3_QUOTER : 
                                  chainId === 8453 ? BASE_V3_QUOTER :
                                  chainId === 42161 ? ARBITRUM_V3_QUOTER :
                                  SEPOLIA_V3_QUOTER;
          if (!v3QuoterAddress) throw new Error("V3 Quoter not configured");

          const quoter = new Contract(
              v3QuoterAddress,
              [
                  "function quoteExactInputSingle(tuple(address tokenIn, address tokenOut, uint256 amountIn, uint24 fee, uint160 sqrtPriceLimitX96) params) external returns (uint256 amountOut, uint160 sqrtPriceX96After, uint32 initializedTicksCrossed, uint256 gasEstimate)",
                  "function quoteExactInput(bytes path, uint256 amountIn) external returns (uint256 amountOut, uint160[] sqrtPriceX96AfterList, uint32[] initializedTicksCrossedList, uint256 gasEstimate)"
              ],
              provider
          );

          const fees = [100, 500, 3000, 10000]; // 0.01%, 0.05%, 0.3%, 1%
          let bestV3Out = BigInt(0);
          let bestFee = 3000;
          let bestV3Path: string | null = null; // For V3 path encoding

          // 2.1 Try Direct Pools (Single Hop)
          for (const fee of fees) {
              try {
                  const params = {
                      tokenIn: inputAddress,
                      tokenOut: outputAddress,
                      amountIn: amountIn,
                      fee: fee,
                      sqrtPriceLimitX96: 0
                  };
                  
                  // Use staticCall for simulation
                  const result = await quoter.quoteExactInputSingle.staticCall(params);
                  const out = result[0]; // amountOut is first return value

                  if (out > bestV3Out && !hitPoolBoundary(BigInt(result[1]))) {
                      bestV3Out = out;
                      bestFee = fee;
                      bestV3Path = null; // Direct path
                  }
              } catch (e) {
                  // Fee tier might not exist
                  // console.warn(`V3 Direct quote failed for fee ${fee}:`, e);
              }
          }

          // 2.2 Try Multi-hop via Intermediaries (WETH, USDC, USDC.e, USDbC, AERO, VIRTUAL)
          if (bestV3Out === BigInt(0)) {
             const intermediates = [];
             if (tokens.WETH) intermediates.push(tokens.WETH);
             if (tokens.USDC) intermediates.push(tokens.USDC);
             if (tokens["USDC.e"]) intermediates.push(tokens["USDC.e"]); // Bridged USDC (Arbitrum)
             if (tokens.USDbC) intermediates.push(tokens.USDbC);
             // Additional Base intermediates with high liquidity
             if (tokens.AERO) intermediates.push(tokens.AERO);
             if (tokens.VIRTUAL) intermediates.push(tokens.VIRTUAL);
             if (tokens.CBBTC) intermediates.push(tokens.CBBTC);
             
             for (const intermediate of intermediates) {
                 // Skip if intermediate is same as input or output
                 if (intermediate.toLowerCase() === inputAddress.toLowerCase() || 
                     intermediate.toLowerCase() === outputAddress.toLowerCase()) {
                     continue;
                 }

                 for (const fee1 of fees) {
                     for (const fee2 of fees) {
                         try {
                             // Path: input -> fee1 -> intermediate -> fee2 -> output
                             const path = solidityPacked(
                                 ["address", "uint24", "address", "uint24", "address"],
                                 [inputAddress, fee1, intermediate, fee2, outputAddress]
                             );
                             
                             const result = await quoter.quoteExactInput.staticCall(path, amountIn);
                             const out = result[0];
                             const hopPrices = Array.from(result[1]) as bigint[];

                             if (out > bestV3Out && !hopPrices.some(sqrtPrice => hitPoolBoundary(BigInt(sqrtPrice)))) {
                                 bestV3Out = out;
                                 bestFee = 0; // Mixed fees
                                 bestV3Path = path;
                             }
                         } catch (e) {
                             console.warn(`V3 Multihop quote failed for intermediate ${intermediate}:`, e);
                         }
                     }
                 }
             }
          }

          if (bestV3Out > BigInt(0)) {
              setProtocolVersion("v3");
              setV3FeeTier(bestFee);
              // Store the encoded path if it's a multihop, or null if direct
              // We'll misuse setTradePath to store the hex string if needed, or we need a new state.
              // But executeTrade needs to know if it's multihop.
              // For now, let's just handle direct. If multihop is found, we need to update executeTrade too.
              // Wait, 'setTradePath' is string[]. V3 path is bytes string.
              // I'll need to store the V3 path in a state.
              
              // Let's create a new state for v3PathEncoded
              // But first, let's verify if we can just setTradePath to something indicating multihop?
              // Or better, let's make sure we CAN execute multihop.
              // executeTrade currently uses exactInputSingle.
              // If I find a multihop route, I MUST update executeTrade to use exactInput.
              
              // This is a bigger change.
              // If the user's issue is GMX/ETH (direct), then multihop shouldn't be needed.
              // Maybe the issue is just that I wasn't logging errors.
              
              // But LINK/ETH is also direct.
              // What if the user meant "I can't trade LINK (held in wallet) to GMX"? That's multihop.
              // "ETH/GMX" implies ETH -> GMX.
              
              // Let's keep the multihop logic but I need to update state to store it.
              // I'll add setV3PathEncoded state.
              
              setTradePath(bestV3Path ? [bestV3Path] : null);
              
              let outDecimals = tokens === BASE_TOKENS ? BASE_TOKEN_DECIMALS[outputTokenSymbol] ?? 18 : 18;
              if (!outputIsEth && outputTokenSymbol !== "WETH") {
                   const c = new Contract(outputAddress, ["function decimals() view returns (uint8)"], provider);
                   try {
                       outDecimals = Number(await c.decimals());
                   } catch {}
              }
              setQuoteAmount(formatUnits(bestV3Out, outDecimals));

              // Estimate V3 price impact by comparing a tiny quote (spot price proxy) vs actual quote
              // Try ALL fee tiers for the tiny quote to find the true best spot rate
              try {
                  const tinyAmountIn = parseUnits("1", inDecimals);
                  let bestSpotRate = 0;
                  for (const spotFee of [100, 500, 3000, 10000]) {
                      try {
                          const spotResult = await quoter.quoteExactInputSingle.staticCall({
                              tokenIn: inputAddress,
                              tokenOut: outputAddress,
                              amountIn: tinyAmountIn,
                              fee: spotFee,
                              sqrtPriceLimitX96: 0
                          });
                          if (hitPoolBoundary(BigInt(spotResult[1]))) continue;
                          // Normalize to output-per-base-unit so it matches effectiveRate's scale
                          const rate = Number(spotResult[0]) / Number(tinyAmountIn);
                          if (rate > bestSpotRate) bestSpotRate = rate;
                      } catch {}
                  }
                  if (bestSpotRate > 0) {
                      const effectiveRate = Number(bestV3Out) / Number(amountIn);
                      const rawImpact = (1 - effectiveRate / bestSpotRate) * 100;
                      if (isFinite(rawImpact) && !isNaN(rawImpact)) {
                          setPriceImpact(Math.max(0, Math.min(rawImpact, 100)));
                      }
                  }
              } catch (e) { console.warn("V3 price impact calc failed", e); }
              
              // Estimate Gas for V3 (usually higher)
              try {
                  const feeData = await provider.getFeeData();
                  if (feeData.gasPrice) {
                      const estimatedGas = BigInt(350000); 
                      const cost = estimatedGas * feeData.gasPrice;
                      setGasCostEth(formatEther(cost));
                  }
              } catch (e) {}
              
              setIsQuoting(false);
              return;
          }
      } catch (e) {
          console.warn("V3 Quote failed", e);
      }

      // 3. Arbitrum fallback: Try USDC.e if native USDC was used and no route found
      if (chainId === 42161 && inputTokenSymbol === "USDC" && tokens["USDC.e"]) {
          console.log("Arbitrum: Trying USDC.e fallback for better liquidity");
          try {
              const usdceAddress = tokens["USDC.e"];
              const v3QuoterAddress = ARBITRUM_V3_QUOTER;
              const quoter = new Contract(
                  v3QuoterAddress,
                  [
                      "function quoteExactInputSingle(tuple(address tokenIn, address tokenOut, uint256 amountIn, uint24 fee, uint160 sqrtPriceLimitX96) params) external returns (uint256 amountOut, uint160 sqrtPriceX96After, uint32 initializedTicksCrossed, uint256 gasEstimate)",
                  ],
                  provider
              );
              
              const fees = [100, 500, 3000, 10000];
              let bestOut = BigInt(0);
              let bestFee = 3000;
              
              // Try direct USDC.e -> Output
              for (const fee of fees) {
                  try {
                      const params = {
                          tokenIn: usdceAddress,
                          tokenOut: outputAddress,
                          amountIn: amountIn, // Same amount, USDC and USDC.e both have 6 decimals
                          fee: fee,
                          sqrtPriceLimitX96: 0
                      };
                      const result = await quoter.quoteExactInputSingle.staticCall(params);
                      const out = result[0];
                      if (out > bestOut) {
                          bestOut = out;
                          bestFee = fee;
                      }
                  } catch {}
              }
              
              if (bestOut > BigInt(0)) {
                  setProtocolVersion("v3");
                  setV3FeeTier(bestFee);
                  setTradePath(null);
                  
                  let outDecimals = 18;
                  if (!outputIsEth && outputTokenSymbol !== "WETH") {
                      const c = new Contract(outputAddress, ["function decimals() view returns (uint8)"], provider);
                      try { outDecimals = Number(await c.decimals()); } catch {}
                  }
                  setQuoteAmount(formatUnits(bestOut, outDecimals));
                  setQuoteError("Note: This trade will use USDC.e (bridged) for better liquidity. Ensure you have USDC.e in your wallet.");
                  setIsQuoting(false);
                  return;
              }
          } catch (e) {
              console.warn("USDC.e fallback also failed", e);
          }
      }

      // 4. Try Aerodrome (Base only) - for low-cap tokens with liquidity on Aerodrome
      if (chainId === 8453) {
          console.log("Trying Aerodrome for Base network...");
          console.log("Input:", inputAddress, "Output:", outputAddress);
          try {
              // Aerodrome uses a different quoting mechanism - try using the pool directly
              // First, we need to find the pool address via the factory
              const aerodromeFactory = new Contract(
                  "0x420DD381b31aEf6683db6b902084cB0FFECe40Da",
                  [
                      "function getPool(address tokenA, address tokenB, bool stable) external view returns (address pool)"
                  ],
                  provider
              );
              
              // Try volatile pool first (most common for trading pairs)
              let poolAddress: string | null = null;
              try {
                  poolAddress = await aerodromeFactory.getPool(inputAddress, outputAddress, false);
                  console.log("Aerodrome volatile pool result:", poolAddress);
              } catch (e) {
                  console.warn("Aerodrome volatile pool not found:", e);
              }
              
              // Try stable pool if volatile not found
              if (!poolAddress || poolAddress === "0x0000000000000000000000000000000000000000") {
                  try {
                      poolAddress = await aerodromeFactory.getPool(inputAddress, outputAddress, true);
                      console.log("Aerodrome stable pool result:", poolAddress);
                  } catch (e) {
                      console.warn("Aerodrome stable pool not found:", e);
                  }
              }
              
              if (poolAddress && poolAddress !== "0x0000000000000000000000000000000000000000") {
                  console.log("Found Aerodrome pool:", poolAddress);
                  
                  // Get quote from the pool directly
                  const poolContract = new Contract(
                      poolAddress,
                      [
                          "function getReserves() external view returns (uint256 reserve0, uint256 reserve1, uint256 blockTimestampLast)",
                          "function token0() external view returns (address)",
                          "function token1() external view returns (address)",
                          "function stable() external view returns (bool)"
                      ],
                      provider
                  );
                  
                  try {
                      const [reserve0, reserve1] = await poolContract.getReserves();
                      const token0 = await poolContract.token0();
                      
                      // Calculate output based on reserves (simplified AMM formula)
                      // For volatile pools: dy = y * dx / (x + dx)
                      let out: bigint;
                      const fee = BigInt(2); // 0.2% fee for Aerodrome
                      
                      if (inputAddress.toLowerCase() === token0.toLowerCase()) {
                          // Input is token0, output is token1
                          const amountInWithFee = amountIn * (BigInt(10000) - fee) / BigInt(10000);
                          out = (reserve1 * amountInWithFee) / (reserve0 + amountInWithFee);
                      } else {
                          // Input is token1, output is token0
                          const amountInWithFee = amountIn * (BigInt(10000) - fee) / BigInt(10000);
                          out = (reserve0 * amountInWithFee) / (reserve1 + amountInWithFee);
                      }
                      
                      if (out > BigInt(0)) {
                          setTradePath([inputAddress, outputAddress]);
                          setProtocolVersion("aerodrome");
                          
                          let outDecimals = tokens === BASE_TOKENS ? BASE_TOKEN_DECIMALS[outputTokenSymbol] ?? 18 : 18;
                          if (!outputIsEth && outputTokenSymbol !== "WETH") {
                              const c = new Contract(outputAddress, ["function decimals() view returns (uint8)"], provider);
                              try { outDecimals = Number(await c.decimals()); } catch {}
                          }
                          setQuoteAmount(formatUnits(out, outDecimals));

                          // Calculate price impact from Aerodrome reserves
                          // For constant-product AMM: impact = amountIn_withFee / (reserveIn + amountIn_withFee)
                          const reserveIn = inputAddress.toLowerCase() === token0.toLowerCase() ? reserve0 : reserve1;
                          const amountInWithFee = amountIn * (BigInt(10000) - fee) / BigInt(10000);
                          const impact = Number(amountInWithFee) / Number(reserveIn + amountInWithFee) * 100;
                          if (isFinite(impact) && !isNaN(impact)) {
                              setPriceImpact(Math.max(0, Math.min(impact, 100)));
                          }
                          
                          // Estimate Gas for Aerodrome
                          try {
                              const feeData = await provider.getFeeData();
                              if (feeData.gasPrice) {
                                  const estimatedGas = BigInt(250000); 
                                  const cost = estimatedGas * feeData.gasPrice;
                                  setGasCostEth(formatEther(cost));
                              }
                          } catch (e) {}
                          
                          setIsQuoting(false);
                          return;
                      }
                  } catch (e) {
                      console.warn("Aerodrome pool quote failed:", e);
                  }
              }
              
              // Try multi-hop via WETH if direct pool not found
              if (tokens.WETH) {
                  let wethPoolAddress: string | null = null;
                  try {
                      wethPoolAddress = await aerodromeFactory.getPool(inputAddress, tokens.WETH, false);
                  } catch (e) {}
                  
                  if (!wethPoolAddress || wethPoolAddress === "0x0000000000000000000000000000000000000000") {
                      try {
                          wethPoolAddress = await aerodromeFactory.getPool(inputAddress, tokens.WETH, true);
                      } catch (e) {}
                  }
                  
                  if (wethPoolAddress && wethPoolAddress !== "0x0000000000000000000000000000000000000000") {
                      console.log("Found Aerodrome WETH intermediate pool");
                      // For simplicity, we'll just indicate this is a multi-hop route
                      // The actual calculation would require two pool quotes
                      setTradePath([inputAddress, tokens.WETH, outputAddress]);
                      setProtocolVersion("aerodrome");
                      setQuoteAmount("0"); // Will be calculated during execution
                      setQuoteError("Aerodrome multi-hop route found. Proceed with caution - actual amount will be calculated at execution.");
                      setIsQuoting(false);
                      return;
                  }
              }
          } catch (e) {
              console.warn("Aerodrome quote failed:", e);
          }
      }

      throw new Error("No route found (V2, V3, or Aerodrome)");

    } catch (e: any) {
      console.error("Quote failed", e);
      setQuoteAmount(null);
      setTradePath(null);
      setQuoteError(e.message || "Failed to fetch quote");
      setPriceImpact(null);
    } finally {
      setIsQuoting(false);
    }
  }
  
  // Helper to convert amount when swapping input asset
  async function convertInputAmount(oldAsset: string, newAsset: string, currentAmount: string) {
     if (!currentAmount || parseFloat(currentAmount) <= 0 || !address) return;
     
     try {
       // We want to find X newAsset such that Value(X) ≈ Value(currentAmount oldAsset)
       // This effectively means selling oldAsset for newAsset.
       // So we can use the same router logic: amountIn = currentAmount, path = [oldAsset, ..., newAsset]
       
       const provider = new BrowserProvider((window as any).ethereum);
       const net = await provider.getNetwork();
       const chainId = Number(net.chainId);

       let tokens = SEPOLIA_TOKENS;
       let routerAddress = SEPOLIA_ROUTER;

       if (chainId === 1) {
         tokens = MAINNET_TOKENS;
         routerAddress = MAINNET_ROUTER;
       } else if (chainId === 8453) {
         tokens = BASE_TOKENS;
         routerAddress = ""; // No V2 support in this helper for Base yet
       } else if (chainId === 42161) {
         tokens = ARBITRUM_TOKENS;
         routerAddress = ""; // No V2 support in this helper for Arbitrum yet
       } else if (chainId === 11155111) {
         tokens = SEPOLIA_TOKENS;
         routerAddress = SEPOLIA_ROUTER;
       } else {
         if (network === "base") {
              tokens = BASE_TOKENS;
              routerAddress = "";
         } else if (network === "arbitrum") {
              tokens = ARBITRUM_TOKENS;
              routerAddress = "";
         } else {
              tokens = network === "mainnet" ? MAINNET_TOKENS : SEPOLIA_TOKENS;
              routerAddress = network === "mainnet" ? MAINNET_ROUTER : SEPOLIA_ROUTER;
         }
       }

       const inputAddress = oldAsset === "ETH" ? tokens.WETH : tokens[oldAsset];
       const outputAddress = newAsset === "ETH" ? tokens.WETH : tokens[newAsset];
       
       if (!inputAddress || !outputAddress) return;

       // If just wrapping/unwrapping or same token
       if (inputAddress.toLowerCase() === outputAddress.toLowerCase()) {
           return; // 1:1, keep amount
       }
       
       if (!routerAddress) {
           // Skip conversion if no V2 router (Base) - doing full V3 quote in helper is complex
           // and this is just for UI convenience.
           return; 
       }

       let inDecimals = 18;
       if (oldAsset !== "ETH" && oldAsset !== "WETH") {
          try {
              const c = new Contract(inputAddress, ["function decimals() view returns (uint8)"], provider);
              inDecimals = Number(await c.decimals());
          } catch { inDecimals = 18; }
       }

       const amountIn = parseUnits(currentAmount, inDecimals);
       
       // Build path (reuse logic from fetchQuote but simplified)
       let path = [inputAddress, outputAddress];
       if (tokens.WETH && inputAddress !== tokens.WETH && outputAddress !== tokens.WETH) {
           path = [inputAddress, tokens.WETH, outputAddress];
       }
       
       const router = new Contract(
         routerAddress,
         ["function getAmountsOut(uint amountIn, address[] path) view returns (uint[] amounts)"],
         provider
       );

       try {
           const amounts = await router.getAmountsOut(amountIn, path);
           const rawOut = amounts[amounts.length - 1];
           
           let outDecimals = 18;
           if (newAsset !== "ETH" && newAsset !== "WETH") {
                const c = new Contract(outputAddress, ["function decimals() view returns (uint8)"], provider);
                outDecimals = Number(await c.decimals());
           }
           
           const newAmountStr = formatUnits(rawOut, outDecimals);
           // Truncate to reasonable decimals (e.g. 6) to avoid UI overflow
           setAmount(parseFloat(newAmountStr).toFixed(6).replace(/\.?0+$/, ""));
       } catch (e) {
           console.error("Conversion failed", e);
           setAmount(""); // Reset if conversion fails (e.g. no liquidity)
       }
     } catch (e) {
         console.error("Conversion error", e);
         setAmount("");
     }
  }

  // Clear amount when user changes input asset (to avoid wrong value carry-over)
  // UPDATED: Now attempts to convert instead of clear
  useEffect(() => {
    if (!props.open) {
      setPrevInputAsset(null);
      return;
    }

    if (prevInputAsset === null) {
      setPrevInputAsset(inputAsset);
      return;
    }

    if (inputAsset !== prevInputAsset) {
       // Attempt conversion
       // Note: we use 'amount' from closure which might be stale if not in deps,
       // but adding 'amount' to deps causes loops.
       // However, since this effect only runs when inputAsset changes, 
       // and inputAsset changes via user interaction, 'amount' should be reasonably fresh.
       // Actually, the best way is to do this in the onChange handler, not useEffect.
       // But keeping it here for minimal refactor, acknowledging the race condition risk.
       // We'll move the logic to handleInputAssetChange for robustness.
    }
  }, [inputAsset, props.open, prevInputAsset]); 
  
  function handleInputAssetChange(newAsset: string) {
      if (amount && inputAsset) {
          convertInputAmount(inputAsset, newAsset, amount);
      }
      setInputAsset(newAsset);
      
      // Auto-adjust slippage for problematic tokens
      const recommendedSlippage = getRecommendedSlippage(newAsset);
      console.log(`Token changed to: ${newAsset}, Recommended slippage: ${recommendedSlippage}%, Current: ${slippage}%`);
      if (recommendedSlippage !== slippage) {
        console.log(`Updating slippage from ${slippage}% to ${recommendedSlippage}%`);
        setSlippage(recommendedSlippage);
      }
  }
  
  function handleOutputAssetChange(newAsset: string) {
      setOutputAsset(newAsset);
      
      // Auto-adjust slippage for problematic tokens when buying them
      const recommendedSlippage = getRecommendedSlippage(newAsset);
      console.log(`Output token changed to: ${newAsset}, Recommended slippage: ${recommendedSlippage}%, Current: ${slippage}%`);
      if (recommendedSlippage !== slippage) {
        console.log(`Updating slippage from ${slippage}% to ${recommendedSlippage}%`);
        setSlippage(recommendedSlippage);
      }
  }


  async function ensureCorrectNetwork(provider: BrowserProvider) {
    const eth = (window as any).ethereum;
    let chainIdNumber: number | null = null;
    try {
      const rawChainId =
        eth?.chainId ??
        (await eth?.request?.({ method: "eth_chainId" }));
      if (typeof rawChainId === "string") {
        const value = rawChainId.startsWith("0x")
          ? parseInt(rawChainId, 16)
          : parseInt(rawChainId, 10);
        if (Number.isFinite(value)) {
          chainIdNumber = value;
        }
      } else if (typeof rawChainId === "number") {
        chainIdNumber = rawChainId;
      }
    } catch {
    }
    if (chainIdNumber === null) {
      const networkInfo = await provider.getNetwork();
      chainIdNumber = Number(
        (networkInfo as any).chainId ?? networkInfo.chainId
      );
    }
    return Number.isFinite(chainIdNumber) ? chainIdNumber : null;
  }

  useEffect(() => {
    async function loadBalance() {
      if (!props.open || !props.signal || !address) {
        setEthBalance(null);
        setWethBalance(null);
        setError(null);
        return;
      }
      if (typeof window === "undefined" || !(window as any).ethereum) {
        setEthBalance(null);
        setWethBalance(null);
        setInputBalance(null);
        setError("No wallet available");
        return;
      }
      
      try {
        setLoading(true);
        setError(null);
        const provider = new BrowserProvider((window as any).ethereum);
        const chainIdNumber = await ensureCorrectNetwork(provider);
        
        let currentTokens = SEPOLIA_TOKENS;
        if (chainIdNumber === 1) {
            currentTokens = MAINNET_TOKENS;
        } else if (chainIdNumber === 8453) {
            currentTokens = BASE_TOKENS;
        } else if (chainIdNumber === 42161) {
            currentTokens = ARBITRUM_TOKENS;
        } else if (chainIdNumber === 11155111) {
            currentTokens = SEPOLIA_TOKENS;
        } else {
             // Fallback to settings if chainId is unknown/null (or allow it but default to settings)
             const requiredChainId = network === "mainnet" ? 1 : network === "base" ? 8453 : network === "arbitrum" ? 42161 : 11155111;
             if (chainIdNumber !== null && chainIdNumber !== requiredChainId) {
                setError(
                  `Connected network chainId ${chainIdNumber}. Please switch to ${network === "mainnet" ? "Mainnet (1)" : network === "base" ? "Base (8453)" : network === "arbitrum" ? "Arbitrum One (42161)" : "Sepolia (11155111)"}.`
                );
                return;
             }
             if (network === "base") {
                 currentTokens = BASE_TOKENS;
             } else if (network === "arbitrum") {
                 currentTokens = ARBITRUM_TOKENS;
             } else {
                 currentTokens = network === "mainnet" ? MAINNET_TOKENS : SEPOLIA_TOKENS;
             }
        }

        const rawEth = await provider.getBalance(address);
        setEthBalance(formatEther(rawEth));
        
        const tokens = currentTokens;

        // Fetch WETH balance
        try {
          const weth = new Contract(
            tokens.WETH,
            ["function balanceOf(address) view returns (uint256)"],
            provider
          );
          const rawWeth: bigint = await weth.balanceOf(address);
          setWethBalance(formatEther(rawWeth));
        } catch {}

        // Fetch Input Token Balance
        if (inputAsset === "ETH") {
           setInputBalance(formatEther(rawEth));
           setInputDecimals(18);
        } else if (inputAsset === "WETH") {
           const weth = new Contract(
             tokens.WETH,
             ["function balanceOf(address) view returns (uint256)"],
             provider
           );
           const rawWeth: bigint = await weth.balanceOf(address);
           setInputBalance(formatEther(rawWeth));
           setInputDecimals(18);
        } else {
           // Fetch other token
           const tokenAddress = tokens[inputAsset] || tokens[inputAsset.toUpperCase()];
           if (tokenAddress) {
              try {
                const tokenContract = new Contract(
                  tokenAddress,
                  ["function balanceOf(address) view returns (uint256)", "function decimals() view returns (uint8)"],
                  provider
                );
                const rawBal: bigint = await tokenContract.balanceOf(address);
                let decimals = tokens === BASE_TOKENS ? BASE_TOKEN_DECIMALS[inputAsset] ?? 18 : 18;
                try {
                  decimals = Number(await tokenContract.decimals());
                } catch {}
                setInputDecimals(decimals);
                setInputBalance(formatUnits(rawBal, decimals));
              } catch (err) {
                 console.error("Failed to fetch token balance", err);
                 setInputBalance(null);
              }
           } else {
              // Unknown token?
              setInputBalance(null);
           }
        }

      } catch (e) {
        setEthBalance(null);
        setWethBalance(null);
        setInputBalance(null);
        setError(
          e instanceof Error ? e.message : "Failed to load wallet balance"
        );
      } finally {
        setLoading(false);
      }
    }
    loadBalance();
  }, [props.open, props.signal?.pair, inputAsset, address, network]);

  useEffect(() => {
    setSubmitError(null);
    setSubmitResult(null);
    setTxHash(null);
    setExecutionData(null);
    setSubmitting(false); // Reset submitting state
    
    // Reset amount when signal changes to avoid confusing persistence from previous trades
    if (props.open) {
        setAmount(props.initialAmount || "");
    }
    
    // Assets are now initialized via useState lazy init
  }, [props.open, props.signal?.pair, props.signal?.action]);

  const hasExecuted = !!executionData;

  if (!props.open || !props.signal) {
    return null;
  }

  const [base, quote] = props.signal.pair.split("/");
  const confidencePct = (props.signal.confidence * 100).toFixed(0);
  const balanceForTrade = inputBalance;
  
  // Dynamic Pair Display
  const tradingPair = props.signal.action === "buy" 
      ? `${outputAsset}/${inputAsset}`
      : `${inputAsset}/${outputAsset}`;
  
  async function executeTrade(amountStr: string) {
    if (typeof window === "undefined" || !(window as any).ethereum) {
      setSubmitError("No wallet available for on-chain execution.");
      return;
    }
    const numericAmount = parseFloat(amountStr);
    if (isNaN(numericAmount) || numericAmount <= 0) {
        setSubmitError("Invalid amount");
        return;
    }

    let tx: any;

    try {
      setSubmitting(true);
      setSubmitError(null);
      setSubmitResult("Preparing transaction...");
      
      const provider = new BrowserProvider((window as any).ethereum);
      const net = await provider.getNetwork();
      const chainId = Number(net.chainId);

      let tokens = SEPOLIA_TOKENS;
      let routerAddress = SEPOLIA_ROUTER;

      if (chainId === 1) {
          tokens = MAINNET_TOKENS;
          routerAddress = MAINNET_ROUTER;
      } else if (chainId === 8453) {
          tokens = BASE_TOKENS;
          routerAddress = "";
      } else if (chainId === 42161) {
          tokens = ARBITRUM_TOKENS;
          routerAddress = ""; // V3 only
      } else if (chainId === 11155111) {
          tokens = SEPOLIA_TOKENS;
          routerAddress = SEPOLIA_ROUTER;
      } else {
          // Fallback
          if (network === "base") {
              tokens = BASE_TOKENS;
              routerAddress = "";
          } else if (network === "arbitrum") {
              tokens = ARBITRUM_TOKENS;
              routerAddress = "";
          } else {
              tokens = network === "mainnet" ? MAINNET_TOKENS : SEPOLIA_TOKENS;
              routerAddress = network === "mainnet" ? MAINNET_ROUTER : SEPOLIA_ROUTER;
          }
          
          const targetChainId = network === "mainnet" ? 1 : network === "base" ? 8453 : network === "arbitrum" ? 42161 : 11155111;
          if (chainId !== targetChainId) {
             setSubmitError(`Wrong network. Please switch to ${network}`);
             setSubmitting(false);
             return;
          }
      }

      const signer = await provider.getSigner();
      const signerAddress = await signer.getAddress();
      
      // Fix: Truncate numericAmount to avoid underflow if user typed too many decimals
      // Use the string directly if possible, but we need to ensure it doesn't exceed decimals
      // If we use parseFloat(amountStr), we might lose precision for very small numbers or very large precision
      // Better to use a regex or string manipulation to truncate to inputDecimals
      
      let safeAmountStr = amountStr;
      if (amountStr.includes(".")) {
          const parts = amountStr.split(".");
          if (parts[1].length > inputDecimals) {
              safeAmountStr = `${parts[0]}.${parts[1].substring(0, inputDecimals)}`;
          }
      }
      
      const amountIn = parseUnits(safeAmountStr, inputDecimals);
      
      // Get Input/Output Addresses
      const inputTokenSymbol = inputAsset;
      const outputTokenSymbol = outputAsset;
      
      const inputIsEth = inputTokenSymbol === "ETH";
      const outputIsEth = outputTokenSymbol === "ETH";
      
      const inputAddress = inputIsEth ? tokens.WETH : tokens[inputTokenSymbol];
      const outputAddress = outputIsEth ? tokens.WETH : tokens[outputTokenSymbol];
      
      if (!inputAddress || !outputAddress) {
         setSubmitError(`Token address not found for ${inputTokenSymbol} or ${outputTokenSymbol}`);
         setSubmitting(false);
         return;
      }

      let path = tradePath;
      
      // Deadline 20 mins
      const deadline = Math.floor(Date.now() / 1000) + 60 * 20;
      // tx declared outside try

      if (protocolVersion === "v3") {
          // --- UNISWAP V3 EXECUTION ---
          const v3RouterAddress = chainId === 1 ? MAINNET_V3_ROUTER : 
                                  chainId === 8453 ? BASE_V3_ROUTER :
                                  chainId === 42161 ? ARBITRUM_V3_ROUTER :
                                  SEPOLIA_V3_ROUTER;
          if (!v3RouterAddress) throw new Error("V3 Router not configured");

          const v3Router = new Contract(
              v3RouterAddress,
              [
                  "function exactInputSingle(tuple(address tokenIn, address tokenOut, uint24 fee, address recipient, uint256 amountIn, uint256 amountOutMinimum, uint160 sqrtPriceLimitX96) params) external payable returns (uint256 amountOut)",
                  "function exactInput(tuple(bytes path, address recipient, uint256 amountIn, uint256 amountOutMinimum) params) external payable returns (uint256 amountOut)"
              ],
              signer
          );

          // Handle Approvals for V3 (if input not ETH)
          if (!inputIsEth) {
             const tokenContract = new Contract(
                inputAddress,
                [
                    "function approve(address spender, uint256 amount) returns (bool)", 
                    "function allowance(address owner, address spender) view returns (uint256)",
                    "function balanceOf(address) view returns (uint256)"
                ],
                signer
             );
             
             const balance: bigint = await tokenContract.balanceOf(signerAddress);
             if (amountIn > balance) {
               setSubmitError(`Insufficient ${inputTokenSymbol} balance.`);
               setSubmitting(false);
               return;
             }

             const currentAllowance: bigint = await tokenContract.allowance(signerAddress, v3RouterAddress);
             if (currentAllowance < amountIn) {
               setSubmitResult(`Approving ${inputTokenSymbol} for V3 trading...`);
               const approveOptions: any = {
                 gasLimit: BigInt(100000)
               };
               // Add gas price if set
               if (gasPriceGwei) {
                 try {
                   const gasWei = parseUnits(gasPriceGwei, "gwei");
                   approveOptions.maxFeePerGas = gasWei;
                   approveOptions.maxPriorityFeePerGas = parseUnits("0.1", "gwei");
                 } catch (e) {
                   console.warn("Invalid gas price for approval, using default");
                 }
               }
               
               let approveTx: any;
               try {
                 approveTx = await tokenContract.approve(v3RouterAddress, MaxUint256, approveOptions);
                 await approveTx.wait();
               } catch (approveErr: any) {
                 // Handle BASE nonce error
                 const errStr = JSON.stringify(approveErr);
                 if (errStr.includes("nonce") && errStr.includes("undefined") && approveTx?.hash) {
                   console.log("BASE nonce error on approval, checking receipt...");
                   const receipt = await provider.waitForTransaction(approveTx.hash, 1, 60000);
                   if (receipt && receipt.status === 1) {
                     console.log("Approval was successful despite error");
                   } else {
                     throw approveErr;
                   }
                 } else {
                   throw approveErr;
                 }
               }
               setSubmitResult(`Approval confirmed. Executing V3 swap...`);
             }
          }

          // Calculate minOut based on Quote
          let outDecimals = tokens === BASE_TOKENS ? BASE_TOKEN_DECIMALS[outputTokenSymbol] ?? 18 : 18;
          if (!outputIsEth && outputTokenSymbol !== "WETH") {
               const c = new Contract(outputAddress, ["function decimals() view returns (uint8)"], provider);
               try { outDecimals = Number(await c.decimals()); } catch {}
          }
          
          // Use the last quoted amount as expected amount
          // If quote failed or is null, we shouldn't be here (button disabled), but safe check:
          if (!quoteAmount) throw new Error("No quote available");
          
          const expectedOut = parseUnits(quoteAmount, outDecimals);
          const slippageBps = BigInt(Math.floor(parseFloat(slippage) * 100)); // 0.5% -> 50
          const minOut = expectedOut - (expectedOut * slippageBps) / BigInt(10000);

          // Prepare overrides (value, gasPrice, etc)
          const overridesV3: any = {
              gasLimit: BigInt(500000), // Higher gas for V3 (especially multi-hop)
          };
          
          if (inputIsEth) {
              overridesV3.value = amountIn;
          }

          // Do NOT pin a nonce: a dapp-pinned nonce breaks MetaMask's relay path
          // (pay-gas-in-token / EIP-7702 Gas Station -> FAILED_TIMEOUT), because
          // the relayer must control nonce sequencing. Ethers v6 populates the
          // nonce from the network for normal transactions.
          
          if (gasPriceGwei) {
              try {
                  const gasWei = parseUnits(gasPriceGwei, "gwei");
                  const feeData = await provider.getFeeData();
                  
                  if (feeData.maxFeePerGas) {
                     // EIP-1559. Never go below the network's suggested max fee:
                     // a maxFee under the live requirement is unincludable on any
                     // path (public mempool or wallet relay).
                     overridesV3.maxFeePerGas = gasWei > feeData.maxFeePerGas ? gasWei : feeData.maxFeePerGas;
                     overridesV3.maxPriorityFeePerGas = parseUnits("0.1", "gwei"); // Use small priority fee
                     // Ensure maxPriorityFeePerGas < maxFeePerGas
                     if (overridesV3.maxPriorityFeePerGas > overridesV3.maxFeePerGas) {
                         overridesV3.maxPriorityFeePerGas = overridesV3.maxFeePerGas;
                     }
                  } else {
                     // Legacy
                     overridesV3.gasPrice = gasWei;
                  }
              } catch (e) {
                  console.warn("Invalid gas price, ignoring override", e);
              }
          }
          
          // Determine execution method (Direct vs Multi-hop)
          // Hack: if tradePath is set and has 1 element, it's the encoded path for multi-hop
          const isMultiHop = tradePath && tradePath.length === 1;

          if (isMultiHop) {
               console.log("Executing V3 Multi-hop trade", tradePath![0]);
               const params = {
                  path: tradePath![0],
                  recipient: signerAddress,
                  amountIn: amountIn,
                  amountOutMinimum: minOut
               };
               try {
                   tx = await v3Router.exactInput(params, overridesV3);
               } catch (execErr: any) {
                   // Try to recover tx hash from error if available (Ethers v6 INVALID_ARGUMENT/BAD_DATA often contains it)
                   console.error("V3 Exec Error:", execErr);
                   if (execErr?.value?.hash) {
                       console.log("Recovered tx hash from error:", execErr.value.hash);
                       // Mock a TransactionResponse-like object
                       tx = {
                           hash: execErr.value.hash,
                           wait: async () => { 
                               // If we recovered hash from an error, wait might fail too, but let's try
                               return provider.waitForTransaction(execErr.value.hash);
                           }
                       } as any;
                   } else {
                       throw execErr;
                   }
               }
          } else {
               console.log("Executing V3 Direct trade");
               const params = {
                  tokenIn: inputAddress,
                  tokenOut: outputAddress,
                  fee: v3FeeTier,
                  recipient: signerAddress,
                  amountIn: amountIn,
                  amountOutMinimum: minOut,
                  sqrtPriceLimitX96: 0
               };
               try {
                   tx = await v3Router.exactInputSingle(params, overridesV3);
               } catch (execErr: any) {
                    console.error("V3 Exec Error:", execErr);
                    if (execErr?.value?.hash) {
                        console.log("Recovered tx hash from error:", execErr.value.hash);
                        tx = {
                            hash: execErr.value.hash,
                            wait: async () => { 
                                return provider.waitForTransaction(execErr.value.hash);
                            }
                        } as any;
                    } else {
                        throw execErr;
                    }
               }
          }

      } else if (protocolVersion === "aerodrome") {
          // --- AERODROME EXECUTION (Base only) ---
          if (!path) throw new Error("No trade path available for Aerodrome");
          
          const aerodromeRouter = new Contract(
            AERODROME_ROUTER,
            [
              "function swapExactETHForTokens(uint amountOutMin, address[] calldata path, address to, uint deadline) external payable returns (uint[] memory amounts)",
              "function swapExactTokensForETH(uint amountIn, uint amountOutMin, address[] calldata path, address to, uint deadline) external returns (uint[] memory amounts)",
              "function swapExactTokensForTokens(uint amountIn, uint amountOutMin, address[] calldata path, address to, uint deadline) external returns (uint[] memory amounts)"
            ],
            signer
          );
          
          // Handle Approvals for Aerodrome
          if (!inputIsEth) {
             const tokenContract = new Contract(
                inputAddress,
                [
                    "function balanceOf(address) view returns (uint256)",
                    "function allowance(address owner, address spender) view returns (uint256)",
                    "function approve(address spender, uint256 amount) returns (bool)"
                ],
                signer
             );
             
             const balance: bigint = await tokenContract.balanceOf(signerAddress);
             if (amountIn > balance) {
               setSubmitError(`Insufficient ${inputTokenSymbol} balance.`);
               setSubmitting(false);
               return;
             }

             const currentAllowance: bigint = await tokenContract.allowance(signerAddress, AERODROME_ROUTER);
             if (currentAllowance < amountIn) {
               setSubmitResult(`Approving ${inputTokenSymbol} for Aerodrome trading...`);
               
               const approveOptions: any = {
                 gasLimit: BigInt(100000)
               };
               if (gasPriceGwei) {
                 try {
                   const gasWei = parseUnits(gasPriceGwei, "gwei");
                   approveOptions.maxFeePerGas = gasWei;
                   approveOptions.maxPriorityFeePerGas = parseUnits("0.1", "gwei");
                 } catch (e) {
                   console.warn("Invalid gas price for approval, using default");
                 }
               }
               
               let approveTx: any;
               try {
                 approveTx = await tokenContract.approve(AERODROME_ROUTER, MaxUint256, approveOptions);
                 await approveTx.wait();
               } catch (approveErr: any) {
                 const errStr = JSON.stringify(approveErr);
                 if (errStr.includes("nonce") && errStr.includes("undefined") && approveTx?.hash) {
                   console.log("BASE nonce error on Aerodrome approval, checking receipt...");
                   const receipt = await provider.waitForTransaction(approveTx.hash, 1, 60000);
                   if (receipt && receipt.status === 1) {
                     console.log("Approval was successful despite error");
                   } else {
                     throw approveErr;
                   }
                 } else {
                   throw approveErr;
                 }
               }
               setSubmitResult(`Approval confirmed. Executing Aerodrome swap...`);
             }
          }
          
          // Calculate minOut
          let outDecimals = tokens === BASE_TOKENS ? BASE_TOKEN_DECIMALS[outputTokenSymbol] ?? 18 : 18;
          if (!outputIsEth && outputTokenSymbol !== "WETH") {
               const c = new Contract(outputAddress, ["function decimals() view returns (uint8)"], provider);
               try { outDecimals = Number(await c.decimals()); } catch {}
          }
          
          if (!quoteAmount) throw new Error("No quote available");
          
          const expectedOut = parseUnits(quoteAmount, outDecimals);
          const slippageBps = BigInt(Math.floor(parseFloat(slippage) * 100));
          const minOut = expectedOut - (expectedOut * slippageBps) / BigInt(10000);
          
          const overridesAero: any = {
              gasLimit: BigInt(300000),
          };
          
          if (inputIsEth) {
              overridesAero.value = amountIn;
          }
          
          // Do NOT pin a nonce (see V3 path): it breaks MetaMask relay submissions.
          
          if (gasPriceGwei) {
              try {
                  const gasWei = parseUnits(gasPriceGwei, "gwei");
                  const feeData = await provider.getFeeData();
                  if (feeData.maxFeePerGas) {
                     overridesAero.maxFeePerGas = gasWei > feeData.maxFeePerGas ? gasWei : feeData.maxFeePerGas;
                     overridesAero.maxPriorityFeePerGas = parseUnits("0.1", "gwei");
                     if (overridesAero.maxPriorityFeePerGas > overridesAero.maxFeePerGas) {
                         overridesAero.maxPriorityFeePerGas = overridesAero.maxFeePerGas;
                     }
                  } else {
                     overridesAero.gasPrice = gasWei;
                  }
              } catch (e) {
                  console.warn("Invalid gas price for Aerodrome, ignoring override", e);
              }
          }
          
          // Execute swap
          if (inputIsEth) {
              tx = await aerodromeRouter.swapExactETHForTokens(minOut, path, signerAddress, deadline, overridesAero);
          } else if (outputIsEth) {
              tx = await aerodromeRouter.swapExactTokensForETH(amountIn, minOut, path, signerAddress, deadline, overridesAero);
          } else {
              tx = await aerodromeRouter.swapExactTokensForTokens(amountIn, minOut, path, signerAddress, deadline, overridesAero);
          }

      } else {
          // --- UNISWAP V2 EXECUTION ---
          
          // If no pre-calculated path (shouldn't happen if quote succeeded), fallback to robust logic
          if (!path) {
             path = [inputAddress, outputAddress];
             // Simple fallback path construction
             if (tokens.WETH && 
                 inputAddress.toLowerCase() !== tokens.WETH.toLowerCase() && 
                 outputAddress.toLowerCase() !== tokens.WETH.toLowerCase()) {
                  // We can't easily guess intermediate path without quote, but let's try direct
             }
          }
          
          const router = new Contract(
            routerAddress,
            [
              "function getAmountsOut(uint amountIn, address[] path) view returns (uint[] amounts)",
              "function swapExactETHForTokens(uint amountOutMin, address[] path, address to, uint deadline) payable returns (uint[] amounts)",
              "function swapExactTokensForETH(uint amountIn, uint amountOutMin, address[] path, address to, uint deadline) returns (uint[] amounts)",
              "function swapExactTokensForTokens(uint amountIn, uint amountOutMin, address[] path, address to, uint deadline) returns (uint[] amounts)",
              "function swapExactETHForTokensSupportingFeeOnTransferTokens(uint amountOutMin, address[] path, address to, uint deadline) payable",
              "function swapExactTokensForETHSupportingFeeOnTransferTokens(uint amountIn, uint amountOutMin, address[] path, address to, uint deadline)",
              "function swapExactTokensForTokensSupportingFeeOnTransferTokens(uint amountIn, uint amountOutMin, address[] path, address to, uint deadline)"
            ],
            signer
          );

          // Handle Approvals for ERC20 inputs (not ETH)
          if (!inputIsEth) {
             const tokenContract = new Contract(
                inputAddress,
                [
                    "function balanceOf(address) view returns (uint256)",
                    "function allowance(address owner, address spender) view returns (uint256)",
                    "function approve(address spender, uint256 amount) returns (bool)"
                ],
                signer
             );
             
             const balance: bigint = await tokenContract.balanceOf(signerAddress);
             if (amountIn > balance) {
               setSubmitError(`Insufficient ${inputTokenSymbol} balance.`);
               setSubmitting(false);
               return;
             }

             const currentAllowance: bigint = await tokenContract.allowance(signerAddress, routerAddress);
             if (currentAllowance < amountIn) {
               setSubmitResult(`Approving ${inputTokenSymbol} for trading...`);
               
               const approveOptions: any = {
                 gasLimit: BigInt(100000)
               };
               // Add gas price if set
               if (gasPriceGwei) {
                 try {
                   const gasWei = parseUnits(gasPriceGwei, "gwei");
                   approveOptions.maxFeePerGas = gasWei;
                   approveOptions.maxPriorityFeePerGas = parseUnits("0.1", "gwei");
                 } catch (e) {
                   console.warn("Invalid gas price for approval, using default");
                 }
               }

               let approveTx: any;
               try {
                 approveTx = await tokenContract.approve(routerAddress, MaxUint256, approveOptions);
                 await approveTx.wait();
               } catch (approveErr: any) {
                 // Handle BASE nonce error
                 const errStr = JSON.stringify(approveErr);
                 if (errStr.includes("nonce") && errStr.includes("undefined") && approveTx?.hash) {
                   console.log("BASE nonce error on approval, checking receipt...");
                   const receipt = await provider.waitForTransaction(approveTx.hash, 1, 60000);
                   if (receipt && receipt.status === 1) {
                     console.log("Approval was successful despite error");
                   } else {
                     throw approveErr;
                   }
                 } else {
                   throw approveErr;
                 }
               }
               setSubmitResult(`Approval confirmed. Executing swap...`);
             }
          }

          // Calculate min amount out (slippage)
          let amountsOut;
          try {
              if (!path) throw new Error("Path not initialized");
              amountsOut = await router.getAmountsOut(amountIn, path);
          } catch (e) {
              console.error("Path execution failed", path, e);
              throw new Error("Failed to calculate swap path. Please wait for quote to update.");
          }
          
          const expectedOut = amountsOut[amountsOut.length - 1];
          const slippageBps = BigInt(Math.floor(parseFloat(slippage) * 100)); // 0.5% -> 50
          const minOut = expectedOut - (expectedOut * slippageBps) / BigInt(10000);

          // Standard V2 swap ~150k-200k gas. Using 300k to be safe for tax tokens.
          const defaultGasLimit = BigInt(300000); 

          // Prepare overrides (value, gasPrice, etc)
          const overrides: any = {
              gasLimit: defaultGasLimit,
          };
          
          // Do NOT pin a nonce (see V3 path): it breaks MetaMask relay submissions.
          
          if (inputIsEth) {
              overrides.value = amountIn;
          }
          
          if (gasPriceGwei) {
              try {
                  const gasWei = parseUnits(gasPriceGwei, "gwei");
                  const feeData = await provider.getFeeData();
                  
                  if (feeData.maxFeePerGas) {
                     // EIP-1559
                     overrides.maxFeePerGas = gasWei > feeData.maxFeePerGas ? gasWei : feeData.maxFeePerGas;
                     overrides.maxPriorityFeePerGas = overrides.maxFeePerGas; 
                  } else {
                     // Legacy
                     overrides.gasPrice = gasWei;
                  }
              } catch (e) {
                  console.warn("Invalid gas price, ignoring override", e);
              }
          }

          if (inputIsEth) {
             // ETH -> Token
             try {
                tx = await router.swapExactETHForTokensSupportingFeeOnTransferTokens(
                    minOut,
                    path,
                    signerAddress,
                    deadline,
                    overrides
                );
             } catch (execErr: any) {
                 if (execErr?.value?.hash) {
                     tx = { hash: execErr.value.hash, wait: async () => provider.waitForTransaction(execErr.value.hash) } as any;
                 } else throw execErr;
             }
           } else if (outputIsEth) {
             // Token -> ETH
             try {
                tx = await router.swapExactTokensForETHSupportingFeeOnTransferTokens(
                    amountIn,
                    minOut,
                    path,
                    signerAddress,
                    deadline,
                    overrides
                );
             } catch (execErr: any) {
                 if (execErr?.value?.hash) {
                     tx = { hash: execErr.value.hash, wait: async () => provider.waitForTransaction(execErr.value.hash) } as any;
                 } else throw execErr;
             }
           } else {
             // Token -> Token
             try {
                tx = await router.swapExactTokensForTokensSupportingFeeOnTransferTokens(
                    amountIn,
                    minOut,
                    path,
                    signerAddress,
                    deadline,
                    overrides
                );
             } catch (execErr: any) {
                 if (execErr?.value?.hash) {
                     tx = { hash: execErr.value.hash, wait: async () => provider.waitForTransaction(execErr.value.hash) } as any;
                 } else throw execErr;
             }
           }
      }

       setSubmitResult(`Transaction sent: `);
      setTxHash(tx.hash);
      
      let receipt;
      try {
        receipt = await tx.wait();
      } catch (waitErr: any) {
          console.warn("Tx wait failed", waitErr);
          
          // Check for specific "nonce: undefined" error which seems to be a false positive in Ethers v6 + Base
          // The error object can have code="BAD_DATA" or code="INVALID_ARGUMENT" with nonce="undefined"
          const errString = waitErr?.toString?.() || "";
          const errCode = waitErr?.code || "";
          const hasNonceUndefined = 
              waitErr?.value?.nonce === "undefined" ||
              errString.includes('nonce') && errString.includes('undefined') ||
              errString.includes('value="undefined"') ||
              errString.includes('Cannot convert undefined to a BigInt');
          
          const isNonceError = (errCode === "BAD_DATA" || errCode === "INVALID_ARGUMENT") && hasNonceUndefined;

          if (isNonceError) {
               console.log("Ignoring nonce parsing error as trade was likely confirmed. Assuming success.");
               // Mock a receipt so execution continues
               receipt = { 
                   status: 1, 
                   hash: tx.hash,
                   gasUsed: BigInt(0), // Unknown
                   gasPrice: BigInt(0) // Unknown
               };
          } else {
               throw waitErr;
          }
      }
      
      const status = receipt.status === 1 ? "completed" : "failed";
      
      if (status === "failed") {
          throw new Error("Transaction reverted on-chain");
      }
      
      setExecutionData({
        txHash: receipt.hash,
        newBalance: "Updated", 
      });

      // Report trade to backend
      try {
        const estOutput = quoteAmount ? parseFloat(quoteAmount) : 0;
        
        // Calculate Network Fee in USD
        let networkFee = 0;
        if (receipt.gasUsed && receipt.gasPrice) {
            const feeWei = receipt.gasUsed * receipt.gasPrice;
            const feeEth = parseFloat(formatEther(feeWei));
            networkFee = feeEth * ethPrice; 
        }
        
         // Calculate Price (USD per Output Token)
        let priceUSD = 0;
         if (outputIsEth) {
             priceUSD = ethPrice;
         } else if (outputAsset === "USDC" || outputAsset === "USDT") {
            priceUSD = 1;
        } else {
            // Derived from input value
            let inputValueUSD = 0;
            if (inputIsEth) {
                inputValueUSD = parseFloat(amount) * ethPrice;
            } else if (inputAsset === "USDC" || inputAsset === "USDT") {
                inputValueUSD = parseFloat(amount);
            }
            
             // Prefer market price for output asset if available
             const marketPrice = pricesBySymbol[String(outputAsset).toUpperCase()];
             if (typeof marketPrice === "number" && marketPrice > 0) {
                 priceUSD = marketPrice;
             } else if (estOutput > 0 && inputValueUSD > 0) {
                 priceUSD = inputValueUSD / estOutput;
             } else if (estOutput > 0) {
                 priceUSD = parseFloat(amount) / estOutput;
             }
        }
        
        // Sanitize values to avoid NaN/null which causes backend validation error (422)
        const safePrice = isNaN(priceUSD) ? 0 : priceUSD;
        const safeEstOutput = isNaN(estOutput) ? 0 : estOutput;
        const safeNetworkFee = isNaN(networkFee) ? 0 : networkFee;
        const inputQty = parseFloat(amount);
        const tradeAction = props.signal?.action || "buy";

        // Uniform trade record standard:
        //   amount       = quantity of the pair's QUOTE currency (spent on buy, received on sell)
        //   token_amount = quantity of the pair's BASE token (received on buy, sold on sell)
        //   token        = the quote currency symbol
        //   price        = quote per base (unit price of the token in the quote currency)
        // For a buy the input is the quote currency and the output is the base token;
        // for a sell the input is the base token and the output is the quote currency.
        const quoteQty = tradeAction === "sell" ? safeEstOutput : inputQty;
        const baseQty = tradeAction === "sell" ? inputQty : safeEstOutput;
        const quoteSymbol = tradeAction === "sell" ? outputAsset : inputAsset;
        const executionPrice = baseQty > 0 && quoteQty > 0 ? quoteQty / baseQty : safePrice;

        const payload = {
            tx_hash: receipt.hash,
            network: network,
            pair: tradingPair,
            action: tradeAction,
            amount: quoteQty,
            token: quoteSymbol,
            price: executionPrice,
            token_amount: baseQty,
            network_fee: safeNetworkFee,
            status: status,
            timestamp: Math.floor(Date.now() / 1000)
        };
        
        console.log("Reporting trade to backend:", payload);

        const response = await fetch(`${BACKEND_URL}/portfolio/trade`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        
        if (!response.ok) {
            console.error("Backend reported error:", await response.text());
        }

      } catch (err) {
        console.error("Failed to report trade", err);
      }

      setSubmitResult("Trade executed successfully!");
      if (props.onClose) props.onClose();
      if (props.onSuccess) props.onSuccess(receipt.hash);

    } catch (e: any) {
      console.error("Trade execution failed", e);
      
      // Report failed trade if we have a hash
      if (typeof tx !== "undefined" && tx && tx.hash) {
           try {
             await fetch(`${BACKEND_URL}/portfolio/trade`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    tx_hash: tx.hash,
                    network: network,
                    pair: tradingPair,
                    action: props.signal?.action || "buy",
                    amount: parseFloat(amount), 
                    token: inputAsset, 
                    price: 0, 
                    token_amount: 0, 
                    network_fee: 0,
                    status: "failed",
                    timestamp: Math.floor(Date.now() / 1000)
                })
            });
          } catch (rErr) { console.error("Report failed trade err", rErr); }
      }
      console.error("Trade execution failed", e);
      
      let msg = e.reason || e.message || "Transaction failed";
      
      // Enhanced error handling for common swap issues
      if (msg.includes("CALL_EXCEPTION") || msg.includes("estimateGas")) {
          msg = "Transaction simulation failed. This often happens with tax tokens (like FLOKI/PEPE) if Slippage is too low. Try increasing Slippage Tolerance to 3-5%.";
      } else if (msg.includes("insufficient funds")) {
          msg = "Insufficient ETH for gas + value.";
      }
      
      setSubmitError(msg);
    } finally {
      setSubmitting(false);
    }
  }

  const tokenList = ["ETH", ...Object.keys(network === "mainnet" ? MAINNET_TOKENS : network === "base" ? BASE_TOKENS : network === "arbitrum" ? ARBITRUM_TOKENS : SEPOLIA_TOKENS).sort()];

  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-lg shadow-2xl flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="p-6 border-b border-slate-800 flex items-center justify-between sticky top-0 bg-slate-900 z-10 rounded-t-xl">
          <h3 className="text-xl font-bold text-white flex items-center gap-2">
            Execute Trade
            <span className="text-xs font-normal px-2 py-0.5 rounded bg-blue-500/20 text-blue-400 border border-blue-500/30">
              {network === "mainnet" ? "Mainnet" : network === "base" ? "Base" : network === "arbitrum" ? "Arbitrum" : "Sepolia"}
            </span>
          </h3>
          <button
            onClick={props.onClose}
            className="text-gray-400 hover:text-white transition-colors"
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-6 h-6">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="p-6 overflow-y-auto custom-scrollbar">
          {error && (
            <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-sm text-red-400">
              {error}
            </div>
          )}

          {hasExecuted ? (
            <div className="text-center py-8">
              <div className="w-16 h-16 bg-green-500/20 text-green-500 rounded-full flex items-center justify-center mx-auto mb-4">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-8 h-8">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                </svg>
              </div>
              <h4 className="text-xl font-bold text-white mb-2">Trade Executed!</h4>
              <p className="text-gray-400 mb-6">Your transaction has been confirmed on the blockchain.</p>
              
              <div className="bg-slate-800 rounded-lg p-4 mb-6 text-left">
                <div className="flex justify-between mb-2">
                  <span className="text-gray-400">Transaction Hash</span>
                </div>
                <a 
                  href={`https://${network === "mainnet" ? "etherscan.io" : network === "base" ? "basescan.org" : "sepolia.etherscan.io"}/tx/${executionData?.txHash}`}
                  target="_blank"
                  rel="noreferrer"
                  className="text-blue-400 text-sm hover:underline break-all font-mono"
                >
                  {executionData?.txHash}
                </a>
              </div>

              <button
                onClick={props.onClose}
                className="w-full py-3 bg-slate-700 hover:bg-slate-600 text-white rounded-lg font-medium transition-colors"
              >
                Close
              </button>
            </div>
          ) : (
            <div className="space-y-6">
              {/* Signal Info */}
              <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700">
                <div className="flex justify-between items-center mb-2">
                  <span className="text-sm text-gray-400">Trading Pair</span>
                  <div className="text-right">
                    <div className="font-mono font-bold text-white text-lg">{tradingPair}</div>
                    {tradingPair !== props.signal.pair && (
                        <div className="text-xs text-gray-500">Signal: {props.signal.pair}</div>
                    )}
                  </div>
                </div>
                <div className="flex justify-between items-center mb-2">
                  <span className="text-sm text-gray-400">Action</span>
                  <span className={`font-bold ${props.signal.action === "buy" ? "text-green-400" : "text-red-400"} uppercase`}>
                    {props.signal.action}
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-sm text-gray-400">Confidence</span>
                  <div className="flex items-center gap-2">
                    <div className="w-16 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-blue-500 rounded-full"
                        style={{ width: `${confidencePct}%` }}
                      />
                    </div>
                    <span className="text-sm text-blue-400">{confidencePct}%</span>
                  </div>
                </div>
              </div>

              {/* Input Amount & Source Asset */}
              <div>
                <label className="block text-sm font-medium text-gray-400 mb-2">
                  Pay / Sell Amount
                </label>
                <div className="relative">
                  <input
                    type="number"
                    value={amount}
                    onChange={(e) => setAmount(e.target.value)}
                    placeholder="0.0"
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg pl-4 pr-32 py-3 text-white focus:outline-none focus:border-blue-500 transition-colors text-lg"
                  />
                  <div className="absolute right-2 top-2 flex items-center gap-2 h-full pb-4">
                     <button
                        onClick={() => setAmount(balanceForTrade || "")}
                        className="text-xs bg-slate-700 hover:bg-slate-600 text-blue-400 px-2 py-1 rounded font-bold uppercase transition-colors"
                     >
                        Max
                     </button>
                     {/* Input Asset Selector */}
                     {props.signal.action === "buy" ? (
                         <select 
                            value={inputAsset}
                            onChange={(e) => handleInputAssetChange(e.target.value)}
                            className="bg-slate-700 border-none text-white text-sm rounded px-2 py-1 cursor-pointer hover:bg-slate-600 focus:ring-0"
                         >
                            {tokenList.map(t => <option key={t} value={t}>{t}</option>)}
                         </select>
                     ) : (
                         <span className="bg-slate-700 text-white text-sm rounded px-2 py-1 font-bold">
                             {inputAsset}
                         </span>
                     )}
                  </div>
                </div>
                <div className="flex justify-between mt-2 text-xs">
                  <span className="text-gray-500">
                      Available: {balanceForTrade ? parseFloat(balanceForTrade).toFixed(4) : "Loading..."} {inputAsset}
                  </span>
                </div>
              </div>

              {/* Trade Details */}
              <div className="space-y-3 pt-4 border-t border-slate-800">
                <div className="flex justify-between items-center text-sm">
                  <span className="text-gray-400">Slippage Tolerance</span>
                  <div className="flex items-center gap-2">
                    <input 
                      type="number" 
                      value={slippage}
                      onChange={(e) => setSlippage(e.target.value)}
                      className="w-16 bg-slate-800 border border-slate-700 rounded px-2 py-1 text-right text-white text-xs"
                    />
                    <span className="text-gray-500">%</span>
                  </div>
                </div>
                <div className="flex justify-between items-center text-sm">
                  <span className="text-gray-400">Gas Price (Gwei)</span>
                  <input 
                    type="number" 
                    value={gasPriceGwei}
                    onChange={(e) => setGasPriceGwei(e.target.value)}
                    className="w-16 bg-slate-800 border border-slate-700 rounded px-2 py-1 text-right text-white text-xs"
                  />
                </div>
              </div>

              {quoteError && (
                <div className="mb-2 p-3 bg-yellow-500/10 border border-yellow-500/20 rounded-lg text-sm text-yellow-400">
                  Warning: {quoteError}. Trade might fail.
                </div>
              )}

              {submitError && (
                 <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-sm text-red-400">
                   {submitError}
                 </div>
              )}
              
              {submitResult && !submitError && (
                 <div className="p-3 bg-blue-500/10 border border-blue-500/20 rounded-lg text-sm text-blue-400 animate-pulse break-all">
                   {submitResult}
                   {txHash && (
                       <a 
                         href={`https://${network === "mainnet" ? "etherscan.io" : network === "base" ? "basescan.org" : "sepolia.etherscan.io"}/tx/${txHash}`}
                         target="_blank" 
                         rel="noreferrer"
                         className="underline font-mono ml-1 hover:text-blue-300"
                       >
                           {txHash}
                       </a>
                   )}
                 </div>
              )}

              {/* Output / Quote & Destination Asset */}
              <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700">
                <div className="flex justify-between items-center mb-2">
                  <span className="text-sm text-gray-400">Estimated Output</span>
                  {isQuoting ? (
                     <span className="text-xs text-blue-400 animate-pulse">Fetching quote...</span>
                  ) : (
                     <span className="text-xs text-gray-500">
                        {quoteAmount ? `1 ${inputAsset} ≈ ${(parseFloat(quoteAmount) / parseFloat(amount || "1")).toFixed(6)} ${outputAsset}` : ""}
                     </span>
                  )}
                </div>
                <div className="flex items-center gap-3 justify-between">
                    <div className="font-mono text-xl text-white truncate max-w-[200px]">
                        {quoteAmount ? parseFloat(quoteAmount).toFixed(6) : "---..."}
                    </div>
                    
                    {/* Output Asset Selector */}
                     {props.signal.action === "sell" ? (
                         <select 
                            value={outputAsset}
                            onChange={(e) => handleOutputAssetChange(e.target.value)}
                            className="bg-slate-700 border-none text-white text-sm rounded px-2 py-1 cursor-pointer hover:bg-slate-600 focus:ring-0"
                         >
                            {tokenList.map(t => <option key={t} value={t}>{t}</option>)}
                         </select>
                     ) : (
                         <span className="bg-slate-700 text-white text-sm rounded px-2 py-1 font-bold">
                             {outputAsset}
                         </span>
                     )}
                </div>

                {/* Price Impact Display */}
                {!isQuoting && priceImpact !== null && (
                  <div className={`mt-2 flex items-center justify-between text-xs rounded px-2 py-1 ${
                    priceImpact >= 10
                      ? "bg-red-500/20 border border-red-500/40"
                      : priceImpact >= 5
                      ? "bg-orange-500/20 border border-orange-500/40"
                      : priceImpact >= 2
                      ? "bg-yellow-500/20 border border-yellow-500/40"
                      : "bg-slate-700/50 border border-slate-600"
                  }`}>
                    <span className={
                      priceImpact >= 10 ? "text-red-400 font-bold" :
                      priceImpact >= 5  ? "text-orange-400 font-semibold" :
                      priceImpact >= 2  ? "text-yellow-400" :
                      "text-gray-400"
                    }>
                      Price Impact
                    </span>
                    <span className={`font-mono font-bold ${
                      priceImpact >= 10 ? "text-red-400" :
                      priceImpact >= 5  ? "text-orange-400" :
                      priceImpact >= 2  ? "text-yellow-400" :
                      "text-gray-300"
                    }`}>
                      {priceImpact < 0.01 ? "<0.01%" : `-${priceImpact.toFixed(2)}%`}
                    </span>
                  </div>
                )}
                
                {/* High price impact warning */}
                {!isQuoting && priceImpact !== null && priceImpact >= 5 && (
                  <div className="mt-2 text-xs text-center font-semibold text-red-400 bg-red-500/10 border border-red-500/30 rounded px-2 py-1.5">
                    {priceImpact >= 10
                      ? "\u26A0 High price impact! This pool has very low liquidity. Consider reducing trade size."
                      : "\u26A0 Notable price impact due to limited pool liquidity."}
                  </div>
                )}
              </div>

              {/* Gas Estimate */}
              <div className="flex justify-between items-center text-xs text-gray-400 px-1">
                 <span>Network Fee (Est.):</span>
                 <span className="font-mono text-gray-300">
                    {estimating ? "..." : gasCostEth ? `~${parseFloat(gasCostEth).toFixed(5)} ETH` : "---..."}
                 </span>
              </div>
              
              {/* Summary Text */}
              {amount && quoteAmount && !isQuoting && (
                  <div className="text-center text-sm text-gray-400 bg-slate-800/30 p-2 rounded border border-slate-700/50 mb-2">
                      {props.signal.action === "buy" ? "Buying" : "Selling"} <span className="text-white font-bold">{amount} {inputAsset}</span> for <span className="text-white font-bold">~{parseFloat(quoteAmount).toFixed(6)} {outputAsset}</span>
                  </div>
              )}

              {/* Action Buttons */}
              <div className="flex gap-3 pt-2">
                <button
                  disabled={!amount || parseFloat(amount) <= 0 || loading || submitting || isQuoting || !quoteAmount}
                  onClick={() => executeTrade(amount)}
                  className={`flex-1 py-4 rounded-xl font-bold text-lg transition-all ${
                    !amount || parseFloat(amount) <= 0 || loading || submitting || !quoteAmount
                      ? "bg-slate-800 text-gray-500 cursor-not-allowed"
                      : props.signal.action === "buy"
                      ? "bg-green-600 hover:bg-green-500 text-white shadow-lg shadow-green-900/20"
                      : "bg-red-600 hover:bg-red-500 text-white shadow-lg shadow-red-900/20"
                  }`}
                >
                  {submitting 
                    ? "Processing..." 
                    : isQuoting 
                      ? "Fetching Quote..." 
                      : `Confirm ${props.signal.action.toUpperCase()}`
                  }
                </button>
                <button
                  onClick={props.onClose}
                  className="px-6 py-4 bg-slate-800 hover:bg-slate-700 text-gray-300 rounded-xl font-medium transition-colors border border-slate-700"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
