// 어시스턴트 말풍선 상태 — 스트림 이벤트·승인 결정·되돌리기를 순수 함수로 반영한다.

import type { ApprovalDecision } from "./api";
import type { ApprovalRequest, ChatEvent } from "./sse";

export type ToolEntry = {
  id?: string;
  tool: string;
  args: unknown;
  result?: string;
  snapshot?: string;
  restored?: boolean;
};

export type Decision = { id: string; tool: string; approved: boolean };

export type Assistant = {
  role: "assistant";
  text: string;
  tools: ToolEntry[];
  pending: ApprovalRequest[];
  decisions: Decision[];
  error?: string;
};

const SEPARATOR = "\n\n";

export function emptyAssistant(): Assistant {
  return { role: "assistant", text: "", tools: [], pending: [], decisions: [] };
}

export function applyEvent(a: Assistant, ev: ChatEvent): Assistant {
  switch (ev.type) {
    case "tool_call":
      return { ...a, tools: [...a.tools, { id: ev.id, tool: ev.tool, args: ev.args }] };
    case "tool_result":
      return {
        ...a,
        tools: a.tools.map((t) => (t.id === ev.id ? { ...t, result: ev.content, snapshot: ev.snapshot } : t)),
      };
    case "text":
      return { ...a, text: a.text + ev.text };
    case "approval_required":
      return { ...a, pending: ev.requests };
    case "done": {
      // 이번 실행에서 흘러온 텍스트가 없을 때만 최종 output을 붙인다.
      const idle = !a.text.trim() || a.text.endsWith(SEPARATOR);
      return idle && ev.output ? { ...a, text: a.text + ev.output } : a;
    }
    default:
      return a;
  }
}

export function settleApprovals(a: Assistant, decisions: Record<string, ApprovalDecision>): Assistant {
  const settled = a.pending.filter((r) => r.id in decisions);
  return {
    ...a,
    pending: a.pending.filter((r) => !(r.id in decisions)),
    decisions: [
      ...a.decisions,
      ...settled.map((r) => ({ id: r.id, tool: r.tool, approved: decisions[r.id].approved })),
    ],
  };
}

// 승인 뒤 재개한 실행의 텍스트를 앞 텍스트와 떼어 둔다.
export function beginResume(a: Assistant): Assistant {
  return { ...a, text: a.text ? a.text + SEPARATOR : a.text };
}

export function markRestored(a: Assistant, snapshot: string): Assistant {
  return { ...a, tools: a.tools.map((t) => (t.snapshot === snapshot ? { ...t, restored: true } : t)) };
}
