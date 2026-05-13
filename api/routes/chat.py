"""POST /chat — 에이전트 실행을 SSE로 스트리밍 + (session_id 있으면) 세션 영속."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from agent.streaming import format_sse, run_event_stream
from api.deps import get_agent, get_session_store, verify_token
from api.models import ChatRequest
from api.sse import sse_response

router = APIRouter(dependencies=[Depends(verify_token)])


@router.post("/chat")
async def chat(req: ChatRequest, request: Request):
    if req.model:
        from agent.runtime import make_agent

        try:
            agent = make_agent(req.model)
        except Exception as e:  # provider 키 미설정 등 — 스트림 시작 전에 깔끔히 실패
            raise HTTPException(status_code=400, detail=f"model init failed: {e}")
    else:
        agent = get_agent(request)

    store = get_session_store(request)
    sid = req.session_id
    history = store.get_history(sid) if sid else None

    async def gen():
        full_messages = None
        async for event in run_event_stream(agent, req.message, message_history=history):
            etype = event["type"]
            if etype == "done":
                full_messages = event.get("messages")
                yield format_sse("done", {"output": event.get("output")})
            else:
                yield format_sse(etype, {k: v for k, v in event.items() if k != "type"})
        if sid and full_messages is not None:
            store.clear(sid)
            store.append(sid, full_messages)

    return sse_response(gen())
