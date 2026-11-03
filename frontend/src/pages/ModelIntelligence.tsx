import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { BarsChart, Legend, SERIES } from "../components/charts";
import { EmptyState, ErrorState, KeyValue, LoadingBlock, Panel, Pill, Stat } from "../components/ui";
import { api } from "../lib/api";
import { fmtInt, fmtNum, fmtPct, fmtTime, titleCase } from "../lib/format";

interface Metrics { precision: number; recall: number; f1: number; pr_auc: number; roc_auc: number; confusion_matrix: { tn: number; fp: number; fn: number; tp: number }; support_positive: number; support_total: number }
interface Candidate { validation: Metrics; test: Metrics; fit_seconds: number }
interface ModelSummary {
  version: string; algorithm: string; created_at: string; mlflow_run_id: string | null; decision_threshold: number; feature_names: string[];
  test_metrics: Metrics; feature_importance: { feature: string; importance: number; std: number }[];
  training_summary: { rows: Record<string, number>; positive_rate: Record<string, number>; time_ranges: Record<string, string[]>; candidates: Record<string, Candidate>;
    test_recall_by_scenario: { scenario: string; n: number; alerts: number; alert_rate: number }[]; seed: number; calibration: string; threshold_rule: string };
  live_simulation_performance: { tp: number; fp: number; fn: number; tn: number; precision: number | null; recall: number | null; note: string };
  prediction_distribution: { range: string; count: number }[];
}
interface Drift {
  status: string; sample_size?: number; min_sample?: number; score_psi?: number; score_status?: string; score_bins?: string[];
  reference_distribution?: number[]; live_distribution?: number[]; features?: { feature: string; psi: number; status: string }[];
}

const DRIFT_TONE = { stable: "good", moderate: "warn", significant: "bad" } as const;

