import { useInfiniteQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { Pause, Play, Radio } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import TransactionDrawer from "../components/TransactionDrawer";
import { EmptyState, ErrorState, LoadingBlock, Panel, Pill, RiskBadge, ScoreBar, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { fmtMoney, fmtTime, titleCase } from "../lib/format";
import { useTransactionFeed, type FeedMode } from "../lib/stream";
import type { Transaction } from "../lib/types";

interface Filters { q: string; risk: string; channel: string; minScore: string }
const EMPTY: Filters = { q: "", risk: "", channel: "", minScore: "" };

function matches(t: Transaction, f: Filters) {
  if (f.risk && t.risk_category !== f.risk) return false;
  if (f.channel && t.payment_channel !== f.channel) return false;
  if (f.minScore && (t.risk_score ?? 0) < Number(f.minScore)) return false;
  if (f.q.length >= 2) {
    const q = f.q.toLowerCase();
    return [t.customer_id, t.merchant_id, t.merchant_name, t.device_id, t.transaction_id].some((v) => v.toLowerCase().includes(q));
  }
  return true;
}

const MODE_LABEL: Record<FeedMode, [string, "teal" | "warn" | "bad" | "neutral"]> = {
  connecting: ["Connecting", "neutral"], live: ["Live stream", "teal"], reconnecting: ["Reconnecting", "warn"],
  polling: ["Polling fallback", "warn"], offline: ["Offline", "bad"],
};

export default function TransactionsPage() {
  const [filters, setFilters] = useState<Filters>(EMPTY);
  const [paused, setPaused] = useState(false);
  const [live, setLive] = useState<Transaction[]>([]);
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<string | null>(null);

  const params = useMemo(() => {
    const p = new URLSearchParams({ limit: "50" });
    if (filters.q.length >= 2) p.set("q", filters.q);
    if (filters.risk) p.set("risk_category", filters.risk);
    if (filters.channel) p.set("channel", filters.channel);
    if (filters.minScore) p.set("min_score", filters.minScore);
    return p;
  }, [filters]);

  const q = useInfiniteQuery({
    queryKey: ["transactions", params.toString()],
    queryFn: ({ pageParam }) => {
      const p = new URLSearchParams(params);
      if (pageParam) p.set("before_seq", String(pageParam));
      return api<{ items: Transaction[]; next_before_seq: number | null }>(`/transactions?${p}`);
    },
    initialPageParam: 0,
    getNextPageParam: (last) => last.next_before_seq ?? undefined,
  });

  const onRows = useCallback((rows: Transaction[]) => {
    if (paused) return;
    const keep = rows.filter((r) => matches(r, filters)).reverse();
    if (!keep.length) return;
    setLive((prev) => [...keep, ...prev].slice(0, 300));
    setFresh(new Set(keep.map((r) => r.transaction_id)));
  }, [filters, paused]);
  const mode = useTransactionFeed(onRows);

  const rows = useMemo(() => {
    const seen = new Set<string>();
    const base = q.data?.pages.flatMap((p) => p.items) ?? [];
    return [...live, ...base].filter((r) => (seen.has(r.transaction_id) ? false : (seen.add(r.transaction_id), true)));
  }, [live, q.data]);

  const set = (k: keyof Filters) => (e: { target: { value: string } }) => {
    setLive([]);
    setFilters((f) => ({ ...f, [k]: e.target.value }));
  };
  const [label, tone] = MODE_LABEL[mode];

  return (
    <div className="space-y-5">
      <Panel bodyClass="p-4">
        <div className="flex flex-wrap items-center gap-3">
          <input className="input max-w-xs" placeholder="Search customer, merchant, device, id…" value={filters.q} onChange={set("q")} aria-label="Search" />
          <select className="input w-auto" value={filters.risk} onChange={set("risk")} aria-label="Risk category">
            <option value="">All risk levels</option>
            {["low", "medium", "high", "critical"].map((r) => <option key={r} value={r}>{titleCase(r)}</option>)}
          </select>
          <select className="input w-auto" value={filters.channel} onChange={set("channel")} aria-label="Channel">
            <option value="">All channels</option>
            {["card_present", "ecommerce", "mobile_wallet", "bank_transfer"].map((c) => <option key={c} value={c}>{titleCase(c)}</option>)}
          </select>
          <select className="input w-auto" value={filters.minScore} onChange={set("minScore")} aria-label="Minimum score">
            <option value="">Any score</option>
            {[30, 50, 60, 85].map((s) => <option key={s} value={s}>Score ≥ {s}</option>)}
          </select>
          {Object.values(filters).some(Boolean) && <button className="text-[12px] text-signal hover:underline" onClick={() => { setLive([]); setFilters(EMPTY); }}>Clear</button>}
          <div className="ml-auto flex items-center gap-2">
            <span data-testid="feed-mode"><Pill tone={tone}><Radio className="h-3 w-3" />{label}</Pill></span>
            <button className="btn-ghost" onClick={() => setPaused((p) => !p)}>
              {paused ? <Play className="h-3.5 w-3.5" /> : <Pause className="h-3.5 w-3.5" />}{paused ? "Resume" : "Pause"}
            </button>
          </div>
        </div>
      </Panel>

      <Panel bodyClass="p-0" title="Transaction feed" subtitle="Newest first · click a row for model explanation and investigation">
        {q.isLoading ? <div className="p-5"><LoadingBlock rows={10} /></div> : q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> :
          rows.length === 0 ? <EmptyState title="No transactions match">Adjust the filters or generate traffic from the Overview page.</EmptyState> : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[960px]" data-testid="txn-table">
                <thead className="table-head"><tr>
                  <th>Event time</th><th>Customer</th><th>Merchant</th><th>Channel</th><th>Country</th>
                  <th className="text-right">Amount</th><th>Status</th><th>Score</th><th>Risk</th>
                </tr></thead>
                <tbody>
                  {rows.map((t) => (
                    <tr key={t.transaction_id} onClick={() => setSelected(t.transaction_id)}
                      className={clsx("table-row cursor-pointer", fresh.has(t.transaction_id) && "animate-flash")}>
                      <td className="num text-mist-300">{fmtTime(t.event_timestamp)}{t.is_late && <span className="ml-1.5"><Pill tone="warn">late</Pill></span>}</td>
                      <td className="num">{t.customer_id}</td>
                      <td className="max-w-[200px] truncate">{t.merchant_name}<div className="text-[11px] text-mist-500">{titleCase(t.merchant_category)}</div></td>
                      <td className="text-mist-300">{titleCase(t.payment_channel)}</td>
                      <td className="num">{t.country}</td>
                      <td className="num text-right">{fmtMoney(t.amount, t.currency)}</td>
                      <td>{t.status === "approved" ? <span className="text-mist-400">approved</span> : <Pill tone={t.status === "declined" ? "bad" : "neutral"}>{t.status}</Pill>}</td>
                      <td><ScoreBar score={t.risk_score} /></td>
                      <td><RiskBadge category={t.risk_category} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="flex justify-center border-t border-line p-3">
                {q.hasNextPage ? (
                  <button className="btn-ghost" onClick={() => q.fetchNextPage()} disabled={q.isFetchingNextPage}>
                    {q.isFetchingNextPage && <Spinner />}Load older
                  </button>
                ) : <span className="text-[12px] text-mist-500">End of history</span>}
              </div>
            </div>
          )}
      </Panel>
      {selected && <TransactionDrawer id={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
