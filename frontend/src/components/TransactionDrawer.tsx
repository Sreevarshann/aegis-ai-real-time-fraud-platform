import { useMutation, useQuery } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api, post } from "../lib/api";
import { canAnalyze, useAuth } from "../lib/auth";
import { fmtMoney, fmtTime, titleCase } from "../lib/format";
import type { Investigation, TransactionDetail } from "../lib/types";
import { ErrorState, KeyValue, LoadingBlock, Pill, RiskBadge, Spinner } from "./ui";

export default function TransactionDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ["txn", id], queryFn: () => api<TransactionDetail>(`/transactions/${id}`) });
  const investigate = useMutation({
    mutationFn: () => post<Investigation>("/investigations", { transaction_id: id }),
    onSuccess: (inv) => navigate(`/investigations/${inv.investigation_id}`),
  });
  const t = q.data;
  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-label="Transaction details">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <aside className="relative h-full w-full max-w-[520px] animate-fadein overflow-y-auto border-l border-line bg-ink-900 p-6">
        <div className="mb-5 flex items-start justify-between">
          <div>
            <div className="eyebrow">Transaction</div>
            <div className="num mt-1 break-all text-[13px] text-mist-300">{id}</div>
          </div>
          <button onClick={onClose} aria-label="Close" className="text-mist-500 hover:text-mist-100"><X className="h-5 w-5" /></button>
        </div>
        {q.isLoading && <LoadingBlock rows={8} />}
        {q.isError && <ErrorState error={q.error} onRetry={() => q.refetch()} />}
        {t && (
          <div className="space-y-6">
            <div className="flex items-end justify-between">
              <div className="num text-[28px] font-medium">{fmtMoney(t.amount, t.currency)}</div>
              <RiskBadge category={t.risk_category} score={t.risk_score} />
            </div>
            <KeyValue items={[
              ["Event time", fmtTime(t.event_timestamp, true)],
              ["Ingested", fmtTime(t.ingested_at, true)],
              ["Customer", <span className="num">{t.customer_id}</span>],
              ["Merchant", <>{t.merchant_name} <span className="text-mist-500">· {titleCase(t.merchant_category)}</span></>],
              ["Country / channel", `${t.country} · ${titleCase(t.payment_channel)}`],
              ["Device", <span className="num">{t.device_id}</span>],
              ["Status", <Pill tone={t.status === "declined" ? "bad" : "neutral"}>{t.status}</Pill>],
              ["Delivery", <>{t.is_late ? <Pill tone="warn">late / out of order</Pill> : "in order"} <span className="num text-mist-500">· p{t.kafka_partition} @ {t.kafka_offset}</span></>],
              ["Model", <span className="num">{t.model_version} · threshold {Math.round(t.decision_threshold * 100)}</span>],
              ["Scoring latency", <span className="num">{t.scoring_latency_ms.toFixed(2)} ms</span>],
            ]} />
            <div>
              <div className="eyebrow mb-2">Main contributing factors</div>
              <p className="mb-3 text-[11px] text-mist-500">Change in fraud probability when each feature is reset to its training median (single-feature occlusion).</p>
              {t.explanation.length === 0 ? <p className="text-[13px] text-mist-500">No feature raised the score materially.</p> : (
                <ul className="space-y-2">
                  {t.explanation.map((e, i) => (
                    <li key={e.feature} className="rounded-lg border border-line bg-ink-850 px-3 py-2">
                      <div className="flex items-center justify-between gap-3 text-[13px]">
                        <span>{t.explanation_text[i]?.replace(/ \(\+[\d.]+ pts\)$/, "")}</span>
                        <span className="num shrink-0 text-risk-high">+{(e.contribution * 100).toFixed(1)}</span>
                      </div>
                      <div className="mt-1.5 h-1 overflow-hidden rounded bg-ink-700">
                        <div className="h-full bg-risk-high" style={{ width: `${Math.min(100, e.contribution * 100)}%` }} />
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <details className="rounded-lg border border-line bg-ink-850 px-3 py-2 text-[12px]">
              <summary className="cursor-pointer text-mist-300">All model features ({Object.keys(t.features).length})</summary>
              <table className="mt-2 w-full">
                <tbody>
                  {Object.entries(t.features).map(([k, v]) => (
                    <tr key={k}><td className="py-0.5 text-mist-500">{k}</td><td className="num py-0.5 text-right">{v == null ? "missing" : v}</td></tr>
                  ))}
                </tbody>
              </table>
            </details>
            {canAnalyze(user) && (
              <button className="btn-primary w-full justify-center" onClick={() => investigate.mutate()} disabled={investigate.isPending}>
                {investigate.isPending ? <Spinner /> : <Search className="h-4 w-4" />}Run investigation
              </button>
            )}
            {investigate.isError && <p className="text-[12px] text-risk-critical">{(investigate.error as Error).message}</p>}
          </div>
        )}
      </aside>
    </div>
  );
}
