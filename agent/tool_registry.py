"""tools/*.py의 MCP tool 함수를 Pydantic-AI Agent용으로 수집.

server.py의 `register(mcp)` 패턴을 그대로 재사용한다 — `mcp.tool()(fn)` 호출을
가로채는 collector 객체를 각 모듈의 register()에 주입하면, MCP가 노출하는 함수
집합과 1:1 동일한 목록을 중복 정의 0으로 얻는다 (스키마 자동 동기화).
"""

from __future__ import annotations

from typing import Callable

from tools import (
    blog_tools,
    citation_tools,
    feed_tools,
    pdf_tools,
    search_tools,
    viz_tools,
    wiki_tools,
)

# server.py와 동일한 모듈 집합/순서.
_TOOL_MODULES = (
    search_tools,
    citation_tools,
    pdf_tools,
    wiki_tools,
    feed_tools,
    viz_tools,
    blog_tools,
)


class _Collector:
    """`mcp.tool()(fn)` 호출을 가로채 fn을 기록하는 가짜 MCP."""

    def __init__(self) -> None:
        self.functions: list[Callable] = []

    def tool(self, *args, **kwargs):
        def _decorator(fn: Callable) -> Callable:
            self.functions.append(fn)
            return fn

        return _decorator


def collect_tool_functions() -> list[Callable]:
    """server.py가 MCP에 등록하는 것과 동일한 tool 함수 목록."""
    collector = _Collector()
    for module in _TOOL_MODULES:
        module.register(collector)
    return collector.functions


def build_tools() -> list:
    """수집한 함수를 pydantic_ai.Tool로 래핑. 이름·설명·스키마는 함수에서 자동 추론."""
    from pydantic_ai import Tool

    return [Tool(fn) for fn in collect_tool_functions()]
