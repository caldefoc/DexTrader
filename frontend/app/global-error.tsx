"use client";

/**
 * Root error boundary. Without this, any uncaught client error replaces the
 * page with Next.js' generic "Application error: a client-side exception has
 * occurred", which is impossible to diagnose from a phone. Here the actual
 * message is shown so the failure can be read and reported.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body
        style={{
          background: "#0b0e14",
          color: "#e6e9ef",
          fontFamily:
            "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
          margin: 0,
          padding: "24px",
          lineHeight: 1.5,
        }}
      >
        <h1 style={{ fontSize: "1.1rem", marginBottom: "0.75rem" }}>
          Something went wrong in DexTrader
        </h1>
        <p style={{ color: "#9aa4b2", marginBottom: "1rem" }}>
          The page failed to start. The details below help pin down why.
        </p>
        <pre
          style={{
            background: "#151a23",
            border: "1px solid #232a36",
            borderRadius: "8px",
            padding: "12px",
            fontSize: "0.8rem",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {error.message || String(error)}
          {error.digest ? `\n(digest: ${error.digest})` : ""}
        </pre>
        <button
          onClick={() => reset()}
          style={{
            marginTop: "1rem",
            background: "#2f6feb",
            color: "#fff",
            border: "none",
            borderRadius: "8px",
            padding: "10px 16px",
            fontSize: "0.9rem",
          }}
        >
          Try again
        </button>
      </body>
    </html>
  );
}
