"""요약 에이전트 — provider 무관(pydantic-ai 모델 문자열 또는 Model), 구조화 출력.

도구는 논문 읽기 하나뿐이고 그 출력은 신뢰 경계 표지로 감싼다. 출력은 NoteDraft —
파일 쓰기·로그·제어 노트는 코드가 한다. 한 반복의 요청·토큰은 UsageLimits로 막는다.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from pydantic_ai import Agent, Tool
from pydantic_ai.usage import UsageLimits

from agent.autopilot.notes import NoteDraft, PaperMeta
from agent.autopilot.untrusted import TRUST_RULE, untrusted_tool

READ_PAGES = 15
DEFAULT_LIMITS = UsageLimits(request_limit=12, total_tokens_limit=400_000)

READER_INSTRUCTIONS = "\n".join(
    [
        "너는 연구 논문 1편을 읽고 한국어 연구 노트 초안(NoteDraft)을 만든다.",
        f"read_paper(paper_id, max_pages={READ_PAGES})로 본문을 읽고 그 본문만 근거로 쓴다. 초록이나 기억에 기대지 않는다.",
        "수치는 원문 표기 그대로 옮긴다. 원문에 없는 수치를 만들거나 반올림하지 않는다.",
        "findings에는 결과와 저자가 밝힌 한계를 함께 적는다.",
        "hubs는 사용자 메시지의 허용 목록에서 논문 자신의 주제만 1~3개 고른다. 인용 관계는 소속 근거가 아니다.",
        "insight_candidate는 이 논문이 다른 연구와 엮이는 한 줄이다. 근거가 없으면 빈 문자열로 둔다.",
        "문서 식별자나 작업 규칙 이름 같은 내부 표기를 노트 문장에 쓰지 않는다.",
        TRUST_RULE,
    ]
)


def reader_prompt(meta: PaperMeta, scope: list[str], allowed_hubs: set[str]) -> str:
    return "\n".join(
        [
            f"논문: {meta.title} (arXiv:{meta.arxiv_id}, {meta.year or '-'}, {meta.venue or '-'})",
            f"이번 실행의 주제 범위: {', '.join(scope)}",
            "허용 hub: " + ", ".join(sorted(allowed_hubs)),
            "본문을 읽고 NoteDraft를 채워라.",
        ]
    )


def make_reader_agent(
    model: Any, *, read_paper_fn: Callable[..., Awaitable[str]] | None = None
) -> Agent:
    if read_paper_fn is None:
        from tools.pdf_tools import read_paper as read_paper_fn
    tool = Tool(untrusted_tool(read_paper_fn, source_prefix="arxiv", id_arg="paper_id"), name="read_paper")
    return Agent(model, output_type=NoteDraft, instructions=READER_INSTRUCTIONS, tools=[tool], retries=2)


async def summarize_with_agent(
    agent: Agent,
    meta: PaperMeta,
    scope: list[str],
    allowed_hubs: set[str],
    usage_limits: UsageLimits | None = None,
) -> NoteDraft:
    result = await agent.run(reader_prompt(meta, scope, allowed_hubs), usage_limits=usage_limits or DEFAULT_LIMITS)
    return result.output
