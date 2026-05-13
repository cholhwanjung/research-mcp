"""SSE 응답 헬퍼 — agent.streaming이 만든 SSE 프레임 문자열을 그대로 흘려보낸다."""

from __future__ import annotations

from typing import AsyncIterator

from fastapi.responses import StreamingResponse


def sse_response(generator: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
