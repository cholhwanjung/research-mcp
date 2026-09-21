"""API request/response Pydantic 모델 (OpenAPI → TS codegen 입력, W-3)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ApprovalDecision(BaseModel):
    approved: bool
    remember: bool = False  # '이 세션 동안 허용' — 편집 도구만 기억된다
    message: str | None = None  # 거부 이유 (모델에 전달)


class ChatRequest(BaseModel):
    message: str
    model: str | None = None
    session_id: str | None = None
    mode: Literal["read_only", "ask", "accept_edits"] | None = None
    approvals: dict[str, ApprovalDecision] | None = None  # 직전 approval_required의 tool_call_id → 결정


class SkillItem(BaseModel):
    name: str
    description: str
    triggers: list[str]
