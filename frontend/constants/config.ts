export const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:8000";

/**
 * Public demo build: the backend runs with DEMO_MODE=1, executing proposals
 * against a virtual portfolio.  The browser never touches a wallet.
 */
export const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === "1";
