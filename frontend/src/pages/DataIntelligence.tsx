import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, CircleAlert, PlayCircle, XCircle } from "lucide-react";
import { BarsChart } from "../components/charts";
import { EmptyState, ErrorState, LoadingBlock, Panel, Pill, Spinner } from "../components/ui";
import { api, post } from "../lib/api";
import { canAnalyze, useAuth } from "../lib/auth";
import { fmtAgo, fmtInt, fmtPct, fmtTime, titleCase } from "../lib/format";

interface DQRow { check_name: string; dimension: string; status: "pass" | "warn" | "fail"; observed_value: number | null; threshold: number | null; details: { description: string }; checked_at: string }
interface DQ { latest: DQRow[]; history: { checked_at: string; passed: number; warned: number; failed: number }[] }
interface DL { items: { dead_letter_id: number; reason: string; error_detail: string; raw_payload: string; source_partition: number; source_offset: number; received_at: string; tenant_id: string | null }[]; by_reason: { reason: string; count: number; last_seen: string }[] }
type Row = Record<string, string | number | null>;
interface Analytics { available: boolean; marts: Record<string, Row[] | null>; transformations: { invocation_id: string; invocation_completed_at: string; node_id: string; resource_type: string; status: string; execution_time_s: number; rows_affected: number | null; message: string }[] }

const STATUS_ICON = {
  pass: <CheckCircle2 className="h-4 w-4 text-risk-low" />, warn: <CircleAlert className="h-4 w-4 text-risk-medium" />, fail: <XCircle className="h-4 w-4 text-risk-critical" />,
};

