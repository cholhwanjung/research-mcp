"""인용·참조·인용 문맥·arXiv 검색 — 코드가 쓰는 구조화 결과(LLM 없음).

도구 함수(`get_references_by_citations` 등)는 사람이 읽을 문자열을 내므로, 여기서는 그 아래 소스 헬퍼
(디스크 캐시 경유)를 직접 쓴다. velocity 내림차순, `min_velocity` 미달은 SS가 영향력 있다고 표시한 인용만
살린다. 오류 표지는 ToolFailure로 바꿔 호출측이 영구/일시 실패를 가르게 한다.
"""

from __future__ import annotations

import asyncio
import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone

from agent.autopilot.failures import MetaUnavailable, ToolFailure
from analysis.ranking import citation_velocity
from core.filter import drop_surveys
from core.http import get as http_get
from sources.arxiv import parse_arxiv
from sources.semantic_scholar import (
    SS_BASE,
    fetch_network_papers,
    get_contexts,
    lookup_error_message,
    resolve_id,
    ss_get,
)
from tools.search_tools import ARXIV_TIMEOUT

_VERSION = re.compile(r"v\d+$")


@dataclass
class NetworkPaper:
    ss_id: str
    arxiv_id: str | None
    title: str
    year: int | None
    citation_count: int
    velocity: float
    influential: bool = False


@dataclass
class ArxivHit:
    arxiv_id: str
    title: str
    year: int | None = None
    abstract: str = ""
    authors: list[str] = field(default_factory=list)


def _year(current_year: int | None) -> int:
    return current_year or datetime.now(timezone.utc).year


def _network(raw: dict, current_year: int) -> NetworkPaper:
    arxiv = (raw.get("externalIds") or {}).get("ArXiv")
    return NetworkPaper(
        ss_id=str(raw.get("paperId") or ""),
        arxiv_id=_VERSION.sub("", str(arxiv)) if arxiv else None,
        title=str(raw.get("title") or ""),
        year=raw.get("year"),
        citation_count=int(raw.get("citationCount") or 0),
        velocity=round(citation_velocity(raw, current_year), 1),
        influential=bool(raw.get("is_influential")),
    )


def rank_network(raw: list[dict], *, top_k: int, min_velocity: float, current_year: int) -> list[NetworkPaper]:
    papers = sorted((_network(p, current_year) for p in raw), key=lambda p: -p.velocity)
    kept = [p for p in papers if min_velocity <= 0 or p.velocity >= min_velocity or p.influential]
    return kept[:top_k]


async def _detail(paper_id: str, fields: str) -> dict:
    data = await ss_get(f"{SS_BASE}/{resolve_id(paper_id)}", {"fields": fields})
    err = lookup_error_message(paper_id, data)
    if err:
        raise MetaUnavailable(err)
    return data


async def fetch_references(
    paper_id: str, *, top_k: int = 20, min_velocity: float = 10.0, current_year: int | None = None, max_fetch: int = 500
) -> list[NetworkPaper]:
    detail = await _detail(paper_id, "paperId,title,referenceCount")
    raw = await fetch_network_papers(detail["paperId"], "references", "citedPaper", max_fetch=max_fetch)
    return rank_network(raw, top_k=top_k, min_velocity=min_velocity, current_year=_year(current_year))


async def fetch_citations(
    paper_id: str,
    *,
    top_k: int = 20,
    min_velocity: float = 10.0,
    exclude_recent_year: bool = True,
    current_year: int | None = None,
    max_fetch: int = 1000,
) -> list[NetworkPaper]:
    """SS citations는 출판일 내림차순이라 기본으로 최근 1년을 잘라낸다. 최근 anchor는 끄고 부른다."""
    year = _year(current_year)
    detail = await _detail(paper_id, "paperId,title,citationCount")
    raw = await fetch_network_papers(
        detail["paperId"], "citations", "citingPaper", max_fetch=max_fetch,
        publication_date_or_year=f":{year - 1}" if exclude_recent_year else None,
    )
    return rank_network(raw, top_k=top_k, min_velocity=min_velocity, current_year=year)


async def fetch_contexts(citing_id: str, cited_id: str) -> list[str]:
    return await get_contexts(citing_id, cited_id)


async def search_arxiv(query: str, max_results: int = 20) -> list[ArxivHit]:
    """arXiv 관련도 검색. 타임아웃·비정상 피드는 ⏳(일시 실패) — '결과 없음'으로 위장하지 않는다."""
    url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
        {"search_query": f"all:{query}", "sortBy": "relevance", "sortOrder": "descending",
         "max_results": str(min(max_results, 50))},
        safe=":+",
    )
    try:
        xml = await http_get(url, timeout=ARXIV_TIMEOUT)
    except asyncio.TimeoutError:
        raise ToolFailure("⏳ arXiv 검색 응답 없음 (timeout)", permanent=False)
    if not isinstance(xml, str) or "<feed" not in xml:
        raise ToolFailure("⏳ arXiv 검색 응답이 정상 피드가 아니다 (rate limit·장애)", permanent=False)
    hits: list[ArxivHit] = []
    for p in drop_surveys(parse_arxiv(xml)):
        published = str(p.get("published") or "")
        hits.append(ArxivHit(
            arxiv_id=_VERSION.sub("", str(p.get("arxiv_id") or "")),
            title=" ".join(str(p.get("title") or "").split()),
            year=int(published[:4]) if published[:4].isdigit() else None,
            abstract=" ".join(str(p.get("abstract") or "").split()),
            authors=list(p.get("authors") or []),
        ))
    return hits
