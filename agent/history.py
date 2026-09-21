"""대화 컨텍스트 예산 — 오래된 도구 결과를 생략 표지로 바꾼다(ADR-063).

최근 메시지는 그대로 두고, 그 이전의 도구 결과를 새것부터 합산해 문자 예산을 넘는 것부터 표지로 바꾼다.
호출·결과 쌍의 구조와 tool_call_id는 유지하고 추가 모델 호출은 하지 않는다.
"""

from __future__ import annotations

from dataclasses import replace

from pydantic_ai.messages import ModelMessage, ModelRequest, ToolReturnPart

OMITTED = "[이전 도구 결과 생략 — 필요하면 도구를 다시 부른다]"
DEFAULT_BUDGET = 120_000
DEFAULT_KEEP_LAST = 6


def _returns(message: ModelMessage) -> list[ToolReturnPart]:
    if not isinstance(message, ModelRequest):
        return []
    return [p for p in message.parts if isinstance(p, ToolReturnPart)]


def trim_tool_results(
    messages: list[ModelMessage], *, budget_chars: int = DEFAULT_BUDGET, keep_last: int = DEFAULT_KEEP_LAST
) -> list[ModelMessage]:
    cut = max(len(messages) - keep_last, 0)
    used = sum(len(str(p.content)) for m in messages[cut:] for p in _returns(m))
    out = list(messages)
    for i in range(cut - 1, -1, -1):
        message = messages[i]
        if not _returns(message):
            continue
        parts, changed = [], False
        for part in message.parts:
            if isinstance(part, ToolReturnPart) and part.content != OMITTED:
                size = len(str(part.content))
                if used + size > budget_chars:
                    part = replace(part, content=OMITTED)
                    changed = True
                else:
                    used += size
            parts.append(part)
        if changed:
            out[i] = replace(message, parts=parts)
    return out


def make_history_processor(*, budget_chars: int = DEFAULT_BUDGET, keep_last: int = DEFAULT_KEEP_LAST):
    def trim(messages: list[ModelMessage]) -> list[ModelMessage]:
        return trim_tool_results(messages, budget_chars=budget_chars, keep_last=keep_last)

    return trim


def history_capability(*, budget_chars: int = DEFAULT_BUDGET, keep_last: int = DEFAULT_KEEP_LAST):
    """모델 요청마다 히스토리를 줄이는 pydantic-ai capability(`Agent(capabilities=[...])`)."""
    from pydantic_ai.capabilities import ProcessHistory

    return ProcessHistory(make_history_processor(budget_chars=budget_chars, keep_last=keep_last))
