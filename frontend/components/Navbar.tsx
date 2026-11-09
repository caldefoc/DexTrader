"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import WalletConnectButton from "./WalletConnectButton";
import { DEMO_MODE } from "../constants/config";

const links = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/portfolio", label: "Portfolio" },
  { href: "/agents", label: "Agents" },
  { href: "/reports", label: "Reports" },
  { href: "/news", label: "News" },
  { href: "/settings", label: "Settings" }
];

export default function Navbar() {
  const pathname = usePathname();

  return (
    <header className="border-b border-slate-800 bg-slate-950/70 backdrop-blur">
      <div className="container mx-auto px-4 py-3 flex items-center justify-between gap-4">
        <Link href="/" className="text-lg font-semibold">
          DexTrader
        </Link>
        <nav className="flex items-center gap-6">
          <div className="hidden md:flex items-center gap-4">
            {links.map(link => (
              <Link
                key={link.href}
                href={link.href}
                className={
                  "text-sm " +
                  (pathname === link.href
                    ? "text-primary font-medium"
                    : "text-gray-300 hover:text-white")
                }
              >
                {link.label}
              </Link>
            ))}
          </div>
          {DEMO_MODE ? (
            <span className="text-xs text-amber-300 border border-amber-500/40 rounded-full px-3 py-1">
              Demo mode
            </span>
          ) : (
            <WalletConnectButton />
          )}
        </nav>
      </div>
    </header>
  );
}
