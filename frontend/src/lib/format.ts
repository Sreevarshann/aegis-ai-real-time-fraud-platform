const nf = new Intl.NumberFormat("en-US");
export const fmtInt = (n: number | string | null | undefined) => (n == null ? "—" : nf.format(Number(n)));
export const fmtPct = (n: number | null | undefined, digits = 1) => (n == null ? "—" : `${(n * 100).toFixed(digits)}%`);
export const fmtNum = (n: number | null | undefined, digits = 3) => (n == null ? "—" : Number(n).toFixed(digits));

export function fmtMoney(amount: string | number, currency: string) {
  const v = Number(amount);
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency, maximumFractionDigits: currency === "JPY" ? 0 : 2 }).format(v);
  } catch {
    return `${currency} ${v.toFixed(2)}`;
  }
}

export function fmtTime(iso: string | null | undefined, withDate = false) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("en-US", {
    hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit",
    ...(withDate ? { month: "short", day: "numeric" } : {}),
  });
}

export function fmtAgo(iso: string | null | undefined) {
  if (!iso) return "never";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

export const shortId = (id: string) => id.slice(0, 8);
export const titleCase = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
