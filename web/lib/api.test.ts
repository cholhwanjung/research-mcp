import { afterEach, describe, expect, it, vi } from "vitest";

import { streamChat } from "./api";
import type { ChatEvent } from "./sse";

function streamFrom(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(c) {
      for (const ch of chunks) c.enqueue(enc.encode(ch));
      c.close();
    },
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("streamChat", () => {
  it("yields typed chat events from the SSE stream", async () => {
    const body = streamFrom([
      'event: start\ndata: {"message":"hi"}\n\n',
      'event: tool_call\ndata: {"tool":"search_papers","args":{}}\n\nevent: text\ndata: {"text":"a"}\n\n',
      'event: done\ndata: {"output":"ok"}\n\n',
    ]);
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, body });
    vi.stubGlobal("fetch", fetchMock);

    const events: ChatEvent[] = [];
    for await (const e of streamChat("hi", { apiUrl: "http://x", token: "t", sessionId: "s1" })) {
      events.push(e);
    }

    expect(events.map((e) => e.type)).toEqual(["start", "tool_call", "text", "done"]);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://x/chat");
    expect(init.method).toBe("POST");
    expect(init.headers.authorization).toBe("Bearer t");
    expect(JSON.parse(init.body)).toEqual({ message: "hi", model: undefined, session_id: "s1" });
  });

  it("omits Authorization header when no token", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, status: 200, body: streamFrom([]) });
    vi.stubGlobal("fetch", fetchMock);

    for await (const _ of streamChat("hi", { apiUrl: "http://x" })) {
      /* drain */
    }
    expect(fetchMock.mock.calls[0][1].headers.authorization).toBeUndefined();
  });

  it("throws on non-ok response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 401, body: null }));
    await expect(async () => {
      for await (const _ of streamChat("hi", { apiUrl: "http://x" })) {
        /* drain */
      }
    }).rejects.toThrow(/401/);
  });
});
