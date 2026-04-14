"""MCP tools: get_references_by_citations, get_citations_by_citations.

D-3 (Phase 3.1):
- 기본 `max_fetch=200`로 lazy growth — 첫 호출 부하 완화.
- `sort='count'|'velocity'` 옵션 — velocity는 ADR-004.
"""

from __future__ import annotations

from analysis.ranking import render_sorted_list as _render_sorted_list
from sources.semantic_scholar import (
    SS_BASE,
    fetch_network_papers as _fetch_network_papers,
    get_contexts as _get_contexts,
    resolve_id as _resolve_id,
    ss_get as _ss_get,
)


async def get_references_by_citations(
    paper_id: str,
    top_k: int = 20,
    max_fetch: int = 200,
    sort: str = "count",
    current_year: int | None = None,
) -> str:
    """논문이 참조(reference)한 논문들을 정렬해 반환합니다.

    Args:
        paper_id:     arXiv ID (예: "2301.12597"), DOI, 또는 Semantic Scholar ID.
        top_k:        반환할 상위 논문 수 (기본 20).
        max_fetch:    최대 수집 reference 수 (기본 200, D-3 lazy growth).
        sort:         "count"(인용수 순, 기본) 또는 "velocity"(연평균 인용 속도, ADR-004).
        current_year: velocity 계산 기준 연도. None이면 현재.
    """
    detail = await _ss_get(
        f"{SS_BASE}/{_resolve_id(paper_id)}",
        {"fields": "paperId,title,referenceCount"},
    )
    if isinstance(detail, str) or "paperId" not in detail:
        return f"❌ 논문을 찾을 수 없습니다: {paper_id}"

    pid = detail["paperId"]
    paper_title = detail.get("title", paper_id)
    total = detail.get("referenceCount", 0)

    refs = await _fetch_network_papers(pid, "references", "citedPaper", max_fetch=max_fetch)

    if not refs:
        return f"'{paper_title}'의 reference 논문을 가져올 수 없습니다."

    header_suffix = "velocity 순" if sort == "velocity" else "인용수 순"
    return _render_sorted_list(
        refs,
        f"📤 '{paper_title}' — Reference 논문 ({header_suffix} 정렬)",
        total,
        len(refs),
        top_k,
        sort=sort,
        current_year=current_year,
    )


async def get_citations_by_citations(
    paper_id: str,
    top_k: int = 20,
    max_fetch: int = 200,
    sort: str = "count",
    current_year: int | None = None,
) -> str:
    """논문을 인용(citation)한 후속 연구들을 정렬해 반환합니다.

    SS API는 최신순으로 반환 — `max_fetch`를 늘리면 오래된 핵심 후속도 수집.

    Args:
        paper_id:     arXiv ID (예: "2304.08485"), DOI, 또는 Semantic Scholar ID.
        top_k:        반환할 상위 논문 수 (기본 20).
        max_fetch:    최대 수집 citation 수 (기본 200, D-3 lazy growth).
        sort:         "count"(기본) 또는 "velocity" (ADR-004).
        current_year: velocity 기준 연도.
    """
    detail = await _ss_get(
        f"{SS_BASE}/{_resolve_id(paper_id)}",
        {"fields": "paperId,title,citationCount"},
    )
    if isinstance(detail, str) or "paperId" not in detail:
        return f"❌ 논문을 찾을 수 없습니다: {paper_id}"

    pid = detail["paperId"]
    paper_title = detail.get("title", paper_id)
    total = detail.get("citationCount", 0)

    cits = await _fetch_network_papers(
        pid, "citations", "citingPaper", max_fetch=max_fetch
    )

    if not cits:
        return f"'{paper_title}'의 인용 논문을 가져올 수 없습니다."

    header_suffix = "velocity 순" if sort == "velocity" else "인용수 순"
    return _render_sorted_list(
        cits,
        f"📥 '{paper_title}' — Citation 논문 ({header_suffix} 정렬)",
        total,
        len(cits),
        top_k,
        sort=sort,
        current_year=current_year,
    )


async def get_citation_contexts(citing_id: str, cited_id: str) -> str:
    """`citing_id` 논문이 `cited_id` 논문을 인용한 본문 문맥 스니펫을 반환합니다.

    동적 토픽 분석 (ADR-009) 입력으로 사용 — Claude가 컨텍스트 + 초록을 결합해
    토픽 태그와 `cited_for` 노트를 생성합니다.

    Args:
        citing_id: 인용하는 논문 (arXiv ID / DOI / SS sha).
        cited_id:  인용된 논문.
    """
    snippets = await _get_contexts(citing_id, cited_id)
    if not snippets:
        return (
            f"❌ 컨텍스트 없음: arXiv:{citing_id} → arXiv:{cited_id}\n"
            "   가능한 원인: 인용 관계 미존재 / SS가 본문 컨텍스트 미수집 / cited_id 매칭 실패."
        )
    lines = [f"📌 인용 컨텍스트: arXiv:{citing_id} → arXiv:{cited_id} ({len(snippets)}건)"]
    for i, s in enumerate(snippets, 1):
        lines.append(f"  [{i}] {s}")
    return "\n".join(lines)


def register(mcp) -> None:
    mcp.tool()(get_references_by_citations)
    mcp.tool()(get_citations_by_citations)
    mcp.tool()(get_citation_contexts)
