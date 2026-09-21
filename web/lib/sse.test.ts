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

  it("keeps the tool call id", () => {
    expect(toChatEvent({ event: "tool_call", data: '{"tool":"read_file","args":{},"id":"r1"}' })).toEqual({
      type: "tool_call",
      tool: "read_file",
      args: {},
      id: "r1",
    });
  });

  it("maps tool_result with its snapshot id", () => {
    const data = JSON.stringify({
      tool: "write_file",
      id: "w1",
      content: "💾 저장",
      metadata: { snapshot: "20260912T101010-abcdef", path: "notes/a.md" },
    });
    expect(toChatEvent({ event: "tool_result", data })).toEqual({
      type: "tool_result",
      tool: "write_file",
      id: "w1",
      content: "💾 저장",
      snapshot: "20260912T101010-abcdef",
    });
  });

  it("flattens approval_required requests", () => {
    const data = JSON.stringify({
      requests: [
        {
          id: "w1",
          tool: "write_file",
          args: { path: "notes/a.md" },
          metadata: { reason: "vault 파일을 바꾼다", preview: "+new", rememberable: true },
        },
      ],
    });
    expect(toChatEvent({ event: "approval_required", data })).toEqual({
      type: "approval_required",
      requests: [
        {
          id: "w1",
          tool: "write_file",
          args: { path: "notes/a.md" },
          reason: "vault 파일을 바꾼다",
          preview: "+new",
          rememberable: true,
        },
      ],
    });
  });

  it("returns null for unknown event and bad JSON", () => {
    expect(toChatEvent({ event: "weird", data: "{}" })).toBeNull();
    expect(toChatEvent({ event: "text", data: "not json" })).toBeNull();
  });
});
