import { describe, expect, it } from "vitest";

import { SSEParser, toChatEvent } from "./sse";

describe("SSEParser", () => {
  it("parses a single complete frame", () => {
    const p = new SSEParser();
    expect(p.push('event: start\ndata: {"message":"hi"}\n\n')).toEqual([
      { event: "start", data: '{"message":"hi"}' },
    ]);
  });

  it("parses two frames in one chunk", () => {
    const p = new SSEParser();
    const evs = p.push("event: a\ndata: 1\n\nevent: b\ndata: 2\n\n");
    expect(evs.map((e) => e.event)).toEqual(["a", "b"]);
    expect(evs.map((e) => e.data)).toEqual(["1", "2"]);
  });

  it("buffers a frame split across chunks until complete", () => {
    const p = new SSEParser();
    expect(p.push("event: done\nda")).toEqual([]);
    expect(p.push('ta: {"output":"x"}\n\n')).toEqual([
      { event: "done", data: '{"output":"x"}' },
    ]);
  });

  it("defaults event name to 'message' when only data present", () => {
    const p = new SSEParser();
    expect(p.push("data: hello\n\n")).toEqual([{ event: "message", data: "hello" }]);
  });

  it("skips frames with no data line", () => {
    const p = new SSEParser();
    expect(p.push(": comment only\n\n")).toEqual([]);
  });
});

describe("toChatEvent", () => {
  it("maps start", () => {
    expect(toChatEvent({ event: "start", data: '{"message":"hi"}' })).toEqual({
      type: "start",
      message: "hi",
    });
  });

  it("maps tool_call", () => {
    expect(
      toChatEvent({ event: "tool_call", data: '{"tool":"search_papers","args":{"q":"x"}}' })
    ).toEqual({ type: "tool_call", tool: "search_papers", args: { q: "x" } });
  });

  it("maps text", () => {
    expect(toChatEvent({ event: "text", data: '{"text":"hello"}' })).toEqual({
      type: "text",
      text: "hello",
    });
  });

  it("maps done", () => {
    expect(toChatEvent({ event: "done", data: '{"output":"final"}' })).toEqual({
      type: "done",
      output: "final",
    });
  });

  it("returns null for unknown event and bad JSON", () => {
    expect(toChatEvent({ event: "weird", data: "{}" })).toBeNull();
    expect(toChatEvent({ event: "text", data: "not json" })).toBeNull();
  });
});
