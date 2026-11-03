import { useQuery } from "@tanstack/react-query";
import { Activity, AlertOctagon, ArrowRight, BrainCircuit, Layers } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { BarsChart, HeroBars, VolumeChart } from "../components/charts";
import SimulatorControls from "../components/SimulatorControls";
import { EmptyState, ErrorState, LoadingBlock, Panel, RISK_HEX, RiskBadge, Segmented, Stat, StatusDot } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { fmtAgo, fmtInt, fmtMoney, fmtNum, fmtTime, titleCase } from "../lib/format";
import type { Alert, RiskCategory } from "../lib/types";

interface Overview {
  stats: { total_transactions: number; last_60s: number; transactions_per_second: number; last_24h: number; total_alerts: number;
    open_alerts: number; alerts_24h: number; investigations: number; avg_score_24h: string | null; amount_24h: string;
    last_ingested_at: string | null };
  volume: { bucket: string; transactions: number; alerts: number }[];
  bucket_seconds: number;
  risk_distribution: { range: string; count: number }[];
  risk_categories: { category: RiskCategory; count: number }[];
  recent_alerts: Alert[];
}
interface Health { services: Record<string, { status: string; latency_ms: number }>; consumer_heartbeat_age_s: number | null }
interface ModelSummary { version: string; test_metrics: { pr_auc: number; precision: number; recall: number };
  live_simulation_performance: { precision: number | null; recall: number | null } }
interface Analytics { marts: { risk_by_category: { merchant_category: string; avg_risk_score: string; transactions: number }[] | null } }

const WINDOWS = [{ value: "60", label: "1h" }, { value: "360", label: "6h" }, { value: "1440", label: "24h" }] as const;