export default function DataIntelligence() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const dq = useQuery({ queryKey: ["dq"], queryFn: () => api<DQ>("/data-quality?history_hours=6"), refetchInterval: 20_000 });
  const dl = useQuery({ queryKey: ["dead-letters"], queryFn: () => api<DL>("/dead-letters?limit=25"), refetchInterval: 15_000 });
  const an = useQuery({ queryKey: ["analytics"], queryFn: () => api<Analytics>("/analytics"), refetchInterval: 60_000 });
  const run = useMutation({ mutationFn: () => post("/data-quality/run", {}), onSuccess: () => qc.invalidateQueries({ queryKey: ["dq"] }) });

  const latestInvocation = an.data?.transformations[0]?.invocation_id;
  const dbtRows = an.data?.transformations.filter((t) => t.invocation_id === latestInvocation) ?? [];
  const dbtFailed = dbtRows.filter((t) => ["fail", "error"].includes(t.status)).length;
  const marts = an.data?.marts ?? {};

  return (
    <div className="space-y-5">
      <div className="grid gap-5 xl:grid-cols-3">
        <Panel className="xl:col-span-2" title="Data quality checks" subtitle={dq.data?.latest[0] ? `Latest run ${fmtAgo(dq.data.latest[0].checked_at)} · runs every 60s in the consumer` : "Operational checks over the pipeline output"}
          actions={canAnalyze(user) && <button className="btn-ghost" onClick={() => run.mutate()} disabled={run.isPending}>{run.isPending ? <Spinner /> : <PlayCircle className="h-3.5 w-3.5" />}Run checks now</button>}
          bodyClass="p-0">
          {dq.isLoading ? <div className="p-5"><LoadingBlock rows={8} /></div> : dq.isError ? <ErrorState error={dq.error} onRetry={() => dq.refetch()} /> :
            !dq.data?.latest.length ? <EmptyState title="No checks have run yet">Checks run automatically once the consumer is up.</EmptyState> : (
              <table className="w-full" data-testid="dq-table">
                <thead className="table-head"><tr><th></th><th>Check</th><th>Dimension</th><th className="text-right">Observed</th><th className="text-right">Threshold</th></tr></thead>
                <tbody>
                  {dq.data.latest.map((c) => (
                    <tr key={c.check_name} className="table-row">
                      <td className="w-8">{STATUS_ICON[c.status]}</td>
                      <td><div className="num text-[12px]">{c.check_name}</div><div className="text-[11px] text-mist-500">{c.details.description}</div></td>
                      <td><Pill>{c.dimension}</Pill></td>
                      <td className="num text-right">{c.observed_value ?? "n/a"}</td>
                      <td className="num text-right text-mist-500">{c.threshold ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
        </Panel>
        <Panel title="Validation failures" subtitle="Quarantined to the dead-letter topic + table, by reason">
          {dl.isLoading ? <LoadingBlock /> : dl.isError ? <ErrorState error={dl.error} /> : !dl.data?.by_reason.length ? <EmptyState title="No rejected events" /> :
            <BarsChart data={dl.data.by_reason} x="reason" y="count" name="Events" layout="vertical" height={Math.max(160, dl.data.by_reason.length * 34)} color="#9b6cf6" />}
        </Panel>
      </div>

      <Panel title="Quarantined events" subtitle="Most recent dead letters with the exact rejection reason" bodyClass="p-0">
        {dl.data?.items.length ? (
          <div className="max-h-[360px] overflow-auto">
            <table className="w-full min-w-[900px]" data-testid="dead-letter-table">
              <thead className="table-head sticky top-0 bg-ink-900"><tr><th>Received</th><th>Reason</th><th>Detail</th><th>Source</th><th>Payload (truncated)</th></tr></thead>
              <tbody>
                {dl.data.items.map((d) => (
                  <tr key={d.dead_letter_id} className="table-row align-top">
                    <td className="num whitespace-nowrap text-mist-300">{fmtTime(d.received_at)}</td>
                    <td><Pill tone="bad">{d.reason}</Pill></td>
                    <td className="max-w-[280px] text-[12px] text-mist-300">{d.error_detail}</td>
                    <td className="num whitespace-nowrap text-[12px] text-mist-500">p{d.source_partition}@{d.source_offset}</td>
                    <td className="num max-w-[320px] truncate text-[11px] text-mist-500">{d.raw_payload}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <EmptyState title="Nothing quarantined" />}
      </Panel>

      <div className="grid gap-5 xl:grid-cols-2">
        <Panel title="dbt transformations" subtitle={latestInvocation ? `Latest invocation ${fmtAgo(dbtRows[0]?.invocation_completed_at)} · ${dbtRows.length} nodes · ${dbtFailed} failed` : "dbt Core runs every 2 minutes"} bodyClass="p-0">
          {an.isLoading ? <div className="p-5"><LoadingBlock /></div> : !dbtRows.length ? <EmptyState title="dbt has not run yet" /> : (
            <div className="max-h-[340px] overflow-auto">
              <table className="w-full" data-testid="dbt-table">
                <thead className="table-head sticky top-0 bg-ink-900"><tr><th>Node</th><th>Type</th><th>Status</th><th className="text-right">Time</th></tr></thead>
                <tbody>
                  {dbtRows.map((t) => (
                    <tr key={t.node_id} className="table-row">
                      <td className="num max-w-[320px] truncate text-[12px]">{t.node_id.split(".").slice(2).join(".")}</td>
                      <td className="text-mist-400">{t.resource_type}</td>
                      <td><Pill tone={["pass", "success"].includes(t.status) ? "good" : t.status === "warn" ? "warn" : "bad"}>{t.status}</Pill></td>
                      <td className="num text-right text-mist-400">{t.execution_time_s?.toFixed(2)}s</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
        <Panel title="Data completeness (dbt)" subtitle="analytics.dq_completeness for your tenant" bodyClass="p-0">
          {marts.completeness?.length ? (
            <table className="w-full">
              <thead className="table-head"><tr><th>Check</th><th className="text-right">Rows</th><th className="text-right">Failing</th><th className="text-right">Pass rate</th></tr></thead>
              <tbody>
                {marts.completeness.map((c) => (
                  <tr key={String(c.check_name)} className="table-row">
                    <td>{titleCase(String(c.check_name))}</td><td className="num text-right">{fmtInt(c.total_rows)}</td>
                    <td className="num text-right">{fmtInt(c.failing_rows)}</td><td className="num text-right">{fmtPct(Number(c.pass_rate), 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <EmptyState title="Marts not built yet">They appear after the first dbt build.</EmptyState>}
        </Panel>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <Panel title="Hourly volume (dbt mart)" subtitle="analytics.fct_hourly_volume · event time">
          {marts.hourly_volume?.length ? <BarsChart data={[...marts.hourly_volume].reverse().map((h) => ({ ...h,
            label: new Date(String(h.hour)).toLocaleString("en-US", { hour12: false, month: "short", day: "numeric", hour: "2-digit" }) }))}
            x="label" y="transactions" name="Transactions" /> : <EmptyState title="No data yet" />}
        </Panel>
        <Panel title="Risk by merchant category (dbt mart)" subtitle="Average risk score · analytics.fct_risk_by_category">
          {marts.risk_by_category?.length ? <BarsChart data={marts.risk_by_category.map((r) => ({ ...r, avg_risk_score: Number(r.avg_risk_score) }))}
            x="merchant_category" y="avg_risk_score" name="Avg risk score" layout="vertical" height={330} /> : <EmptyState title="No data yet" />}
        </Panel>
      </div>

      <Panel title="Fraud rate trend (dbt mart)" subtitle="Simulated fraud rate vs. alert rate and precision · evaluation against simulator labels" bodyClass="p-0">
        {marts.fraud_rate_trend?.length ? (
          <table className="w-full">
            <thead className="table-head"><tr><th>Day</th><th className="text-right">Transactions</th><th className="text-right">Labelled fraud</th><th className="text-right">Alerts</th><th className="text-right">True positives</th><th className="text-right">Fraud rate</th><th className="text-right">Alert rate</th><th className="text-right">Alert precision</th></tr></thead>
            <tbody>
              {marts.fraud_rate_trend.map((d) => (
                <tr key={String(d.day)} className="table-row">
                  <td className="num">{String(d.day)}</td><td className="num text-right">{fmtInt(d.transactions)}</td><td className="num text-right">{fmtInt(d.labelled_fraud)}</td>
                  <td className="num text-right">{fmtInt(d.alerts)}</td><td className="num text-right">{fmtInt(d.true_positives)}</td>
                  <td className="num text-right">{fmtPct(Number(d.simulated_fraud_rate), 2)}</td><td className="num text-right">{fmtPct(Number(d.alert_rate), 2)}</td>
                  <td className="num text-right">{d.alert_precision == null ? "—" : fmtPct(Number(d.alert_precision), 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <EmptyState title="No data yet" />}
      </Panel>
    </div>
  );
}
