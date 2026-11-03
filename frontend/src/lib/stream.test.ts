import { describe, expect, it } from "vitest";
import { parseSse } from "./stream";

describe("parseSse", () => {
  it("parses complete events and keeps the partial remainder", () => {
    const { events, rest } = parseSse('event: ready\ndata: {"cursor": 5}\n\n: keep-alive\n\nevent: transactions\ndata: [1');
    expect(events).toEqual([{ event: "ready", data: '{"cursor": 5}' }]);
    expect(rest).toBe("event: transactions\ndata: [1");
  });

  it("joins multi-line data and ignores comments", () => {
    const { events } = parseSse(": ping\n\ndata: a\ndata: b\n\n");
    expect(events).toEqual([{ event: "message", data: "a\nb" }]);
  });

  it("handles chunk boundaries across calls", () => {
    const first = parseSse("event: transactions\nda");
    const second = parseSse(first.rest + 'ta: [{"seq": 1}]\n\n');
    expect(second.events[0]).toEqual({ event: "transactions", data: '[{"seq": 1}]' });
  });
});
