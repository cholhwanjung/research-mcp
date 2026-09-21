// /chat SSE 클라이언트 + 스냅샷 되돌리기 + 모델·권한 모드 카탈로그.

import { SSEParser, toChatEvent, type ChatEvent } from "./sse";

export type ModelOption = { label: string; value: string };

// provider-prefixed 모델 (백엔드 agent.runtime이 그대로 해석).
export const MODELS: ModelOption[] = [
  { label: "Claude Sonnet 4.5", value: "anthropic:claude-sonnet-4-5" },
  { label: "GPT-4o", value: "openai:gpt-4o" },
  { label: "Gemini 2.5 Pro", value: "google:gemini-2.5-pro" },
];

// 권한 모드 (백엔드 agent.permissions). 서버에 토큰이 설정돼 있지 않으면 서버가 읽기 전용으로 고정한다.
export type Mode = "ask" | "accept_edits" | "read_only";

export const MODES: { label: string; value: Mode }[] = [
  { label: "확인 후 편집", value: "ask" },
  { label: "편집 자동 허용", value: "accept_edits" },
  { label: "읽기 전용", value: "read_only" },
];

export type ApprovalDecision = { approved: boolean; remember?: boolean; message?: string };

export interface ChatOptions {
  apiUrl: string;
  token?: string;
  model?: string;
  sessionId?: string;
  mode?: Mode;
  approvals?: Record<string, ApprovalDecision>;
  signal?: AbortSignal;
}

function authHeaders(token?: string): Record<string, string> {
  return token ? { authorization: `Bearer ${token}` } : {};
}

export async function* streamChat(
  message: string,
  opts: ChatOptions
): AsyncGenerator<ChatEvent> {
  const headers: Record<string, string> = { "content-type": "application/json", ...authHeaders(opts.token) };

  const res = await fetch(`${opts.apiUrl}/chat`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      message,
      model: opts.model,
      session_id: opts.sessionId,
      mode: opts.mode,
      approvals: opts.approvals,
    }),
    signal: opts.signal,
  });

  if (!res.ok || !res.body) {
    throw new Error(`chat request failed: ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SSEParser();

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    for (const ev of parser.push(decoder.decode(value, { stream: true }))) {
      const ce = toChatEvent(ev);
      if (ce) yield ce;
    }
  }
}

// 에이전트가 쓴 파일을 쓰기 전 내용으로 되돌린다.
export async function restoreSnapshot(
  id: string,
  opts: { apiUrl: string; token?: string }
): Promise<{ path: string }> {
  const res = await fetch(`${opts.apiUrl}/snapshots/${encodeURIComponent(id)}/restore`, {
    method: "POST",
    headers: authHeaders(opts.token),
  });
  if (!res.ok) throw new Error(`restore failed: ${res.status}`);
  return (await res.json()) as { path: string };
}