/** Counts differ by orders of magnitude (most traffic is low risk), so show exact numbers + shares, not a bar chart. */
function CategoryList({ items }: { items: { category: RiskCategory; count: number }[] }) {
  const total = items.reduce((a, c) => a + c.count, 0) || 1;
  return (
    <ul className="space-y-4" aria-label="Risk categories">
      {items.map((c) => (
        <li key={c.category}>
          <div className="mb-1.5 flex items-baseline justify-between text-[13px]">
            <span className="flex items-center gap-2 font-medium capitalize text-fg"><span className="h-2.5 w-2.5 rounded-full" style={{ background: RISK_HEX[c.category] }} />{c.category}</span>
            <span className="num text-fg">{fmtInt(c.count)} <span className="text-fg-3">· {((c.count / total) * 100).toFixed(c.count / total < 0.01 ? 2 : 1)}%</span></span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-track">
            <div className="h-full rounded-full" style={{ width: `${Math.max((c.count / total) * 100, c.count ? 0.8 : 0)}%`, background: RISK_HEX[c.category] }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

export default function OverviewPage() {
  const { user } = useAuth();
  const [win, setWin] = useState<(typeof WINDOWS)[number]["value"]>("60");
  const q = useQuery({ queryKey: ["overview", win], queryFn: () => api<Overview>(`/overview?window_minutes=${win}`), refetchInterval: 5000 });
  const health = useQuery({ queryKey: ["health"], queryFn: () => api<Health>("/operations/health"), refetchInterval: 15_000 });
  const model = useQuery({ queryKey: ["model"], queryFn: () => api<ModelSummary>("/models/active"), refetchInterval: 60_000 });
  const analytics = useQuery({ queryKey: ["analytics"], queryFn: () => api<Analytics>("/analytics"), refetchInterval: 60_000 });

  if (q.isLoading) return <div className="grid gap-6 md:grid-cols-4">{[0, 1, 2, 3].map((i) => <Panel key={i}><LoadingBlock rows={2} /></Panel>)}</div>;
  if (q.isError || !q.data) return <Panel><ErrorState error={q.error} onRetry={() => q.refetch()} /></Panel>;
  const { stats, volume, risk_distribution, risk_categories, recent_alerts, bucket_seconds } = q.data;
  const highRisk = risk_categories.filter((c) => c.category === "high" || c.category === "critical").reduce((a, c) => a + c.count, 0);
  const windowAlerts = volume.reduce((a, v) => a + v.alerts, 0);
  const windowTxns = volume.reduce((a, v) => a + v.transactions, 0);
  const bucketLabel = bucket_seconds === 60 ? "minute" : `${bucket_seconds / 60} minutes`;
  const categories = (analytics.data?.marts.risk_by_category ?? []).slice(0, 7)
    .map((r) => ({ category: titleCase(r.merchant_category), score: Number(r.avg_risk_score) }));
  const winLabel = WINDOWS.find((w) => w.value === win)?.label;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-[22px] font-semibold tracking-tight text-fg">Good to see you, {user?.full_name.split(" ")[0]}</h2>
          <p className="mt-1 text-[13.5px] text-fg-3">Live risk posture across the streaming pipeline · last transaction {fmtAgo(stats.last_ingested_at)}</p>
        </div>
        <Segmented value={win} onChange={setWin} options={WINDOWS.map((w) => ({ value: w.value, label: w.label }))} />
      </div>

      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Total transactions" value={fmtInt(stats.total_transactions)} icon={<Layers className="h-5 w-5" />}
          hint={<>{fmtInt(stats.last_24h)} in the last 24h</>} />
        <Stat label="Live rate" value={<>{stats.transactions_per_second.toFixed(2)}<span className="ml-1 text-[14px] font-medium text-fg-3">tx/s</span></>}
          icon={<Activity className="h-5 w-5" />} tone="good" hint={`${fmtInt(stats.last_60s)} ingested in the last 60s`} />
        <Stat label="Suspicious activity" value={fmtInt(stats.open_alerts)} icon={<AlertOctagon className="h-5 w-5" />} tone="alert"
          hint={`${fmtInt(stats.alerts_24h)} alerts in 24h · ${fmtInt(highRisk)} high/critical`} />
        <Stat label="Model PR-AUC" value={model.data ? fmtNum(model.data.test_metrics.pr_auc) : "—"} icon={<BrainCircuit className="h-5 w-5" />}
          hint={model.data ? `test split · live precision ${fmtNum(model.data.live_simulation_performance.precision, 2)}` : "loading model"} />
      </div>

      <div className="grid gap-6 xl:grid-cols-12">
        <section className="panel animate-fadein p-4 xl:col-span-5">
          <div className="rounded-xl bg-gradient-to-br from-[#2563eb] via-[#1d4ed8] to-[#1e3a8a] p-4 pb-2 shadow-brand">
            <div className="mb-1 flex items-center justify-between px-1 text-white">
              <span className="text-[13px] font-semibold">Alerts per {bucketLabel}</span>
              <span className="rounded-full bg-white/15 px-2 py-0.5 text-[11px] font-medium">last {winLabel}</span>
            </div>
            {windowAlerts > 0 ? <HeroBars data={volume} dataKey="alerts" name="Alerts" height={190} />
              : <div className="grid h-[190px] place-items-center text-[13px] text-white/80">No alerts raised in this window</div>}
          </div>
          <div className="px-2 pt-5">
            <h3 className="text-[15px] font-semibold text-fg">Alert activity</h3>
            <p className="mt-0.5 text-[12.5px] text-fg-3">
              <span className="font-semibold text-signal">{fmtInt(windowAlerts)}</span> alerts from {fmtInt(windowTxns)} transactions in the last {winLabel}
            </p>
            <div className="mt-5 grid grid-cols-2 gap-4 sm:grid-cols-4">
              {[
                ["Open alerts", fmtInt(stats.open_alerts)],
                ["Investigations", fmtInt(stats.investigations)],
                ["Avg risk (24h)", stats.avg_score_24h ? Number(stats.avg_score_24h).toFixed(1) : "—"],
                ["Volume (24h)", fmtMoney(stats.amount_24h, "USD").replace(/\.\d+$/, "")],
              ].map(([label, value]) => (
                <div key={label}>
                  <div className="num text-[18px] font-semibold text-fg">{value}</div>
                  <div className="mt-0.5 text-[11.5px] text-fg-3">{label}</div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <Panel className="xl:col-span-7" title="Transaction volume" subtitle={`Persisted transactions per ${bucketLabel} · ingestion time`}
          actions={<span className="num text-[12px] text-fg-3">{fmtInt(windowTxns)} in window</span>}>
          {windowTxns > 0 ? <VolumeChart data={volume} height={290} /> :
            <EmptyState title="No transactions in this window">Start the simulator (<span className="num">make demo</span>) or generate traffic below.</EmptyState>}
        </Panel>
      </div>

      <div className="grid gap-6 xl:grid-cols-3">
        <Panel title="Risk categories" subtitle="Scored transactions, last 24h"><CategoryList items={risk_categories} /></Panel>
        <Panel title="Risk score distribution" subtitle="Last 24h · 10-point score bands">
          <BarsChart data={risk_distribution.map((d) => ({ ...d, band: d.range.split("-")[0] }))} x="band" y="count" name="Transactions" height={190} />
          <p className="mt-1 text-center text-[11px] text-fg-3">score band floor (0 = scores 0–9)</p>
        </Panel>
        <Panel title="Merchant category risk" subtitle="Average risk score · dbt mart fct_risk_by_category">
          {categories.length ? <BarsChart data={categories} x="category" y="score" name="Avg risk score" layout="vertical" height={210} categoryWidth={104}
            valueFormatter={(v) => Number(v).toFixed(1)} /> : <EmptyState title="Marts not built yet">They appear after the first dbt run.</EmptyState>}
        </Panel>
      </div>

      <div className="grid gap-6 xl:grid-cols-3">
        <Panel className="xl:col-span-2" title="Recent alerts" subtitle="Model score at or above the active model's decision threshold"
          actions={<Link to="/investigations" className="inline-flex items-center gap-1 text-[12.5px] font-semibold text-signal hover:underline">Open queue <ArrowRight className="h-3.5 w-3.5" /></Link>}
          bodyClass="p-0 pt-3">
          {recent_alerts.length === 0 ? <EmptyState title="No alerts yet" /> : (
            <div className="overflow-x-auto"><table className="w-full min-w-[680px] table-fixed">
              <thead className="table-head"><tr><th className="w-[96px] pl-6">Time</th><th className="w-[120px]">Customer</th><th>Merchant</th><th className="w-[104px] text-right">Amount</th><th className="w-[132px]">Risk</th><th className="w-[28%] pr-6">Top factor</th></tr></thead>
              <tbody>
                {recent_alerts.map((a) => (
                  <tr key={a.alert_id} className="table-row">
                    <td className="num pl-6 text-fg-3">{fmtTime(a.event_timestamp)}</td>
                    <td className="num font-medium">{a.customer_id}</td>
                    <td className="truncate">{a.merchant_name}</td>
                    <td className="num text-right font-medium">{fmtMoney(a.amount, a.currency)}</td>
                    <td><RiskBadge category={a.risk_category} score={a.risk_score} /></td>
                    <td className="truncate pr-6 text-[12px] text-fg-3" title={a.top_reasons[0]}>{a.top_reasons[0] ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          )}
        </Panel>
        <Panel title="System health" subtitle={health.data?.consumer_heartbeat_age_s != null ? `Consumer heartbeat ${health.data.consumer_heartbeat_age_s}s ago` : undefined}>
          {health.data ? (
            <ul className="space-y-1">
              {Object.entries(health.data.services).map(([name, s]) => (
                <li key={name} className="flex items-center gap-3 rounded-lg px-2 py-2 text-[13px] hover:bg-hover">
                  <StatusDot status={s.status === "up" ? "up" : s.status === "down" ? "down" : "unknown"} />
                  <span className="font-medium capitalize">{name}</span>
                  <span className="num ml-auto text-[12px] text-fg-3">{s.status === "up" ? `${s.latency_ms} ms` : s.status}</span>
                </li>
              ))}
            </ul>
          ) : health.isError ? <ErrorState error={health.error} /> : <LoadingBlock rows={4} />}
        </Panel>
      </div>
      <SimulatorControls />
    </div>
  );
}
