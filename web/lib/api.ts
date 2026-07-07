// /chat SSE 클라이언트 + 모델 카탈로그.

import { SSEParser, toChatEvent, type ChatEvent } from "./sse";

export type ModelOption = { label: string; value: string };

// provider-prefixed 모델 (백엔드 agent.runtime이 그대로 해석).
export const MODELS: ModelOption[] = [
  { label: "Claude Sonnet 4.5", value: "anthropic:claude-sonnet-4-5" },
  { label: "GPT-4o", value: "openai:gpt-4o" },
  { label: "Gemini 2.5 Pro", value: "google:gemini-2.5-pro" },
];

export interface ChatOptions {
  apiUrl: string;
  token?: string;
  model?: string;
  sessionId?: string;
  signal?: AbortSignal;
}

export async function* streamChat(
  message: string,
  opts: ChatOptions
): AsyncGenerator<ChatEvent> {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (opts.token) headers.authorization = `Bearer ${opts.token}`;

  const res = await fetch(`${opts.apiUrl}/chat`, {
    method: "POST",
    headers,
    body: JSON.stringify({ message, model: opts.model, session_id: opts.sessionId }),
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
