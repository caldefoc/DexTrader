const compactUsd = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  notation: "compact",
  maximumFractionDigits: 3,
});

export function formatCompactUsd(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value) || value < 0) return "—";
  return compactUsd.format(value);
}
