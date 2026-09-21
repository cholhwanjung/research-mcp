"use client";

import { useCallback, useRef, useState } from "react";

import { restoreSnapshot, streamChat, type ApprovalDecision, type ChatOptions } from "./api";
import {
  applyEvent,
  beginResume,
  emptyAssistant,
  markRestored,
  settleApprovals,
  type Assistant,
} from "./chatState";

export type Message = { role: "user"; text: string } | Assistant;

export function useChat(opts: Omit<ChatOptions, "sessionId" | "approvals">) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [streaming, setStreaming] = useState(false);
  const sessionId = useRef<string>("");
  if (!sessionId.current) sessionId.current = crypto.randomUUID();

  const patchLast = useCallback(
    (fn: (a: Assistant) => Assistant) =>
      setMessages((m) => {
        const copy = m.slice();
        const last = copy[copy.length - 1];
        if (last && last.role === "assistant") copy[copy.length - 1] = fn(last);
        return copy;
      }),
    []
  );

  const run = useCallback(
    async (message: string, approvals?: Record<string, ApprovalDecision>) => {
      setStreaming(true);
      try {
        for await (const ev of streamChat(message, { ...opts, sessionId: sessionId.current, approvals })) {
          patchLast((a) => applyEvent(a, ev));
        }
      } catch (e) {
        patchLast((a) => ({ ...a, error: e instanceof Error ? e.message : String(e) }));
      } finally {
        setStreaming(false);
      }
    },
    [opts, patchLast]
  );

  const send = useCallback(
    async (raw: string) => {
      const text = raw.trim();
      if (!text || streaming) return;
      setMessages((m) => [...m, { role: "user", text }, emptyAssistant()]);
      await run(text);
    },
    [run, streaming]
  );

  // 승인 대기 요청 전부에 대한 결정을 보내 같은 실행을 이어간다.
  const respond = useCallback(
    async (decisions: Record<string, ApprovalDecision>) => {
      if (streaming) return;
      patchLast((a) => beginResume(settleApprovals(a, decisions)));
      await run("", decisions);
    },
    [patchLast, run, streaming]
  );

  const undo = useCallback(
    async (snapshot: string) => {
      try {
        await restoreSnapshot(snapshot, { apiUrl: opts.apiUrl, token: opts.token });
        setMessages((m) => m.map((msg) => (msg.role === "assistant" ? markRestored(msg, snapshot) : msg)));
      } catch (e) {
        patchLast((a) => ({ ...a, error: e instanceof Error ? e.message : String(e) }));
      }
    },
    [opts.apiUrl, opts.token, patchLast]
  );

  const last = messages[messages.length - 1];
  const awaitingApproval = !!last && last.role === "assistant" && last.pending.length > 0;

  return { messages, streaming, awaitingApproval, send, respond, undo };
}
