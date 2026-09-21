// SSE wire 파싱 + 백엔드 이벤트 → 타입드 ChatEvent 매핑.
// 백엔드(agent/streaming.format_sse) 프레임 형식: `event: <name>\ndata: <json>\n\n`.

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

// 승인 대기 요청 — 백엔드 metadata(reason·preview·rememberable)를 펼친 형태.
export type ApprovalRequest = {
  id: string;
  tool: string;
  args: unknown;
  reason: string;
  preview: string;
  rememberable: boolean;
};

export type ChatEvent =
  | { type: "start"; message: string }
  | { type: "tool_call"; tool: string; args: unknown; id?: string }
  | { type: "tool_result"; tool: string; id: string; content: string; snapshot?: string }
  | { type: "text"; text: string }
  | { type: "approval_required"; requests: ApprovalRequest[] }
  | { type: "done"; output: string | null };

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

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
      return {
        type: "tool_call",
        tool: String(d.tool ?? ""),
        args: d.args,
        id: d.id === undefined ? undefined : String(d.id),
      };
    case "tool_result": {
      const meta = record(d.metadata);
      return {
        type: "tool_result",
        tool: String(d.tool ?? ""),
        id: String(d.id ?? ""),
        content: String(d.content ?? ""),
        snapshot: typeof meta.snapshot === "string" ? meta.snapshot : undefined,
      };
    }
    case "text":
      return { type: "text", text: String(d.text ?? "") };
    case "approval_required": {
      const requests = Array.isArray(d.requests) ? d.requests : [];
      return {
        type: "approval_required",
        requests: requests.map((raw) => {
          const r = record(raw);
          const meta = record(r.metadata);
          return {
            id: String(r.id ?? ""),
            tool: String(r.tool ?? ""),
            args: r.args,
            reason: String(meta.reason ?? ""),
            preview: String(meta.preview ?? ""),
            rememberable: meta.rememberable === true,
          };
        }),
      };
    }
    case "done":
      return { type: "done", output: (d.output as string | null) ?? null };
    default:
      return null;
  }
}
