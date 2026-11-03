import clsx from "clsx";
import { AlertTriangle, Inbox, Loader2, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";
import type { RiskCategory } from "../lib/types";

export function Panel({ title, subtitle, actions, children, className, bodyClass }: {
  title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClass?: string;
}) {
  return (
    <section className={clsx("panel animate-fadein", className)}>
      {(title || actions) && (
        <header className="panel-header">
          <div>
            {title && <h2 className="panel-title">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-[12px] text-mist-500">{subtitle}</p>}
          </div>
          {actions}
        </header>
      )}
      <div className={clsx("p-5", bodyClass)}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, hint, icon, tone = "default" }: {
  label: string; value: ReactNode; hint?: ReactNode; icon?: ReactNode; tone?: "default" | "alert" | "good";
}) {
  return (
    <div className="panel animate-fadein p-4">
      <div className="flex items-center justify-between">
        <span className="eyebrow">{label}</span>
        {icon && <span className={clsx("text-mist-500", tone === "alert" && "text-risk-critical", tone === "good" && "text-teal")}>{icon}</span>}
      </div>
      <div className="num mt-2 text-[26px] font-medium leading-none tracking-tight text-mist-100">{value}</div>
      {hint && <div className="mt-2 text-[12px] text-mist-500">{hint}</div>}
    </div>
  );
}

const RISK_STYLE: Record<RiskCategory, string> = {
  low: "text-risk-low bg-risk-low/10 ring-risk-low/25",
  medium: "text-risk-medium bg-risk-medium/10 ring-risk-medium/25",
  high: "text-risk-high bg-risk-high/10 ring-risk-high/25",
  critical: "text-risk-critical bg-risk-critical/10 ring-risk-critical/30",
};
export const RISK_HEX: Record<RiskCategory, string> = { low: "#34d399", medium: "#fbbf24", high: "#fb923c", critical: "#f43f5e" };

export function RiskBadge({ category, score }: { category: RiskCategory | null; score?: number | null }) {
  if (!category) return <span className="text-mist-500">unscored</span>;
  return (
    <span className={clsx("inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset", RISK_STYLE[category])}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {score != null && <span className="num">{score}</span>}
      <span className="uppercase tracking-wide">{category}</span>
    </span>
  );
}

export function ScoreBar({ score }: { score: number | null }) {
  if (score == null) return <span className="text-mist-500">—</span>;
  const cat: RiskCategory = score >= 85 ? "critical" : score >= 60 ? "high" : score >= 30 ? "medium" : "low";
  return (
    <div className="flex items-center gap-2" title={`Risk score ${score}/100 (${cat})`}>
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-ink-700">
        <div className="h-full rounded-full" style={{ width: `${Math.max(score, 3)}%`, background: RISK_HEX[cat] }} />
      </div>
      <span className="num w-6 text-right text-[12px] text-mist-300">{score}</span>
    </div>
  );
}

export function Pill({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "blue" | "teal" | "warn" | "bad" | "good" }) {
  const tones = {
    neutral: "bg-ink-700/60 text-mist-300 ring-line",
    blue: "bg-signal/10 text-signal ring-signal/30",
    teal: "bg-teal/10 text-teal ring-teal/30",
    warn: "bg-risk-medium/10 text-risk-medium ring-risk-medium/30",
    bad: "bg-risk-critical/10 text-risk-critical ring-risk-critical/30",
    good: "bg-risk-low/10 text-risk-low ring-risk-low/30",
  };
  return <span className={clsx("inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset", tones[tone])}>{children}</span>;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("animate-pulse rounded-md bg-ink-700/50", className)} />;
}

export function LoadingBlock({ rows = 4, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div className="space-y-2.5" role="status" aria-label={label}>
      {Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className="h-7 w-full" />)}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
      <Inbox className="h-6 w-6 text-mist-500" />
      <div className="text-[13px] font-medium text-mist-300">{title}</div>
      {children && <div className="max-w-md text-[12px] text-mist-500">{children}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-8 text-center" role="alert">
      <AlertTriangle className="h-6 w-6 text-risk-high" />
      <div className="text-[13px] font-medium text-mist-100">Could not load data</div>
      <div className="max-w-md text-[12px] text-mist-500">{msg}</div>
      {onRetry && <button className="btn-ghost mt-2" onClick={onRetry}><RefreshCw className="h-3.5 w-3.5" />Retry</button>}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={clsx("h-4 w-4 animate-spin", className)} />;
}

export function StatusDot({ status }: { status: "up" | "down" | "warn" | "unknown" }) {
  const c = { up: "bg-risk-low", down: "bg-risk-critical", warn: "bg-risk-medium", unknown: "bg-mist-500" }[status];
  return (
    <span className="relative inline-flex h-2 w-2">
      {status === "up" && <span className={clsx("absolute inline-flex h-full w-full animate-ping rounded-full opacity-40", c)} />}
      <span className={clsx("relative inline-flex h-2 w-2 rounded-full", c)} />
    </span>
  );
}

export function KeyValue({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-5 gap-y-2 text-[13px]">
      {items.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-mist-500">{k}</dt>
          <dd className="min-w-0 break-words text-mist-100">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
