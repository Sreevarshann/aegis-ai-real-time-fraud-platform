import { useQuery } from "@tanstack/react-query";
import { Activity, AlertOctagon, Gauge, Layers } from "lucide-react";
import { Link } from "react-router-dom";
import { BarsChart, VolumeChart } from "../components/charts";
import SimulatorControls from "../components/SimulatorControls";
import { EmptyState, ErrorState, LoadingBlock, Panel, RISK_HEX, RiskBadge, Stat, StatusDot } from "../components/ui";
import { api } from "../lib/api";
import { fmtAgo, fmtInt, fmtMoney, fmtTime } from "../lib/format";
import type { Alert, RiskCategory } from "../lib/types";

interface Overview {
  stats: { total_transactions: number; last_60s: number; transactions_per_second: number; last_24h: number; total_alerts: number;
    open_alerts: number; alerts_24h: number; investigations: number; avg_score_24h: string | null; last_ingested_at: string | null };
  volume: { bucket: string; transactions: number; alerts: number }[];
  risk_distribution: { range: string; count: number }[];
  risk_categories: { category: RiskCategory; count: number }[];
  recent_alerts: Alert[];
}
interface Health { services: Record<string, { status: string; latency_ms: number }>; consumer_heartbeat_age_s: number | null }

/** Counts differ by orders of magnitude (most traffic is low risk), so show exact numbers + shares, not a bar chart. */
function CategoryList({ items }: { items: { category: RiskCategory; count: number }[] }) {
  const total = items.reduce((a, c) => a + c.count, 0) || 1;
  return (
    <ul className="space-y-4 py-2" aria-label="Risk categories">
      {items.map((c) => (
        <li key={c.category}>
          <div className="mb-1.5 flex items-baseline justify-between text-[13px]">
            <span className="flex items-center gap-2 capitalize"><span className="h-2 w-2 rounded-sm" style={{ background: RISK_HEX[c.category] }} />{c.category}</span>
            <span className="num text-mist-100">{fmtInt(c.count)} <span className="text-mist-500">· {((c.count / total) * 100).toFixed(c.count / total < 0.01 ? 2 : 1)}%</span></span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-ink-700">
            <div className="h-full rounded-full" style={{ width: `${Math.max((c.count / total) * 100, c.count ? 0.8 : 0)}%`, background: RISK_HEX[c.category] }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

export default function OverviewPage() {
  const q = useQuery({ queryKey: ["overview"], queryFn: () => api<Overview>("/overview?window_minutes=60"), refetchInterval: 5000 });
  const health = useQuery({ queryKey: ["health"], queryFn: () => api<Health>("/operations/health"), refetchInterval: 15_000 });

  if (q.isLoading) return <div className="grid gap-4 md:grid-cols-4">{[0, 1, 2, 3].map((i) => <Panel key={i}><LoadingBlock rows={2} /></Panel>)}</div>;
  if (q.isError || !q.data) return <Panel><ErrorState error={q.error} onRetry={() => q.refetch()} /></Panel>;
  const { stats, volume, risk_distribution, risk_categories, recent_alerts } = q.data;
  const highRisk = risk_categories.filter((c) => c.category === "high" || c.category === "critical").reduce((a, c) => a + c.count, 0);

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Total transactions" value={fmtInt(stats.total_transactions)} icon={<Layers className="h-4 w-4" />}
          hint={<>{fmtInt(stats.last_24h)} in last 24h · last {fmtAgo(stats.last_ingested_at)}</>} />
        <Stat label="Live rate" value={<>{stats.transactions_per_second.toFixed(2)}<span className="ml-1 text-[13px] text-mist-500">tx/s</span></>}
          icon={<Activity className="h-4 w-4" />} tone="good" hint={`${fmtInt(stats.last_60s)} ingested in the last 60s`} />
        <Stat label="Suspicious activity" value={fmtInt(stats.open_alerts)} icon={<AlertOctagon className="h-4 w-4" />} tone="alert"
          hint={`${fmtInt(stats.alerts_24h)} alerts in 24h · ${fmtInt(highRisk)} high/critical scores`} />
        <Stat label="Avg risk score (24h)" value={stats.avg_score_24h ? Number(stats.avg_score_24h).toFixed(1) : "—"} icon={<Gauge className="h-4 w-4" />}
          hint={`${fmtInt(stats.investigations)} investigations opened`} />
      </div>

      <div className="grid gap-5 xl:grid-cols-3">
        <Panel className="xl:col-span-2" title="Transaction volume" subtitle="Persisted transactions per minute, last 60 minutes (ingestion time)">
          {volume.some((v) => v.transactions > 0) ? <VolumeChart data={volume} height={240} /> :
            <EmptyState title="No transactions in the last hour">Start the simulator (<span className="num">make demo</span>) or generate traffic below.</EmptyState>}
        </Panel>
        <Panel title="Risk categories" subtitle="Scored transactions, last 24h">
          <CategoryList items={risk_categories} />
        </Panel>
      </div>

      <div className="grid gap-5 xl:grid-cols-3">
        <Panel className="xl:col-span-2" title="Recent alerts" subtitle="Model score at or above the active model's decision threshold"
          actions={<Link to="/investigations" className="text-[12px] text-signal hover:underline">Open queue →</Link>} bodyClass="p-0">
          {recent_alerts.length === 0 ? <EmptyState title="No alerts yet" /> : (
            <div className="overflow-x-auto"><table className="w-full min-w-[820px] table-fixed">
              <thead className="table-head"><tr><th className="w-[92px]">Time</th><th className="w-[120px]">Customer</th><th>Merchant</th><th className="w-[110px] text-right">Amount</th><th className="w-[130px]">Risk</th><th className="w-[30%]">Top factor</th></tr></thead>
              <tbody>
                {recent_alerts.map((a) => (
                  <tr key={a.alert_id} className="table-row">
                    <td className="num text-mist-300">{fmtTime(a.event_timestamp)}</td>
                    <td className="num">{a.customer_id}</td>
                    <td className="truncate">{a.merchant_name}</td>
                    <td className="num text-right">{fmtMoney(a.amount, a.currency)}</td>
                    <td><RiskBadge category={a.risk_category} score={a.risk_score} /></td>
                    <td className="truncate text-[12px] text-mist-400" title={a.top_reasons[0]}>{a.top_reasons[0] ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          )}
        </Panel>
        <div className="space-y-5">
          <Panel title="Risk score distribution" subtitle="Last 24h, 10-point bands">
            <BarsChart data={risk_distribution.map((d) => ({ ...d, band: d.range.split("-")[0] }))} x="band" y="count"
              name="Transactions" height={170} color="#4c8dff" />
            <p className="mt-1 text-center text-[11px] text-mist-500">score band floor (0 = scores 0–9)</p>
          </Panel>
          <Panel title="System health">
            {health.data ? (
              <ul className="space-y-2">
                {Object.entries(health.data.services).map(([name, s]) => (
                  <li key={name} className="flex items-center gap-2 text-[13px]">
                    <StatusDot status={s.status === "up" ? "up" : s.status === "down" ? "down" : "unknown"} />
                    <span className="capitalize">{name}</span>
                    <span className="num ml-auto text-[12px] text-mist-500">{s.status === "up" ? `${s.latency_ms} ms` : s.status}</span>
                  </li>
                ))}
              </ul>
            ) : health.isError ? <ErrorState error={health.error} /> : <LoadingBlock rows={4} />}
          </Panel>
        </div>
      </div>
      <SimulatorControls />
    </div>
  );
}
