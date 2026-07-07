"use client";

import { useCallback, useRef, useState } from "react";

import { streamChat, type ChatOptions } from "./api";

export type AssistantTool = { tool: string; args: unknown };
export type Message =
  | { role: "user"; text: string }
  | { role: "assistant"; text: string; tools: AssistantTool[]; error?: string };

type Assistant = Extract<Message, { role: "assistant" }>;

export function useChat(opts: Omit<ChatOptions, "sessionId">) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [streaming, setStreaming] = useState(false);
  const sessionId = useRef<string>("");
  if (!sessionId.current) sessionId.current = crypto.randomUUID();

  const send = useCallback(
    async (raw: string) => {
      const text = raw.trim();
      if (!text || streaming) return;

      setMessages((m) => [
        ...m,
        { role: "user", text },
        { role: "assistant", text: "", tools: [] },
      ]);
      setStreaming(true);

      const patch = (fn: (a: Assistant) => Assistant) =>
        setMessages((m) => {
          const copy = m.slice();
          const last = copy[copy.length - 1];
          if (last && last.role === "assistant") copy[copy.length - 1] = fn(last);
          return copy;
        });

      try {
        for await (const ev of streamChat(text, { ...opts, sessionId: sessionId.current })) {
          if (ev.type === "tool_call") {
            patch((a) => ({ ...a, tools: [...a.tools, { tool: ev.tool, args: ev.args }] }));
          } else if (ev.type === "text") {
            patch((a) => ({ ...a, text: a.text + ev.text }));
          } else if (ev.type === "done") {
            patch((a) => ({ ...a, text: a.text || ev.output || "" }));
          }
        }
      } catch (e) {
        patch((a) => ({ ...a, error: e instanceof Error ? e.message : String(e) }));
      } finally {
        setStreaming(false);
      }
    },
    [opts, streaming]
  );

  return { messages, streaming, send };
}
