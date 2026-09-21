"""DI 의존성 — agent / session store (app.state) + bearer token 인증."""

from __future__ import annotations

import os

from fastapi import Header, HTTPException, Request


def verify_token(authorization: str | None = Header(default=None)) -> None:
    """RESEARCH_API_TOKEN env가 설정돼 있으면 `Authorization: Bearer <token>` 강제.

    미설정이면 인증 비활성 (로컬 self-hosted 단일 사용자 기본).
    """
    expected = os.getenv("RESEARCH_API_TOKEN")
    if not expected:
        return
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="invalid or missing bearer token")


def resolve_mode(requested: str | None) -> str:
    """권한 모드. 토큰(RESEARCH_API_TOKEN) 없이 뜬 API는 읽기 전용으로 고정한다(ADR-063). 아니면 요청 모드, 기본 ask."""
    if not os.getenv("RESEARCH_API_TOKEN"):
        return "read_only"
    return requested or "ask"


def get_jobs(request: Request):
    jobs = getattr(request.app.state, "jobs", None)
    if jobs is None:
        from agent.jobs import AutopilotJobs

        jobs = request.app.state.jobs = AutopilotJobs()
    return jobs


def get_agent(request: Request):
    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        raise HTTPException(status_code=503, detail="agent not initialized")
    return agent


def get_session_store(request: Request):
    store = getattr(request.app.state, "session_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="session store not initialized")
    return store
