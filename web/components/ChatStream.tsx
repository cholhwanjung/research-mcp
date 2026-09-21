import type { ApprovalDecision } from "@/lib/api";
import type { Message } from "@/lib/useChat";

import { ApprovalPanel } from "./ApprovalPanel";
import { ToolCard } from "./ToolCard";

export function ChatStream({
  messages,
  streaming,
  onRespond,
  onUndo,
}: {
  messages: Message[];
  streaming: boolean;
  onRespond: (decisions: Record<string, ApprovalDecision>) => void;
  onUndo: (snapshot: string) => void;
}) {
  return (
    <div className="flex flex-col gap-4">
      {messages.map((m, i) =>
        m.role === "user" ? (
          <div
            key={i}
            className="max-w-[80%] self-end whitespace-pre-wrap rounded-2xl bg-zinc-900 px-4 py-2 text-white dark:bg-zinc-100 dark:text-black"
          >
            {m.text}
          </div>
        ) : (
          <div key={i} className="max-w-[85%] self-start">
            {m.tools.map((t, j) => (
              <ToolCard key={t.id ?? j} entry={t} onUndo={onUndo} />
            ))}
            {m.text ? (
              <div className="whitespace-pre-wrap rounded-2xl bg-zinc-100 px-4 py-2 dark:bg-zinc-800">{m.text}</div>
            ) : null}
            {m.pending.length > 0 ? (
              <ApprovalPanel requests={m.pending} disabled={streaming} onRespond={onRespond} />
            ) : null}
            {m.error ? <div className="text-sm text-red-500">⚠ {m.error}</div> : null}
            {!m.text && !m.error && m.pending.length === 0 && streaming && i === messages.length - 1 ? (
              <div className="px-2 text-sm text-zinc-400">…</div>
            ) : null}
          </div>
        )
      )}
    </div>
  );
}
