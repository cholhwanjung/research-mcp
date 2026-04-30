"""MCP tools: search_papers, get_paper_by_id. server.py에서 본문 그대로 이전 (Phase 1.3b)."""

from __future__ import annotations

import urllib.parse
from datetime import datetime, timezone

from analysis.format import fmt_paper as _fmt_paper
from core.filter import drop_surveys as _drop_surveys
from core.http import get as _get
from sources.arxiv import parse_arxiv as _parse_arxiv
from sources.semantic_scholar import (
    SS_BASE,
    resolve_id as _resolve_id,
    ss_get as _ss_get,
)


async def search_papers(
    query: str,
    max_results: int = 20,
    category: str = "",
) -> str:
    """주제/키워드로 arXiv에서 논문을 검색합니다.
    결과는 관련도 순으로 정렬되며, 최근 1년 / 3년 / 5년 이내로 분류해 반환합니다.

    Args:
        query:       검색 키워드 (예: "vision language model", "contrastive learning")
        max_results: 최대 논문 수 (기본 20, 최대 50)
        category:    arXiv 카테고리 필터 (예: "cs.CV"). 비우면 전체 검색.
    """
    max_results = min(max_results, 50)
    search = f"all:{query}"
    if category:
        search = f"cat:{category}+AND+{search}"

    url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
        {
            "search_query": search,
            "sortBy": "relevance",
            "sortOrder": "descending",
            "max_results": str(max_results),
        },
        safe=":+",
    )

    xml = await _get(url)
    if not isinstance(xml, str):
        return "❌ arXiv API 응답 오류"

    papers = _parse_arxiv(xml)
    # ADR-021: title에 \bsurvey\b 포함된 논문은 워크플로우에서 의미 없음 → 제외.
    papers = _drop_surveys(papers)
    if not papers:
        return f"'{query}'에 대한 검색 결과가 없습니다."

    now = datetime.now(timezone.utc)

    def _year_diff(published: str) -> float:
        try:
            pub_dt = datetime.strptime(published[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return (now - pub_dt).days / 365.25
        except Exception:
            return float("inf")

    buckets: dict[str, list] = {"1y": [], "3y": [], "5y": [], "old": []}
    for p in papers:
        diff = _year_diff(p.get("published", ""))
        key = "1y" if diff <= 1 else "3y" if diff <= 3 else "5y" if diff <= 5 else "old"
        buckets[key].append(p)

    lines = [f"🔍 '{query}' 검색 결과 ({len(papers)}편) — 관련도 순 정렬\n"]

    bucket_meta = [
        ("1y",  "📅 최근 1년 이내"),
        ("3y",  "📅 1년 ~ 3년 이내"),
        ("5y",  "📅 3년 ~ 5년 이내"),
        ("old", "📦 5년 초과"),
    ]
    for key, label in bucket_meta:
        bucket = buckets[key]
        if not bucket:
            continue
        lines.append(f"{label} ({len(bucket)}편)")
        lines.append("─" * 60)
        for i, p in enumerate(bucket, 1):
            lines.append(f"[{i}] {_fmt_paper(p)}\n")

    return "\n".join(lines)


async def get_paper_by_id(paper_id: str) -> str:
    """논문 ID로 상세 정보를 조회합니다.
    arXiv ID, DOI, Semantic Scholar ID를 모두 지원합니다.

    Args:
        paper_id: arXiv ID (예: "2301.12597"), DOI (예: "10.48550/arXiv.2301.12597"),
                  또는 Semantic Scholar SHA ID.
    """
    fields = (
        "title,authors,abstract,url,year,venue,citationCount,"
        "referenceCount,influentialCitationCount,fieldsOfStudy,"
        "publicationTypes,externalIds,tldr"
    )
    data = await _ss_get(f"{SS_BASE}/{_resolve_id(paper_id)}", {"fields": fields})

    if isinstance(data, str) or "paperId" not in data:
        return f"❌ 논문을 찾을 수 없습니다: {paper_id}"

    lines = [f"📄 {data.get('title', 'Untitled')}\n"]

    authors = data.get("authors", [])
    if authors:
        lines.append(f"Authors: {', '.join(a.get('name', '') for a in authors[:10])}")
    if data.get("year"):
        lines.append(f"Year: {data['year']}")
    if data.get("venue"):
        lines.append(f"Venue: {data['venue']}")
    if data.get("fieldsOfStudy"):
        lines.append(f"Fields: {', '.join(data['fieldsOfStudy'])}")

    lines.append(f"Citations: {data.get('citationCount', 0)}")
    lines.append(f"Influential Citations: {data.get('influentialCitationCount', 0)}")
    lines.append(f"References: {data.get('referenceCount', 0)}")

    tldr = data.get("tldr")
    if tldr and tldr.get("text"):
        lines.append(f"\n💡 TL;DR: {tldr['text']}")

    if data.get("abstract"):
        lines.append(f"\n📝 Abstract:\n{data['abstract']}")

    ext = data.get("externalIds") or {}
    if ext.get("ArXiv"):
        lines.append(f"\n🔗 arXiv: https://arxiv.org/abs/{ext['ArXiv']}")
    if ext.get("DOI"):
        lines.append(f"🔗 DOI: https://doi.org/{ext['DOI']}")
    if data.get("url"):
        lines.append(f"🔗 Semantic Scholar: {data['url']}")

    return "\n".join(lines)


def register(mcp) -> None:
    mcp.tool()(search_papers)
    mcp.tool()(get_paper_by_id)
