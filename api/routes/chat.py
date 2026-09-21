"""POST /chat — 에이전트 실행을 SSE로 스트리밍 + (session_id 있으면) 세션 영속.

승인이 필요한 호출은 approval_required 이벤트로 멈춘다. 같은 session_id로 `approvals`(tool_call_id → 결정)를
보내면 그 자리에서 재개한다. '이 세션 동안 허용'은 편집 도구만 세션에 기억한다(ADR-063).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from agent.streaming import format_sse, run_event_stream
from api.deps import get_agent, get_jobs, get_session_store, resolve_mode, verify_token
from api.models import ChatRequest
from api.sse import sse_response

router = APIRouter(dependencies=[Depends(verify_token)])


def _pending_calls(history: list) -> dict[str, str]:
    """마지막 메시지가 도구 호출 응답이면 그 호출들(tool_call_id → 도구 이름)."""
    from pydantic_ai.messages import ModelResponse, ToolCallPart

    if not history or not isinstance(history[-1], ModelResponse):
        return {}
    return {p.tool_call_id: p.tool_name for p in history[-1].parts if isinstance(p, ToolCallPart)}


@router.post("/chat")
async def chat(req: ChatRequest, request: Request):
    from pydantic_ai.tools import DeferredToolResults, ToolDenied

    from agent.permissions import Policy, rememberable
    from agent.runtime import HarnessDeps, resolve_model_name

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
    message: str | None = req.message
    deferred = None
    if req.approvals:
        pending = _pending_calls(history or [])
        if not sid or not pending or not set(req.approvals) <= set(pending):
            raise HTTPException(status_code=400, detail="approvals need a session whose last turn awaits those tool calls")
        deferred = DeferredToolResults(approvals={
            call_id: True if d.approved else ToolDenied(d.message or "사용자가 거부했다")
            for call_id, d in req.approvals.items()
        })
        store.add_grants(sid, [pending[call_id] for call_id, d in req.approvals.items()
                               if d.approved and d.remember and rememberable(pending[call_id])])
        message = None

    deps = HarnessDeps(
        policy=Policy(resolve_mode(req.mode), session_allow=store.get_grants(sid) if sid else set()),
        session_id=sid or "",
        model_name=resolve_model_name(req.model),
        jobs=get_jobs(request),
    )

    async def gen():
        full_messages = None
        async for event in run_event_stream(agent, message, message_history=history, deps=deps,
                                            deferred_tool_results=deferred):
            etype = event["type"]
            if etype == "done":
                full_messages = event.get("messages")
            yield format_sse(etype, {k: v for k, v in event.items() if k not in ("type", "messages")})
        if sid and full_messages is not None:
            store.clear(sid)
            store.append(sid, full_messages)

    return sse_response(gen())
