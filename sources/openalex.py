"""OpenAlex 클라이언트 — SS 연도 bucket이 잘렸을 때 그 해 인용수 상위를 보강하는 보조 소스 (ADR-071).

- 키 없이 호출 가능(일 1,000크레딧·10 req/s). `OPENALEX_API_KEY` env가 있으면 `api_key` 파라미터로 첨부(10배).
- 커버리지가 SS보다 낮다(LoRA 실측 2026-10-14: cited_by_count 2,488 vs SS 24,234) — 1차 소스가 아니라
  SS가 잘라낸 연도에서 놓친 상위 후보를 찾는 데만 쓴다. 후보는 DOI로 SS에서 되찾아 vault 키(arXiv ID)·velocity를 얻는다.
- 모든 호출은 `oa_get` → `core.cache.get_or_fetch` 경유. 오류 본문은 캐시하지 않는다.
"""

from __future__ import annotations

import json
import os

from core import cache
from core.http import get

OA_BASE = "https://api.openalex.org"
OA_CACHE_TTL = 7 * 24 * 3600  # SS와 같은 1주일


def _cache_key(url: str, params: dict | None) -> str:
    return f"{url}?{json.dumps(params, sort_keys=True)}" if params else url


def _worth_caching(value) -> bool:
    return isinstance(value, dict) and "error" not in value and "message" not in value


async def oa_get(url: str, params: dict | None = None, force_refresh: bool = False):
    """OpenAlex GET + 디스크 캐시. 모든 OpenAlex HTTP 진입점은 이 헬퍼를 거친다."""
    params = dict(params or {})
    key = os.environ.get("OPENALEX_API_KEY")
    if key:
        params["api_key"] = key
    return await cache.get_or_fetch(
        _cache_key(url, params),
        lambda: get(url, params),
        ttl=OA_CACHE_TTL,
        force_refresh=force_refresh,
        cache_if=_worth_caching,
    )


async def resolve_work_id(arxiv_id: str | None = None, doi: str | None = None) -> str | None:
    """arXiv ID 또는 DOI → OpenAlex W-id. DOI가 있으면 DOI, 없으면 arXiv DOI(10.48550/arxiv.<id>). 못 찾으면 None."""
    if doi:
        lookup = doi
    elif arxiv_id:
        lookup = f"10.48550/arxiv.{arxiv_id}"
    else:
        return None
    resp = await oa_get(f"{OA_BASE}/works/doi:{lookup}", {"select": "id"})
    if not isinstance(resp, dict) or not resp.get("id"):
        return None
    return str(resp["id"]).rsplit("/", 1)[-1]


async def top_citing_by_year(work_id: str, year: int, limit: int = 10) -> list[dict]:
    """`work_id`를 인용한 `year`년 논문을 인용수 내림차순으로 → [{title, year, cited_by_count, doi}]. DOI는 접두사 없이."""
    resp = await oa_get(
        f"{OA_BASE}/works",
        {
            "filter": f"cites:{work_id},publication_year:{year}",
            "sort": "cited_by_count:desc",
            "per-page": str(limit),
            "select": "title,publication_year,cited_by_count,doi,ids",
        },
    )
    if not isinstance(resp, dict) or "results" not in resp:
        return []
    out = []
    for w in resp["results"]:
        doi = w.get("doi")
        if doi:
            doi = doi.replace("https://doi.org/", "")
        out.append({
            "title": w.get("title"),
            "year": w.get("publication_year"),
            "cited_by_count": w.get("cited_by_count"),
            "doi": doi,
        })
    return out
