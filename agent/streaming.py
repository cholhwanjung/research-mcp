"""에이전트 실행을 구조화 이벤트로 스트리밍 + SSE wire 포맷.

- `run_event_stream` : in-process 소비자(CLI·세션 저장·평가)용 풍부한 이벤트(dict).
- `run_sse_stream`   : FastAPI SSE 엔드포인트용 wire-safe 문자열.
이벤트 타입: start · tool_call · tool_result · text · approval_required(승인 대기로 멈춤, ADR-063) · done.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

_RESULT_LIMIT = 2000


def format_sse(event: str, data: Any) -> str:
    """SSE wire 포맷 한 프레임. data가 str이 아니면 JSON 직렬화."""
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


async def run_event_stream(
    agent: Any,
    message: str | None,
    message_history: list | None = None,
    *,
    deps: Any = None,
    deferred_tool_results: Any = None,
    usage_limits: Any = None,
) -> AsyncIterator[dict]:
    """agent를 실행하며 노드 단위로 이벤트를 yield. 마지막은 항상 done(output·messages·usage).

    승인이 필요한 호출에서 멈추면 done 앞에 approval_required를 내고 output은 None이다. 승인 결과는 같은
    message_history와 deferred_tool_results로 다시 부른다.
    """
    from pydantic_ai import Agent
    from pydantic_ai.messages import ModelRequest, ToolReturnPart
    from pydantic_ai.tools import DeferredToolRequests

    yield {"type": "start", "message": message}
    emitted: set[str] = set()

    def tool_results(parts) -> list[dict]:
        events = []
        for part in parts:
            if isinstance(part, ToolReturnPart) and part.tool_call_id not in emitted:
                emitted.add(part.tool_call_id)
                events.append({"type": "tool_result", "tool": part.tool_name, "id": part.tool_call_id,
                               "content": str(part.content)[:_RESULT_LIMIT], "metadata": part.metadata or {}})
        return events

    async with agent.iter(message, message_history=message_history, deps=deps,
                          deferred_tool_results=deferred_tool_results, usage_limits=usage_limits) as run:
        async for node in run:
            if Agent.is_model_request_node(node):
                for event in tool_results(node.request.parts):
                    yield event
            elif Agent.is_call_tools_node(node):
                for part in node.model_response.parts:
                    kind = getattr(part, "part_kind", None)
                    if kind == "tool-call":
                        yield {"type": "tool_call", "tool": part.tool_name, "args": part.args, "id": part.tool_call_id}
                    elif kind == "text" and part.content:
                        yield {"type": "text", "text": part.content}

    result = run.result
    for message_ in result.new_messages():
        if isinstance(message_, ModelRequest):
            for event in tool_results(message_.parts):
                yield event
    output = getattr(result, "output", None)
    if isinstance(output, DeferredToolRequests):
        yield {"type": "approval_required", "requests": [
            {"id": call.tool_call_id, "tool": call.tool_name, "args": call.args_as_dict(),
             "metadata": output.metadata.get(call.tool_call_id, {})}
            for call in output.approvals
        ]}
        output = None
    usage = result.usage
    yield {
        "type": "done",
        "output": output,
        "messages": result.all_messages(),
        "usage": {"requests": usage.requests, "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens},
    }


async def run_sse_stream(agent: Any, message: str | None, message_history: list | None = None, **kwargs) -> AsyncIterator[str]:
    """run_event_stream을 SSE 프레임 문자열로 변환 (messages는 wire에서 제외)."""
    async for event in run_event_stream(agent, message, message_history, **kwargs):
        etype = event["type"]
        data = {k: v for k, v in event.items() if k not in ("type", "messages")}
        yield format_sse(etype, data)
