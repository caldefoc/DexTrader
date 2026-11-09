"use client";
import { useWallet } from "../context/WalletContext";

export default function WalletConnectButton() {
  const { address, connecting, error, connect } = useWallet();

  const label =
    address != null
      ? address.slice(0, 6) + "..." + address.slice(-4)
      : connecting
      ? "Connecting..."
      : "Connect Wallet";

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        type="button"
        onClick={connect}
        className="px-3 py-2 rounded-md text-xs md:text-sm bg-primary text-primary-foreground hover:opacity-90 transition"
      >
        {label}
      </button>
      {error && (
        <span className="text-[10px] text-red-400 max-w-[200px] text-right">
          {error}
        </span>
      )}
    </div>
  );
}
