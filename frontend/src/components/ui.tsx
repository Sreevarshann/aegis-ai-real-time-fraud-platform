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
          <div className="min-w-0">
            {title && <h2 className="panel-title">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-[12.5px] text-fg-3">{subtitle}</p>}
          </div>
          {actions}
        </header>
      )}
      <div className={bodyClass ?? "px-6 pb-6 pt-4"}>{children}</div>
    </section>
  );
}

/** Page-level heading used at the top of each screen's content. */
export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h2 className="text-[22px] font-semibold tracking-tight text-fg">{title}</h2>
        {description && <p className="mt-1 max-w-3xl text-[13.5px] text-fg-3">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

const TILE_TONE = {
  default: "from-[#3b82f6] to-[#1d4ed8] shadow-brand",
  alert: "from-[#f87171] to-[#dc2626] shadow-[0_8px_20px_-6px_rgba(220,38,38,0.45)]",
  good: "from-[#2dd4bf] to-[#0d9488] shadow-[0_8px_20px_-6px_rgba(13,148,136,0.45)]",
};

export function Stat({ label, value, hint, icon, tone = "default", delta }: {
  label: string; value: ReactNode; hint?: ReactNode; icon?: ReactNode; tone?: "default" | "alert" | "good";
  delta?: { text: string; tone: "up" | "down" | "neutral" };
}) {
  return (
    <div className="panel animate-fadein flex items-start justify-between gap-4 p-5 transition hover:-translate-y-0.5 hover:shadow-lift">
      <div className="min-w-0">
        <div className="text-[13px] font-medium text-fg-3">{label}</div>
        <div className="mt-1.5 flex items-baseline gap-2">
          <span data-testid="stat-value" className="text-[28px] font-semibold leading-none tracking-tight text-fg">{value}</span>
          {delta && (
            <span className={clsx("text-[12px] font-semibold",
              delta.tone === "up" ? "text-risk-low" : delta.tone === "down" ? "text-risk-critical" : "text-fg-3")}>{delta.text}</span>
          )}
        </div>
        {hint && <div className="mt-2 truncate text-[12px] text-fg-3">{hint}</div>}
      </div>
      {icon && <span className={clsx("grid h-12 w-12 shrink-0 place-items-center rounded-xl bg-gradient-to-br text-white", TILE_TONE[tone])}>{icon}</span>}
    </div>
  );
}

const RISK_STYLE: Record<RiskCategory, string> = {
  low: "text-[#15803d] bg-[#f0fdf4] ring-[#bbf7d0]",
  medium: "text-[#b45309] bg-[#fffbeb] ring-[#fde68a]",
  high: "text-[#c2410c] bg-[#fff7ed] ring-[#fed7aa]",
  critical: "text-[#b91c1c] bg-[#fef2f2] ring-[#fecaca]",
};
export const RISK_HEX: Record<RiskCategory, string> = { low: "#16a34a", medium: "#d97706", high: "#ea580c", critical: "#dc2626" };

export function RiskBadge({ category, score }: { category: RiskCategory | null; score?: number | null }) {
  if (!category) return <span className="text-fg-4">unscored</span>;
  return (
    <span className={clsx("inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-semibold ring-1 ring-inset", RISK_STYLE[category])}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {score != null && <span className="num">{score}</span>}
      <span className="uppercase tracking-wide">{category}</span>
    </span>
  );
}

export function ScoreBar({ score }: { score: number | null }) {
  if (score == null) return <span className="text-fg-4">—</span>;
  const cat: RiskCategory = score >= 85 ? "critical" : score >= 60 ? "high" : score >= 30 ? "medium" : "low";
  return (
    <div className="flex items-center gap-2" title={`Risk score ${score}/100 (${cat})`}>
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-track">
        <div className="h-full rounded-full" style={{ width: `${Math.max(score, 3)}%`, background: RISK_HEX[cat] }} />
      </div>
      <span className="num w-6 text-right text-[12px] font-medium text-fg-2">{score}</span>
    </div>
  );
}

export function Pill({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "blue" | "teal" | "warn" | "bad" | "good" }) {
  const tones = {
    neutral: "bg-sunken text-fg-2 ring-line-strong",
    blue: "bg-signal-soft text-signal ring-signal-ring",
    teal: "bg-teal-soft text-teal ring-[#99e2d9]",
    warn: "bg-[#fffbeb] text-[#b45309] ring-[#fde68a]",
    bad: "bg-[#fef2f2] text-[#b91c1c] ring-[#fecaca]",
    good: "bg-[#f0fdf4] text-[#15803d] ring-[#bbf7d0]",
  };
  return <span className={clsx("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-0.5 text-[11px] font-semibold ring-1 ring-inset", tones[tone])}>{children}</span>;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("animate-pulse rounded-md bg-track", className)} />;
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
      <span className="grid h-11 w-11 place-items-center rounded-full bg-signal-soft"><Inbox className="h-5 w-5 text-signal" /></span>
      <div className="text-[13px] font-semibold text-fg">{title}</div>
      {children && <div className="max-w-md text-[12.5px] text-fg-3">{children}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-8 text-center" role="alert">
      <span className="grid h-11 w-11 place-items-center rounded-full bg-[#fff7ed]"><AlertTriangle className="h-5 w-5 text-risk-high" /></span>
      <div className="text-[13px] font-semibold text-fg">Could not load data</div>
      <div className="max-w-md text-[12.5px] text-fg-3">{msg}</div>
      {onRetry && <button className="btn-ghost mt-2" onClick={onRetry}><RefreshCw className="h-3.5 w-3.5" />Retry</button>}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={clsx("h-4 w-4 animate-spin", className)} />;
}

export function StatusDot({ status }: { status: "up" | "down" | "warn" | "unknown" }) {
  const c = { up: "bg-risk-low", down: "bg-risk-critical", warn: "bg-risk-medium", unknown: "bg-fg-4" }[status];
  return (
    <span className="relative inline-flex h-2 w-2">
      {status === "up" && <span className={clsx("absolute inline-flex h-full w-full animate-ping rounded-full opacity-40", c)} />}
      <span className={clsx("relative inline-flex h-2 w-2 rounded-full", c)} />
    </span>
  );
}

export function KeyValue({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2.5 text-[13px]">
      {items.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-fg-3">{k}</dt>
          <dd className="min-w-0 break-words font-medium text-fg [&_.num]:whitespace-normal [&_.num]:break-all">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Segmented tabs used for status filters. */
export function Segmented<T extends string>({ value, onChange, options }: {
  value: T; onChange: (v: T) => void; options: { value: T; label: ReactNode }[];
}) {
  return (
    <div className="inline-flex flex-wrap rounded-lg border border-line bg-sunken p-0.5" role="tablist">
      {options.map((o) => (
        <button key={o.value} role="tab" aria-selected={value === o.value} onClick={() => onChange(o.value)}
          className={clsx("rounded-md px-3 py-1.5 text-[12px] font-semibold transition",
            value === o.value ? "bg-surface text-signal shadow-sm ring-1 ring-line" : "text-fg-3 hover:text-fg")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}
