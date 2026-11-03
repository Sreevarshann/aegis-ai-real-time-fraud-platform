import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bug, Play, Zap } from "lucide-react";
import { useState } from "react";
import { post } from "../lib/api";
import { isAdmin, useAuth } from "../lib/auth";
import { Panel, Spinner } from "./ui";

interface Result { mode: string; sent: number; expected_outcomes: Record<string, number> }

export default function SimulatorControls() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [last, setLast] = useState<Result | null>(null);
  const run = useMutation({
    mutationFn: (body: { mode: string; count?: number }) => post<Result>("/simulator/runs", body),
    onSuccess: (r) => { setLast(r); setTimeout(() => qc.invalidateQueries(), 2500); },
  });
  const admin = isAdmin(user);
  const btn = (mode: string, label: string, Icon: typeof Play, count?: number) => (
    <button className="btn-ghost" disabled={!admin || run.isPending} onClick={() => run.mutate({ mode, count })}
      title={admin ? undefined : "Requires the admin role"}>
      {run.isPending && run.variables?.mode === mode ? <Spinner /> : <Icon className="h-3.5 w-3.5" />}{label}
    </button>
  );
  return (
    <Panel title="Synthetic traffic" subtitle="Publishes to Kafka; events flow through the real consumer pipeline">
      <div className="flex flex-wrap gap-2">
        {btn("burst", "Generate 500 transactions", Play, 500)}
        {btn("scenarios", "Inject fraud scenarios", Zap)}
        {btn("incident", "Send malformed batch", Bug)}
      </div>
      {!admin && <p className="mt-3 text-[12px] text-mist-500">Read-only for your role. Sign in as an admin to publish events.</p>}
      {run.isError && <p className="mt-3 text-[12px] text-risk-critical">{(run.error as Error).message}</p>}
      {last && (
        <p className="mt-3 text-[12px] text-mist-300" data-testid="sim-result">
          Published <span className="num text-mist-100">{last.sent}</span> messages ({Object.entries(last.expected_outcomes).map(([k, v]) => `${v} ${k.replace("_", " ")}`).join(", ")}).
        </p>
      )}
    </Panel>
  );
}
