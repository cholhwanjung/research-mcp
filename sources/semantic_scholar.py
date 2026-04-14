"""Semantic Scholar 클라이언트. SS_BASE/resolve_id/fetch_network_papers.

Phase 3.0부터 외부 HTTP 호출은 `core.cache.get_or_fetch`로 감싸 디스크 캐시.
SS rate-limit (HTTP 429) 직격 방지 + 같은 호출 반복 시 0 네트워크.
"""

from __future__ import annotations

import asyncio
import json
import re

from core import cache
from core.http import get

SS_BASE = "https://api.semanticscholar.org/graph/v1/paper"
SS_REC_BASE = "https://api.semanticscholar.org/recommendations/v1"
SS_CACHE_TTL = 7 * 24 * 3600  # 1주일 — citation count는 자주 안 변함


def _cache_key(url: str, params: dict | None) -> str:
    """캐시 키. URL + 정렬된 params JSON."""
    if not params:
        return url
    return f"{url}?{json.dumps(params, sort_keys=True)}"


async def ss_get(url: str, params: dict | None = None, ttl: int = SS_CACHE_TTL):
    """SS API 호출 + 디스크 캐시. 모든 SS HTTP 진입점은 이 헬퍼를 거친다."""
    return await cache.get_or_fetch(
        _cache_key(url, params),
        lambda u=url, p=params: get(u, p),
        ttl=ttl,
    )


def resolve_id(paper_id: str) -> str:
    """다양한 입력 형식을 Semantic Scholar API 형식으로 정규화."""
    paper_id = paper_id.strip()
    upper = paper_id.upper()

    if upper.startswith("ARXIV:"):
        return f"ARXIV:{paper_id[6:]}"
    if upper.startswith("DOI:"):
        return f"DOI:{paper_id[4:]}"
    if upper.startswith("CORPUSID:"):
        return f"CorpusId:{paper_id[9:]}"
    if upper.startswith("MAG:"):
        return f"MAG:{paper_id[4:]}"
    if upper.startswith("ACL:"):
        return f"ACL:{paper_id[4:]}"
    if upper.startswith("PMID:"):
        return f"PMID:{paper_id[5:]}"
    if upper.startswith("PMCID:"):
        return f"PMCID:{paper_id[6:]}"
    if re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", paper_id):
        return f"ARXIV:{paper_id}"
    if paper_id.startswith("10."):
        return f"DOI:{paper_id}"
    if re.match(r"^[0-9a-fA-F]{40}$", paper_id):
        return paper_id
    return paper_id


async def fetch_network_papers(
    pid: str,
    endpoint: str,
    item_key: str,
    max_fetch: int,
    sleep_sec: float = 1.5,
) -> list[dict]:
    """SS API offset 기반 페이지네이션으로 citations 또는 references 전량 수집.

    공식 문서 기준:
    - limit 최대 1000 (한 번 요청에 1000개 초과 불가)
    - 응답의 'next' 필드가 다음 offset; 없으면 마지막 페이지
    """
    FIELDS = "title,authors,year,citationCount,influentialCitationCount,externalIds,url,venue"
    BATCH = 1000
    all_papers: list[dict] = []
    offset = 0

    while len(all_papers) < max_fetch:
        limit = min(BATCH, max_fetch - len(all_papers))
        url = f"{SS_BASE}/{pid}/{endpoint}"
        params = {"fields": FIELDS, "limit": str(limit), "offset": str(offset)}
        resp = await ss_get(url, params)
        if not isinstance(resp, dict):
            break

        items = [
            c[item_key]
            for c in (resp.get("data") or [])
            if c.get(item_key, {}).get("title")
        ]
        if not items:
            break

        all_papers.extend(items)

        next_offset = resp.get("next")
        if next_offset is None:
            break

        offset = next_offset
        await asyncio.sleep(sleep_sec)

    return all_papers


async def get_contexts(citing_id: str, cited_id: str) -> list[str]:
    """`citing_id` 논문의 references 중 `cited_id`에 해당하는 항목의 본문 인용 문맥 스니펫.

    `cited_id`는 arXiv ID, DOI, SS sha 모두 허용. references 페이지를 순회하며
    `citedPaper.paperId == sha(cited_id)` 또는 `citedPaper.externalIds.ArXiv == arxiv(cited_id)` 매칭.
    """
    citing_pid = resolve_id(citing_id)
    target_sha, target_arxiv = _cited_identifiers(cited_id)
    offset = 0

    while True:
        url = f"{SS_BASE}/{citing_pid}/references"
        params = {
            "fields": "contexts,citedPaper.paperId,citedPaper.externalIds",
            "limit": "100",
            "offset": str(offset),
        }
        resp = await ss_get(url, params)
        if not isinstance(resp, dict):
            return []

        for entry in resp.get("data") or []:
            cp = entry.get("citedPaper") or {}
            cp_pid = cp.get("paperId")
            cp_arxiv = (cp.get("externalIds") or {}).get("ArXiv")
            if (target_sha and cp_pid == target_sha) or (
                target_arxiv and cp_arxiv == target_arxiv
            ):
                return list(entry.get("contexts") or [])

        next_offset = resp.get("next")
        if next_offset is None:
            return []
        offset = next_offset


def _cited_identifiers(cited_id: str) -> tuple[str | None, str | None]:
    """cited_id에서 (sha, arxiv_id) 후보를 추출. 둘 중 매칭 가능한 쪽으로 비교."""
    rid = resolve_id(cited_id)
    if rid.startswith("ARXIV:"):
        return None, rid[6:]
    if re.match(r"^[0-9a-fA-F]{40}$", rid):
        return rid, None
    # DOI 등 — paperId 매칭은 못 함. ArXiv 추정도 못 함.
    return None, None


_REC_FIELDS = "title,authors,year,citationCount,externalIds,url,venue"


async def recommend_for_paper(paper_id: str, k: int = 10) -> list[dict]:
    """SS Recommendations API: 콘텐츠 유사도 기반 추천 논문 k건. 인용 그래프와 별개 (D-4)."""
    rid = resolve_id(paper_id)
    url = f"{SS_REC_BASE}/papers/forpaper/{rid}"
    params = {"limit": str(k), "fields": _REC_FIELDS}
    resp = await ss_get(url, params)
    if not isinstance(resp, dict):
        return []
    return list(resp.get("recommendedPapers") or [])
