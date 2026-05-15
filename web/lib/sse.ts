// SSE wire 파싱 + 백엔드 이벤트 → 타입드 ChatEvent 매핑.
// 백엔드(api/streaming.format_sse) 프레임 형식: `event: <name>\ndata: <json>\n\n`.

export type SSEEvent = { event: string; data: string };

export class SSEParser {
  private buffer = "";

  // 네트워크 청크는 프레임 경계와 무관하게 도착 — 버퍼링 후 완성된 프레임만 방출.
  push(chunk: string): SSEEvent[] {
    this.buffer += chunk;
    const events: SSEEvent[] = [];
    let idx: number;
    while ((idx = this.buffer.indexOf("\n\n")) !== -1) {
      const raw = this.buffer.slice(0, idx);
      this.buffer = this.buffer.slice(idx + 2);
      const ev = parseFrame(raw);
      if (ev) events.push(ev);
    }
    return events;
  }
}

function parseFrame(raw: string): SSEEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  if (data.length === 0) return null;
  return { event, data: data.join("\n") };
}

export type ChatEvent =
  | { type: "start"; message: string }
  | { type: "tool_call"; tool: string; args: unknown }
  | { type: "text"; text: string }
  | { type: "done"; output: string | null };

export function toChatEvent(e: SSEEvent): ChatEvent | null {
  let d: Record<string, unknown>;
  try {
    d = JSON.parse(e.data);
  } catch {
    return null;
  }
  switch (e.event) {
    case "start":
      return { type: "start", message: String(d.message ?? "") };
    case "tool_call":
      return { type: "tool_call", tool: String(d.tool ?? ""), args: d.args };
    case "text":
      return { type: "text", text: String(d.text ?? "") };
    case "done":
      return { type: "done", output: (d.output as string | null) ?? null };
    default:
      return null;
  }
}
