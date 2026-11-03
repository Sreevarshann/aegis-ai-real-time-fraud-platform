import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { BarsChart, LinesChart } from "../components/charts";
import { EmptyState, ErrorState, LoadingBlock, Panel, Pill, Stat, StatusDot } from "../components/ui";
import { api } from "../lib/api";
import { isAdmin, useAuth } from "../lib/auth";
import { fmtAgo, fmtInt, fmtTime, titleCase } from "../lib/format";

interface Health { services: Record<string, { status: string; latency_ms: number; detail: string | null }>; consumer_heartbeat_age_s: number | null; dbt_last_run_age_s: number | null; llm: { enabled: boolean; model: string } }
interface Pipeline {
  windows: { window_ended_at: string; consumed: number; persisted: number; duplicates: number; dead_lettered: number; late: number; errors: number; consumer_lag: number | null; avg_processing_ms: number | null }[];
  totals: { consumed: number; persisted: number; duplicates: number; dead_lettered: number; late: number; errors: number; consumer_lag: number | null; last_heartbeat: string | null };
  consumer_metrics: Record<string, number | string | boolean | null>;
}
interface DL { items: { dead_letter_id: number; reason: string; error_detail: string; received_at: string }[] }
interface DQ { history: { checked_at: string; passed: number; warned: number; failed: number }[] }
interface Audit { items: { audit_id: number; action: string; entity_type: string; entity_id: string | null; actor: string | null; created_at: string }[] }

