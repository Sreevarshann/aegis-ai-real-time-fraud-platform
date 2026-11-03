import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowRight, Search } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { EmptyState, ErrorState, LoadingBlock, Panel, Pill, RiskBadge, Spinner } from "../components/ui";
import { api, post } from "../lib/api";
import { canAnalyze, useAuth } from "../lib/auth";
import { fmtAgo, fmtInt, fmtMoney, titleCase } from "../lib/format";
import type { Alert, Investigation, InvestigationRow } from "../lib/types";

const TABS = ["open", "investigating", "escalated", "confirmed_fraud", "dismissed"] as const;
export const PRIORITY_TONE = { P1: "bad", P2: "warn", P3: "blue", P4: "neutral" } as const;

export default function InvestigationsPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [tab, setTab] = useState<(typeof TABS)[number]>("open");
  const alerts = useQuery({
    queryKey: ["alerts", tab], queryFn: () => api<{ items: Alert[]; counts: Record<string, number> }>(`/alerts?status=${tab}&limit=100`),
    refetchInterval: 10_000,
  });
  const invs = useQuery({ queryKey: ["investigations"], queryFn: () => api<{ items: InvestigationRow[] }>("/investigations?limit=20") });
  const start = useMutation({
    mutationFn: (transaction_id: string) => post<Investigation>("/investigations", { transaction_id }),
    onSuccess: (inv) => { qc.invalidateQueries({ queryKey: ["alerts"] }); navigate(`/investigations/${inv.investigation_id}`); },
  });

  return (
    <div className="grid gap-5 2xl:grid-cols-[1fr_380px]">
      <Panel title="Suspicious transaction queue" subtitle="Alerts raised by the streaming risk model, newest first" bodyClass="p-0"
        actions={<div className="flex flex-wrap gap-1">
          {TABS.map((t) => (
            <button key={t} onClick={() => setTab(t)} className={clsx("rounded-md px-2.5 py-1 text-[12px]",
              tab === t ? "bg-signal/15 text-mist-100" : "text-mist-400 hover:text-mist-100")}>
              {titleCase(t)} <span className="num text-mist-500">{fmtInt(alerts.data?.counts[t] ?? 0)}</span>
            </button>
          ))}
        </div>}>
        {alerts.isLoading ? <div className="p-5"><LoadingBlock rows={8} /></div> : alerts.isError ? <ErrorState error={alerts.error} onRetry={() => alerts.refetch()} /> :
          !alerts.data?.items.length ? <EmptyState title={`No ${titleCase(tab).toLowerCase()} alerts`} /> : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px]" data-testid="alert-queue">
                <thead className="table-head"><tr><th>Raised</th><th>Risk</th><th>Customer</th><th>Merchant</th><th className="text-right">Amount</th><th>Why it was flagged</th><th></th></tr></thead>
                <tbody>
                  {alerts.data.items.map((a) => (
                    <tr key={a.alert_id} className="table-row">
                      <td className="text-mist-300">{fmtAgo(a.created_at)}</td>
                      <td><RiskBadge category={a.risk_category} score={a.risk_score} /></td>
                      <td className="num">{a.customer_id}<div className="text-[11px] text-mist-500">{a.country} · {titleCase(a.payment_channel)}</div></td>
                      <td className="max-w-[180px] truncate">{a.merchant_name}<div className="text-[11px] text-mist-500">{titleCase(a.merchant_category)}</div></td>
                      <td className="num text-right">{fmtMoney(a.amount, a.currency)}</td>
                      <td className="max-w-[320px] text-[12px] text-mist-400">{a.top_reasons.slice(0, 2).map((r) => <div key={r} className="truncate">{r}</div>)}</td>
                      <td className="text-right">
                        {a.investigation_id ? (
                          <Link to={`/investigations/${a.investigation_id}`} className="btn-ghost">
                            {a.investigation_priority && <Pill tone={PRIORITY_TONE[a.investigation_priority as keyof typeof PRIORITY_TONE]}>{a.investigation_priority}</Pill>}Open<ArrowRight className="h-3.5 w-3.5" />
                          </Link>
                        ) : canAnalyze(user) ? (
                          <button className="btn-primary" disabled={start.isPending} onClick={() => start.mutate(a.transaction_id)}>
                            {start.isPending && start.variables === a.transaction_id ? <Spinner /> : <Search className="h-3.5 w-3.5" />}Investigate
                          </button>
                        ) : <span className="text-[12px] text-mist-500">view only</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        {start.isError && <p className="p-4 text-[12px] text-risk-critical">{(start.error as Error).message}</p>}
      </Panel>

      <Panel title="Recent investigations" bodyClass="p-0">
        {invs.isLoading ? <div className="p-5"><LoadingBlock /></div> : invs.isError ? <ErrorState error={invs.error} /> :
          !invs.data?.items.length ? <EmptyState title="No investigations yet">Pick an alert and press Investigate.</EmptyState> : (
            <ul>
              {invs.data.items.map((i) => (
                <li key={i.investigation_id} className="border-t border-line/70 first:border-t-0">
                  <Link to={`/investigations/${i.investigation_id}`} className="flex items-center gap-3 px-5 py-3 hover:bg-ink-800/60">
                    <Pill tone={PRIORITY_TONE[i.priority as keyof typeof PRIORITY_TONE]}>{i.priority}</Pill>
                    <div className="min-w-0 flex-1">
                      <div className="num truncate text-[12px] text-mist-300">{i.transaction_id.slice(0, 18)}…</div>
                      <div className="text-[11px] text-mist-500">{i.indicator_count} indicators · score {i.risk_score ?? "—"} · {fmtAgo(i.created_at)}</div>
                    </div>
                    <Pill tone={i.engine === "ollama" ? "teal" : "neutral"}>{i.engine === "ollama" ? "Local LLM" : "Deterministic"}</Pill>
                  </Link>
                </li>
              ))}
            </ul>
          )}
      </Panel>
    </div>
  );
}
