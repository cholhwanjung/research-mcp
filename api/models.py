"""API request/response Pydantic 모델 (OpenAPI → TS codegen 입력, W-3)."""

from __future__ import annotations

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    model: str | None = None
    session_id: str | None = None


class SkillItem(BaseModel):
    name: str
    description: str
    triggers: list[str]
