"""Pydantic-AI Agent factory.

모델은 provider-prefixed 문자열로 지정 (멀티 provider):
  - anthropic:claude-sonnet-4-5
  - openai:gpt-4o
  - google-gla:gemini-1.5-pro
ENV `RESEARCH_MODEL`로 기본값 오버라이드 가능.
"""

from __future__ import annotations

import os

from agent.skills_loader import build_system_prompt
from agent.tool_registry import build_tools

DEFAULT_MODEL = "anthropic:claude-sonnet-4-5"


def resolve_model_name(model: str | None = None) -> str:
    """명시 인자 > ENV RESEARCH_MODEL > DEFAULT_MODEL."""
    return model or os.getenv("RESEARCH_MODEL") or DEFAULT_MODEL


def make_agent(model: str | None = None):
    """19개 MCP tool + skill 기반 시스템 프롬프트를 갖춘 Pydantic-AI Agent."""
    from pydantic_ai import Agent

    return Agent(
        resolve_model_name(model),
        system_prompt=build_system_prompt(),
        tools=build_tools(),
    )
