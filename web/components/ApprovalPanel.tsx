"use client";

import { useState } from "react";

import type { ApprovalDecision } from "@/lib/api";
import type { ApprovalRequest } from "@/lib/sse";

function PreviewLine({ line }: { line: string }) {
  const added = line.startsWith("+") && !line.startsWith("+++");
  const removed = line.startsWith("-") && !line.startsWith("---");
  const tone = added ? "text-emerald-700 dark:text-emerald-400" : removed ? "text-red-600 dark:text-red-400" : "";
  return <div className={tone}>{line || " "}</div>;
}

// 승인 대기 요청 전부에 결정이 모이면 한 번에 보낸다.
export function ApprovalPanel({
  requests,
  disabled,
  onRespond,
}: {
  requests: ApprovalRequest[];
  disabled: boolean;
  onRespond: (decisions: Record<string, ApprovalDecision>) => void;
}) {
  const [draft, setDraft] = useState<Record<string, ApprovalDecision>>({});

  const decide = (id: string, decision: ApprovalDecision) => {
    const next = { ...draft, [id]: decision };
    if (requests.every((r) => r.id in next)) {
      setDraft({});
      onRespond(next);
    } else {
      setDraft(next);
    }
  };

  const button =
    "rounded-md border px-3 py-1 text-xs disabled:opacity-40 border-zinc-300 bg-white hover:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-900 dark:hover:bg-zinc-800";

  return (
    <div className="my-2 flex flex-col gap-2">
      {requests.map((r) => (
        <div
          key={r.id}
          className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-700 dark:bg-amber-950"
        >
          <div className="font-medium">
            ⏸ 승인 필요 · <span className="font-mono">{r.tool}</span>
          </div>
          {r.reason ? <div className="text-xs text-zinc-600 dark:text-zinc-400">{r.reason}</div> : null}
          {r.preview ? (
            <div className="mt-2 max-h-64 overflow-auto rounded bg-white p-2 font-mono text-xs whitespace-pre dark:bg-zinc-900">
              {r.preview.split("\n").map((line, i) => (
                <PreviewLine key={i} line={line} />
              ))}
            </div>
          ) : null}
          {r.id in draft ? (
            <div className="mt-2 text-xs text-zinc-500">
              {draft[r.id].approved ? "허용" : "거부"} — 나머지 요청을 결정하면 이어서 실행합니다
            </div>
          ) : (
            <div className="mt-2 flex flex-wrap gap-2">
              <button className={button} disabled={disabled} onClick={() => decide(r.id, { approved: true })}>
                허용
              </button>
              {r.rememberable ? (
                <button
                  className={button}
                  disabled={disabled}
                  onClick={() => decide(r.id, { approved: true, remember: true })}
                >
                  이 세션 동안 허용
                </button>
              ) : null}
              <button
                className={button}
                disabled={disabled}
                onClick={() => decide(r.id, { approved: false, message: "사용자가 거부했다" })}
              >
                거부
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
