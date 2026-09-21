import { describe, expect, it } from "vitest";

import { applyEvent, beginResume, emptyAssistant, markRestored, settleApprovals } from "./chatState";

const request = {
  id: "w1",
  tool: "write_file",
  args: { path: "notes/a.md" },
  reason: "vault 파일을 바꾼다",
  preview: "+x",
  rememberable: true,
};

describe("applyEvent", () => {
  it("pairs tool results with their calls and keeps snapshot ids", () => {
    let a = emptyAssistant();
    a = applyEvent(a, { type: "tool_call", tool: "read_file", args: { path: "notes/a.md" }, id: "r1" });
    a = applyEvent(a, { type: "tool_result", tool: "read_file", id: "r1", content: "hello" });
    a = applyEvent(a, { type: "text", text: "쓰겠" });
    a = applyEvent(a, { type: "text", text: "습니다" });
    a = applyEvent(a, { type: "tool_call", tool: "write_file", args: {}, id: "w1" });
    a = applyEvent(a, { type: "tool_result", tool: "write_file", id: "w1", content: "💾 저장", snapshot: "s-1" });
    expect(a.text).toBe("쓰겠습니다");
    expect(a.tools).toEqual([
      { id: "r1", tool: "read_file", args: { path: "notes/a.md" }, result: "hello" },
      { id: "w1", tool: "write_file", args: {}, result: "💾 저장", snapshot: "s-1" },
    ]);
  });

  it("holds pending approvals until they are settled", () => {
    let a = applyEvent(emptyAssistant(), { type: "approval_required", requests: [request] });
    expect(a.pending).toEqual([request]);
    a = settleApprovals(a, { w1: { approved: false, message: "안 돼" } });
    expect(a.pending).toEqual([]);
    expect(a.decisions).toEqual([{ id: "w1", tool: "write_file", approved: false }]);
  });

  it("uses the done output only when nothing was streamed since the last run started", () => {
    expect(applyEvent(emptyAssistant(), { type: "done", output: "final" }).text).toBe("final");
    const streamed = applyEvent(emptyAssistant(), { type: "text", text: "a" });
    expect(applyEvent(streamed, { type: "done", output: "final" }).text).toBe("a");
  });

  it("separates a resumed run from the text before the approval", () => {
    let a = applyEvent(emptyAssistant(), { type: "text", text: "쓰겠습니다" });
    a = beginResume(a);
    expect(applyEvent(a, { type: "text", text: "완료" }).text).toBe("쓰겠습니다\n\n완료");
    expect(applyEvent(a, { type: "done", output: "완료" }).text).toBe("쓰겠습니다\n\n완료");
  });

  it("marks a restored snapshot", () => {
    let a = applyEvent(emptyAssistant(), { type: "tool_call", tool: "write_file", args: {}, id: "w1" });
    a = applyEvent(a, { type: "tool_result", tool: "write_file", id: "w1", content: "💾", snapshot: "s-1" });
    expect(markRestored(a, "s-1").tools[0].restored).toBe(true);
  });
});
