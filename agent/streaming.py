"""에이전트 실행을 구조화 이벤트로 스트리밍 + SSE wire 포맷.

- `run_event_stream` : in-process 소비자(CLI·세션 저장)용 풍부한 이벤트(dict).
- `run_sse_stream`   : FastAPI SSE 엔드포인트(W-2)용 wire-safe 문자열.
이벤트 타입: start · tool_call · text · done.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator


def format_sse(event: str, data: Any) -> str:
    """SSE wire 포맷 한 프레임. data가 str이 아니면 JSON 직렬화."""
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


async def run_event_stream(
    agent: Any,
    message: str,
    message_history: list | None = None,
) -> AsyncIterator[dict]:
    """agent를 실행하며 노드 단위로 이벤트를 yield. 마지막은 항상 done."""
    from pydantic_ai import Agent

    yield {"type": "start", "message": message}

    async with agent.iter(message, message_history=message_history) as run:
        async for node in run:
            if Agent.is_call_tools_node(node):
                for part in node.model_response.parts:
                    kind = getattr(part, "part_kind", None)
                    if kind == "tool-call":
                        yield {
                            "type": "tool_call",
                            "tool": part.tool_name,
                            "args": part.args,
                        }
                    elif kind == "text" and part.content:
                        yield {"type": "text", "text": part.content}

    result = run.result
    output = getattr(result, "output", None)
    if output is None:
        output = getattr(result, "data", None)
    yield {
        "type": "done",
        "output": output,
        "messages": result.all_messages(),
    }


async def run_sse_stream(
    agent: Any,
    message: str,
    message_history: list | None = None,
) -> AsyncIterator[str]:
    """run_event_stream을 SSE 프레임 문자열로 변환 (messages는 wire에서 제외)."""
    async for event in run_event_stream(agent, message, message_history):
        etype = event["type"]
        data = {k: v for k, v in event.items() if k not in ("type", "messages")}
        yield format_sse(etype, data)