function Confusion({ m }: { m: Metrics["confusion_matrix"] }) {
  const cells = [["True negative", m.tn, false], ["False positive", m.fp, true], ["False negative", m.fn, true], ["True positive", m.tp, false]] as const;
  return (
    <div>
      <div className="mb-2 grid grid-cols-[80px_1fr_1fr] gap-2 text-[11px] text-mist-500"><span /><span className="text-center">Predicted legit</span><span className="text-center">Predicted fraud</span></div>
      {[0, 1].map((row) => (
        <div key={row} className="mb-2 grid grid-cols-[80px_1fr_1fr] gap-2">
          <span className="self-center text-[11px] text-mist-500">{row === 0 ? "Actual legit" : "Actual fraud"}</span>
          {cells.slice(row * 2, row * 2 + 2).map(([label, v, bad]) => (
            <div key={label} className={`rounded-lg border p-3 text-center ${bad ? "border-risk-high/30 bg-risk-high/5" : "border-teal/25 bg-teal/5"}`}>
              <div className="num text-[20px]">{fmtInt(v)}</div><div className="text-[11px] text-mist-500">{label}</div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

export default function ModelIntelligence() {
  const m = useQuery({ queryKey: ["model"], queryFn: () => api<ModelSummary>("/models/active"), refetchInterval: 30_000 });
  const d = useQuery({ queryKey: ["drift"], queryFn: () => api<Drift>("/models/drift"), refetchInterval: 30_000 });
  if (m.isLoading) return <Panel><LoadingBlock rows={10} /></Panel>;
  if (m.isError || !m.data) return <Panel><ErrorState error={m.error} onRetry={() => m.refetch()} /></Panel>;
  const s = m.data;
  const t = s.test_metrics;
  const live = s.live_simulation_performance;
  const driftData = d.data?.score_bins?.map((b, i) => ({ bin: b, reference: d.data!.reference_distribution![i], live: d.data!.live_distribution![i] })) ?? [];

  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-3 xl:grid-cols-6">
        <Stat label="Model version" value={<span className="text-[17px]">{s.version}</span>} hint={titleCase(s.algorithm)} />
        <Stat label="Precision" value={fmtNum(t.precision)} hint="test split" />
        <Stat label="Recall" value={fmtNum(t.recall)} hint="test split" />
        <Stat label="F1" value={fmtNum(t.f1)} hint={`threshold ${fmtNum(s.decision_threshold, 2)}`} />
        <Stat label="PR-AUC" value={fmtNum(t.pr_auc)} hint={`base rate ${fmtPct(s.training_summary.positive_rate.test, 2)}`} />
        <Stat label="ROC-AUC" value={fmtNum(t.roc_auc)} hint={`${fmtInt(t.support_total)} test rows`} />
      </div>
      <p className="text-[12px] text-mist-500">Metrics are measured on a held-out chronological test split of <b>synthetic</b> data generated with seed {s.training_summary.seed}. They describe performance on the simulator's fraud patterns, not real-world fraud.</p>

      <div className="grid gap-5 xl:grid-cols-3">
        <Panel title="Confusion matrix" subtitle={`Test split at threshold ${fmtNum(s.decision_threshold, 3)}`}><Confusion m={t.confusion_matrix} /></Panel>
        <Panel title="Model card">
          <KeyValue items={[
            ["Trained", fmtTime(s.created_at, true)],
            ["Algorithm", titleCase(s.algorithm)],
            ["Calibration", s.training_summary.calibration],
            ["Threshold rule", s.training_summary.threshold_rule],
            ["Rows (train/val/test)", <span className="num">{Object.values(s.training_summary.rows).map(fmtInt).join(" / ")}</span>],
            ["Train window", <span className="num text-[12px]">{s.training_summary.time_ranges.train?.map((x) => x.slice(0, 16)).join(" → ")}</span>],
            ["Test window", <span className="num text-[12px]">{s.training_summary.time_ranges.test?.map((x) => x.slice(0, 16)).join(" → ")}</span>],
            ["Features", s.feature_names.length],
            ["MLflow run", <span className="num text-[12px]">{s.mlflow_run_id ?? "not logged"}</span>],
          ]} />
        </Panel>
        <Panel title="Candidate comparison" subtitle="Selected by validation PR-AUC" bodyClass="p-0">
          <table className="w-full">
            <thead className="table-head"><tr><th>Model</th><th className="text-right">Val PR-AUC</th><th className="text-right">Test PR-AUC</th><th className="text-right">Test F1</th></tr></thead>
            <tbody>
              {Object.entries(s.training_summary.candidates).map(([name, c]) => (
                <tr key={name} className="table-row">
                  <td>{titleCase(name)} {name === s.algorithm && <Pill tone="teal">selected</Pill>}</td>
                  <td className="num text-right">{fmtNum(c.validation.pr_auc)}</td><td className="num text-right">{fmtNum(c.test.pr_auc)}</td><td className="num text-right">{fmtNum(c.test.f1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="border-t border-line p-4">
            <div className="eyebrow mb-2">Test alert rate by simulated scenario</div>
            <table className="w-full text-[12px]">
              <tbody>
                {s.training_summary.test_recall_by_scenario.map((r) => (
                  <tr key={r.scenario}><td className="py-0.5 text-mist-300">{titleCase(r.scenario)}</td><td className="num py-0.5 text-right text-mist-500">{fmtInt(r.alerts)}/{fmtInt(r.n)}</td><td className="num py-0.5 pl-3 text-right">{fmtPct(r.alert_rate)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <Panel title="Feature importance" subtitle="Permutation importance (drop in PR-AUC) on the test split">
          <BarsChart data={s.feature_importance.slice(0, 12).map((f) => ({ ...f, importance: Number(f.importance.toFixed(4)) }))} x="feature" y="importance" name="Δ PR-AUC" layout="vertical" height={360} color={SERIES[1]} />
        </Panel>
        <Panel title="Prediction distribution" subtitle="Live risk scores for your tenant, last 7 days">
          <BarsChart data={s.prediction_distribution} x="range" y="count" name="Transactions" height={360} />
        </Panel>
      </div>

      <div className="grid gap-5 xl:grid-cols-3">
        <Panel className="xl:col-span-2" title="Prediction drift" subtitle="Population Stability Index of live scores vs. the test-split reference (most recent 2,000 predictions)"
          actions={d.data?.score_status && <span data-testid="drift-status"><Pill tone={DRIFT_TONE[d.data.score_status as keyof typeof DRIFT_TONE]}>Score PSI {d.data.score_psi} · {d.data.score_status}</Pill></span>}>
          {d.isLoading ? <LoadingBlock /> : d.isError ? <ErrorState error={d.error} /> : d.data?.status === "insufficient_data" ? (
            <EmptyState title="Not enough live predictions yet">{d.data.sample_size} of {d.data.min_sample} predictions needed for a stable PSI.</EmptyState>
          ) : (
            <>
              <Legend items={[{ label: "Reference (test split)", color: SERIES[0] }, { label: "Live", color: SERIES[1] }]} />
              <ResponsiveContainer width="100%" height={230}>
                <BarChart data={driftData} margin={{ top: 12, right: 8, left: -12, bottom: 0 }} barGap={2}>
                  <CartesianGrid stroke="#1e2a44" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="bin" stroke="#62708f" fontSize={11} tickLine={false} axisLine={false} />
                  <YAxis stroke="#62708f" fontSize={11} tickLine={false} axisLine={false} tickFormatter={(v) => `${Math.round(v * 100)}%`} />
                  <Tooltip cursor={{ fill: "rgba(76,141,255,0.06)" }} contentStyle={{ background: "#0d1426", border: "1px solid #1e2a44", borderRadius: 8, fontSize: 12 }}
                    formatter={(v: number) => fmtPct(v, 2)} />
                  <Bar dataKey="reference" name="Reference" fill={SERIES[0]} radius={[4, 4, 0, 0]} isAnimationActive={false} />
                  <Bar dataKey="live" name="Live" fill={SERIES[1]} radius={[4, 4, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </>
          )}
        </Panel>
        <Panel title="Feature drift & live performance" bodyClass="p-0">
          {d.data?.features ? (
            <table className="w-full">
              <thead className="table-head"><tr><th>Feature</th><th className="text-right">PSI</th><th>Status</th></tr></thead>
              <tbody>{d.data.features.map((f) => (
                <tr key={f.feature} className="table-row"><td className="num text-[12px]">{f.feature}</td><td className="num text-right">{f.psi}</td>
                  <td><Pill tone={DRIFT_TONE[f.status as keyof typeof DRIFT_TONE]}>{f.status}</Pill></td></tr>
              ))}</tbody>
            </table>
          ) : <div className="p-5 text-[12px] text-mist-500">Feature drift appears once enough predictions exist.</div>}
          <div className="border-t border-line p-4">
            <div className="eyebrow mb-2">Live alerting vs. simulator labels (7d)</div>
            <KeyValue items={[
              ["Precision", fmtNum(live.precision)], ["Recall", fmtNum(live.recall)],
              ["TP / FP / FN", <span className="num">{live.tp} / {live.fp} / {live.fn}</span>],
            ]} />
            <p className="mt-2 text-[11px] text-mist-500">{live.note}</p>
          </div>
        </Panel>
      </div>
    </div>
  );
}
