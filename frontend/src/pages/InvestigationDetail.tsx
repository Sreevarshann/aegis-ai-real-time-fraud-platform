import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Bot, CircleAlert, Cpu, FileSearch, ShieldAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ErrorState, LoadingBlock, Panel, Pill, RiskBadge, Spinner } from "../components/ui";
import { api, patch } from "../lib/api";
import { canAnalyze, useAuth } from "../lib/auth";
import { fmtTime, titleCase } from "../lib/format";
import type { Investigation } from "../lib/types";
import { PRIORITY_TONE } from "./Investigations";

const REVIEW = ["pending_review", "in_review", "escalated", "closed_fraud", "closed_legitimate"] as const;

export default function InvestigationDetail() {
  const { id } = useParams();
  const { user } = useAuth();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["investigation", id], queryFn: () => api<Investigation>(`/investigations/${id}`) });
  const [status, setStatus] = useState("in_review");
  const [notes, setNotes] = useState("");
  useEffect(() => {
    if (q.data) { setStatus(q.data.review_status === "pending_review" ? "in_review" : q.data.review_status); setNotes(q.data.reviewer_notes ?? ""); }
  }, [q.data]);
  const save = useMutation({
    mutationFn: () => patch<Investigation>(`/investigations/${id}`, { review_status: status, notes: notes || null }),
    onSuccess: (inv) => { qc.setQueryData(["investigation", id], inv); qc.invalidateQueries({ queryKey: ["alerts"] }); },
  });

  if (q.isLoading) return <Panel><LoadingBlock rows={10} /></Panel>;
  if (q.isError || !q.data) return <Panel><ErrorState error={q.error} onRetry={() => q.refetch()} /></Panel>;
  const inv = q.data;
  const r = inv.report;
  const llm = inv.engine === "ollama";

  return (
    <div className="space-y-5">
      <Link to="/investigations" className="inline-flex items-center gap-1.5 text-[12px] text-mist-400 hover:text-mist-100"><ArrowLeft className="h-3.5 w-3.5" />Back to queue</Link>
      <div className="panel animate-fadein flex flex-wrap items-center gap-4 p-5">
        <div className="grid h-11 w-11 place-items-center rounded-xl bg-risk-critical/10 ring-1 ring-risk-critical/30"><ShieldAlert className="h-5 w-5 text-risk-critical" /></div>
        <div className="min-w-0 flex-1">
          <div className="eyebrow">Investigation · {inv.investigation_id.slice(0, 8)}</div>
          <div className="mt-1 text-[15px] font-medium">{r.transaction_summary}</div>
          <div className="mt-1 text-[12px] text-mist-500">Opened by {inv.created_by_name} · {fmtTime(inv.created_at, true)} · {inv.duration_ms.toFixed(0)} ms</div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <RiskBadge category={r.risk_category} score={r.risk_score} />
          <Pill tone={PRIORITY_TONE[inv.priority]}>Priority {inv.priority}</Pill>
          <span data-testid="engine-badge">
            <Pill tone={llm ? "teal" : "blue"}>{llm ? <Bot className="h-3 w-3" /> : <Cpu className="h-3 w-3" />}
              {llm ? `Local LLM · ${inv.llm_model}` : "Deterministic engine"}</Pill>
          </span>
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-3">
        <div className="space-y-5 xl:col-span-2">
          <Panel title="Findings" subtitle={llm ? "Narrative written by a local LLM from retrieved evidence; passed the grounding check" : "Deterministic narrative assembled from retrieved evidence"}>
            <p className="text-[14px] leading-relaxed text-mist-100" data-testid="narrative">{r.narrative}</p>
            {r.llm_note && <p className="mt-3 flex items-center gap-1.5 text-[12px] text-risk-medium"><CircleAlert className="h-3.5 w-3.5" />{r.llm_note}</p>}
            <div className="mt-5 rounded-lg border border-signal/25 bg-signal/5 p-4">
              <div className="eyebrow mb-1 text-signal">Recommended next action</div>
              <p className="text-[13px] text-mist-100">{r.recommended_action}</p>
            </div>
          </Panel>

          <Panel title="Suspicious indicators" subtitle="Each indicator cites the evidence it was derived from">
            {r.suspicious_indicators.length === 0 ? <p className="text-[13px] text-mist-500">No rule-based indicators were triggered.</p> : (
              <ul className="space-y-2">
                {r.suspicious_indicators.map((i) => (
                  <li key={i.code} className="flex items-start gap-3 rounded-lg border border-line bg-ink-850 px-3 py-2.5">
                    <span className="num mt-0.5 rounded bg-ink-700 px-1.5 text-[11px] text-mist-300">w{i.weight}</span>
                    <span className="flex-1 text-[13px]">{i.description}</span>
                    <span className="flex gap-1">{i.evidence.map((e) => <a key={e} href={`#${e}`}><Pill tone="blue">{e}</Pill></a>)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Panel title="Evidence" subtitle="Retrieved by tenant-scoped database tools; identifiers reference stored records" bodyClass="space-y-3 p-5">
            {r.evidence.map((e) => (
              <div key={e.id} id={e.id} className="rounded-lg border border-line bg-ink-850 p-4">
                <div className="flex items-center gap-2">
                  <Pill tone="blue">{e.id}</Pill>
                  <span className="text-[13px] font-medium">{e.title}</span>
                  <span className="num ml-auto text-[11px] text-mist-500">{e.tool}()</span>
                </div>
                <p className="mt-2 text-[13px] text-mist-300">{e.summary}</p>
                {e.record_ids.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {e.record_ids.slice(0, 8).map((id) => <span key={id} className="num rounded bg-ink-700 px-1.5 py-0.5 text-[10px] text-mist-400">{id.length > 20 ? `${id.slice(0, 8)}…` : id}</span>)}
                    {e.record_ids.length > 8 && <span className="text-[11px] text-mist-500">+{e.record_ids.length - 8} more</span>}
                  </div>
                )}
              </div>
            ))}
          </Panel>
        </div>

        <div className="space-y-5">
          <Panel title="Case review">
            {canAnalyze(user) ? (
              <div className="space-y-3">
                <div>
                  <label className="eyebrow" htmlFor="review-status">Status</label>
                  <select id="review-status" className="input mt-1.5" value={status} onChange={(e) => setStatus(e.target.value)}>
                    {REVIEW.filter((s) => s !== "pending_review").map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
                  </select>
                </div>
                <div>
                  <label className="eyebrow" htmlFor="review-notes">Analyst notes</label>
                  <textarea id="review-notes" className="input mt-1.5 h-24 resize-none" value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={4000} />
                </div>
                <button className="btn-primary w-full justify-center" onClick={() => save.mutate()} disabled={save.isPending}>
                  {save.isPending && <Spinner />}Save review
                </button>
                {save.isSuccess && <p className="text-[12px] text-teal">Saved · alert status synchronised.</p>}
                {save.isError && <p className="text-[12px] text-risk-critical">{(save.error as Error).message}</p>}
              </div>
            ) : <p className="text-[13px] text-mist-500">Current status: {titleCase(inv.review_status)}</p>}
            <p className="mt-4 text-[11px] text-mist-500">Decisions are recorded for human review only; nothing is actioned automatically.</p>
          </Panel>

          <Panel title="Timeline" subtitle="Ordered by event time">
            <ol className="relative space-y-4 border-l border-line pl-4">
              {r.timeline.map((t, i) => (
                <li key={i} className="relative">
                  <span className="absolute -left-[21px] top-1 h-2.5 w-2.5 rounded-full border-2 border-ink-900 bg-signal" />
                  <div className="num text-[11px] text-mist-500">{fmtTime(t.at, true)}</div>
                  <div className="text-[13px]">{t.event}</div>
                  <div className="text-[11px] text-mist-500">{t.evidence} · <span className="num">{t.ref.length > 24 ? `${t.ref.slice(0, 8)}…` : t.ref}</span></div>
                </li>
              ))}
            </ol>
          </Panel>

          <Panel title="Model & data limitations">
            <ul className="space-y-2 text-[12px] text-mist-400">
              {r.limitations.map((l) => <li key={l} className="flex gap-2"><FileSearch className="mt-0.5 h-3.5 w-3.5 shrink-0 text-mist-500" />{l}</li>)}
            </ul>
          </Panel>
        </div>
      </div>
    </div>
  );
}