export default function Operations() {
  const { user } = useAuth();
  const h = useQuery({ queryKey: ["health"], queryFn: () => api<Health>("/operations/health"), refetchInterval: 10_000 });
  const p = useQuery({ queryKey: ["pipeline"], queryFn: () => api<Pipeline>("/operations/pipeline?minutes=60"), refetchInterval: 10_000 });
  const dl = useQuery({ queryKey: ["dead-letters-ops"], queryFn: () => api<DL>("/dead-letters?limit=10"), refetchInterval: 15_000 });
  const dq = useQuery({ queryKey: ["dq-history"], queryFn: () => api<DQ>("/data-quality?history_hours=6"), refetchInterval: 30_000 });
  const audit = useQuery({ queryKey: ["audit"], queryFn: () => api<Audit>("/operations/audit?limit=15"), enabled: isAdmin(user) });

  const cm = p.data?.consumer_metrics ?? {};
  const windows = (p.data?.windows ?? []).map((w) => ({ ...w, bucket: w.window_ended_at }));
  const dlqTotal = Object.entries(cm).filter(([k]) => k.startsWith("aegis_events_dead_lettered_total")).reduce((a, [, v]) => a + Number(v), 0);

  return (
    <div className="space-y-5">
      <Panel title="Service health" subtitle={h.data ? `Consumer heartbeat ${h.data.consumer_heartbeat_age_s != null ? `${h.data.consumer_heartbeat_age_s}s ago` : "never"} · dbt last ran ${h.data.dbt_last_run_age_s != null ? `${Math.round(h.data.dbt_last_run_age_s)}s ago` : "never"}` : undefined}>
        {h.isLoading ? <LoadingBlock rows={3} /> : h.isError ? <ErrorState error={h.error} onRetry={() => h.refetch()} /> : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5" data-testid="service-health">
            {Object.entries(h.data!.services).map(([name, s]) => (
              <div key={name} className={clsx("rounded-lg border p-3", s.status === "down" ? "border-risk-critical/40 bg-risk-critical/5" : "border-line bg-ink-850")}>
                <div className="flex items-center gap-2"><StatusDot status={s.status === "up" ? "up" : s.status === "down" ? "down" : "unknown"} /><span className="text-[13px] font-medium capitalize">{name}</span>
                  <span className="num ml-auto text-[11px] text-mist-500">{s.latency_ms != null ? `${s.latency_ms} ms` : ""}</span></div>
                <div className="mt-1.5 line-clamp-2 text-[11px] text-mist-500" title={s.detail ?? ""}>{s.detail ?? s.status}</div>
              </div>
            ))}
            {!h.data!.llm.enabled && (
              <div className="rounded-lg border border-dashed border-line p-3">
                <div className="flex items-center gap-2"><StatusDot status="unknown" /><span className="text-[13px] font-medium">Ollama (optional)</span></div>
                <div className="mt-1.5 text-[11px] text-mist-500">Disabled — investigations use the deterministic engine.</div>
              </div>
            )}
          </div>
        )}
      </Panel>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-6">
        <Stat label="Consumed" value={fmtInt(cm.aegis_events_consumed_total as number)} hint="since consumer start" />
        <Stat label="Persisted" value={fmtInt(cm.aegis_events_persisted_total as number)} tone="good" />
        <Stat label="Duplicates skipped" value={fmtInt(cm.aegis_events_duplicate_total as number)} hint="idempotent replays" />
        <Stat label="Dead-lettered" value={fmtInt(dlqTotal)} tone="alert" />
        <Stat label="Consumer lag" value={fmtInt(cm.aegis_consumer_lag_messages as number)} hint="messages behind" />
        <Stat label="E2E latency" value={cm.aegis_end_to_end_latency_seconds_avg_ms != null ? `${Number(cm.aegis_end_to_end_latency_seconds_avg_ms).toFixed(0)} ms` : "—"}
          hint={cm.aegis_scoring_seconds_per_event_avg_ms != null ? `scoring ${Number(cm.aegis_scoring_seconds_per_event_avg_ms).toFixed(2)} ms/event` : undefined} />
      </div>
      {!cm.available && !p.isLoading && <p className="text-[12px] text-risk-medium">Consumer metrics endpoint unreachable — counters above are unavailable. {String(cm.error ?? "")}</p>}

      <div className="grid gap-5 xl:grid-cols-2">
        <Panel title="Event throughput" subtitle="Events persisted per 10-second consumer window, last 60 min (from pipeline_stats)">
          {p.isLoading ? <LoadingBlock /> : windows.length ? (
            <LinesChart data={windows} x="bucket" series={[{ key: "persisted", name: "Persisted" }, { key: "duplicates", name: "Duplicates" }, { key: "dead_lettered", name: "Dead-lettered" }]}
              xFormatter={(v) => new Date(v).toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit" })} />
          ) : <EmptyState title="No consumer windows yet" />}
        </Panel>
        <Panel title="Data quality history" subtitle="Failed checks per run, last 6 hours">
          {dq.data?.history.length ? <BarsChart data={dq.data.history.map((r) => ({ ...r, t: fmtTime(r.checked_at) }))} x="t" y="failed" name="Failed checks" color="#9b6cf6" /> : <EmptyState title="No runs yet" />}
        </Panel>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <Panel title="Recent pipeline errors" subtitle={`Rejected events · lifetime totals: ${fmtInt(p.data?.totals.dead_lettered)} quarantined, ${fmtInt(p.data?.totals.errors)} retried infrastructure errors`} bodyClass="p-0">
          {dl.isError ? <ErrorState error={dl.error} /> : !dl.data?.items.length ? <EmptyState title="No pipeline errors" /> : (
            <ul>{dl.data.items.map((d) => (
              <li key={d.dead_letter_id} className="flex items-start gap-3 border-t border-line/70 px-5 py-2.5 first:border-t-0">
                <Pill tone="bad">{d.reason}</Pill><span className="flex-1 text-[12px] text-mist-300">{d.error_detail}</span>
                <span className="num whitespace-nowrap text-[11px] text-mist-500">{fmtAgo(d.received_at)}</span>
              </li>))}
            </ul>
          )}
        </Panel>
        <Panel title="Audit log" subtitle="Security-relevant actions in your tenant" bodyClass="p-0">
          {!isAdmin(user) ? <EmptyState title="Admins only" /> : audit.isLoading ? <div className="p-5"><LoadingBlock /></div> : !audit.data?.items.length ? <EmptyState title="No audit events" /> : (
            <ul>{audit.data.items.map((a) => (
              <li key={a.audit_id} className="flex items-center gap-3 border-t border-line/70 px-5 py-2.5 text-[12px] first:border-t-0">
                <span className="num w-16 text-mist-500">{fmtTime(a.created_at)}</span>
                <span className="font-medium">{titleCase(a.action)}</span>
                <span className="truncate text-mist-500">{a.actor ?? "anonymous"}</span>
              </li>))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}
