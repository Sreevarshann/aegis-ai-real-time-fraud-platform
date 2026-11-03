import { useEffect, useRef, useState } from "react";
import { api, tokenStore } from "./api";
import type { Transaction } from "./types";

export type FeedMode = "connecting" | "live" | "reconnecting" | "polling" | "offline";

/** Parse a text/event-stream chunk buffer into complete events. Exported for unit tests. */
export function parseSse(buffer: string): { events: { event: string; data: string }[]; rest: string } {
  const events: { event: string; data: string }[] = [];
  const blocks = buffer.split("\n\n");
  const rest = blocks.pop() ?? "";
  for (const block of blocks) {
    let event = "message";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith(":")) continue;
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
    }
    if (data.length) events.push({ event, data: data.join("\n") });
  }
  return { events, rest };
}

/**
 * Live transaction feed. Uses Server-Sent Events over fetch (so the bearer token travels in a
 * header, not the URL), reconnects with exponential backoff, and falls back to cursor-based
 * polling after repeated stream failures.
 */
export function useTransactionFeed(onRows: (rows: Transaction[]) => void, enabled = true) {
  const [mode, setMode] = useState<FeedMode>("connecting");
  const cursor = useRef<number | undefined>(undefined);
  const handler = useRef(onRows);
  handler.current = onRows;

  useEffect(() => {
    if (!enabled) return;
    let stopped = false;
    let failures = 0;
    let healthyPolls = 0;
    let controller: AbortController | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const deliver = (rows: Transaction[]) => {
      if (!rows.length) return;
      cursor.current = Math.max(cursor.current ?? 0, ...rows.map((r) => r.seq));
      handler.current(rows);
    };

    const poll = async () => {
      if (stopped) return;
      try {
        const q = cursor.current != null ? `after_seq=${cursor.current}&limit=100` : "limit=1";
        const res = await api<{ items: Transaction[] }>(`/transactions?${q}`);
        if (cursor.current == null) cursor.current = res.items[0]?.seq ?? 0;
        else deliver(res.items);
        setMode("polling");
        // After a healthy stretch of polling, try to upgrade back to the stream.
        if (++healthyPolls >= 6) { healthyPolls = 0; failures = 0; connect(); return; }
      } catch {
        healthyPolls = 0;
        setMode("offline");
      }
      timer = setTimeout(poll, 2500);
    };

    const connect = async () => {
      if (stopped) return;
      controller = new AbortController();
      try {
        const qs = cursor.current != null ? `?after_seq=${cursor.current}` : "";
        const res = await fetch(`/api/v1/transactions/stream${qs}`, {
          headers: { Authorization: `Bearer ${tokenStore.get() ?? ""}`, Accept: "text/event-stream" },
          signal: controller.signal,
        });
        if (!res.ok || !res.body) throw new Error(`stream HTTP ${res.status}`);
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) throw new Error("stream closed");
          buffer += decoder.decode(value, { stream: true });
          const parsed = parseSse(buffer);
          buffer = parsed.rest;
          for (const ev of parsed.events) {
            if (ev.event === "ready") {
              const c = JSON.parse(ev.data).cursor as number;
              cursor.current = Math.max(cursor.current ?? 0, c);
              failures = 0;
              setMode("live");
            } else if (ev.event === "transactions") {
              deliver(JSON.parse(ev.data) as Transaction[]);
            }
          }
        }
      } catch {
        if (stopped) return;
        failures += 1;
        if (failures >= 3) { poll(); return; }
        setMode("reconnecting");
        timer = setTimeout(connect, Math.min(1000 * 2 ** failures, 8000));
      }
    };

    connect();
    return () => {
      stopped = true;
      controller?.abort();
      if (timer) clearTimeout(timer);
    };
  }, [enabled]);

  return mode;
}
