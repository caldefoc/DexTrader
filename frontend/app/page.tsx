import Link from "next/link";
import WalletConnectButton from "../components/WalletConnectButton";

export default function HomePage() {
  return (
    <div className="flex flex-col items-center justify-center gap-8 py-16">
      <div className="text-center max-w-2xl">
        <h1 className="text-4xl md:text-5xl font-semibold mb-4">
          DexTrader
        </h1>
        <p className="text-gray-300 text-lg">
          Monitor CoinMarketCap markets, analyze signals with agents, and trade on Uniswap with a non-custodial wallet.
        </p>
      </div>
      <div className="flex flex-col sm:flex-row gap-4">
        <Link
          href="/dashboard"
          className="px-6 py-3 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 transition"
        >
          Open Dashboard
        </Link>
        <Link
          href="/portfolio"
          className="px-6 py-3 rounded-md bg-secondary text-secondary-foreground text-sm font-medium hover:bg-slate-800 transition"
        >
          View Portfolio
        </Link>
      </div>
      <WalletConnectButton />
    </div>
  );
}

