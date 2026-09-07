"""Semantic Scholar 클라이언트. SS_BASE/resolve_id/fetch_network_papers.

Phase 3.0부터 외부 HTTP 호출은 `core.cache.get_or_fetch`로 감싸 디스크 캐시.
SS rate-limit (HTTP 429) 직격 방지 + 같은 호출 반복 시 0 네트워크.
"""

from __future__ import annotations

import asyncio
import json
import re

from core import cache
from core.filter import is_survey
from core.http import get
from core.slug import is_arxiv_id

SS_BASE = "https://api.semanticscholar.org/graph/v1/paper"
SS_CACHE_TTL = 7 * 24 * 3600  # 1주일 — citation count는 자주 안 변함
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")  # SS paperId (sha)


def _cache_key(url: str, params: dict | None) -> str:
    """캐시 키. URL + 정렬된 params JSON."""
    if not params:
        return url
    return f"{url}?{json.dumps(params, sort_keys=True)}"


def response_error(data) -> str | None:
    """SS 상세 조회 응답의 오류 종류. 정상(`paperId` 있음)이면 None.

    - "not_found": 404 본문 `{"error": "Paper with id … not found"}` — 정말 없는 논문
    - "rejected":  `{"message": …}` — 429 호출 한도·403 등 요청 거절. 논문 유무와 무관
    - "error":     그 밖의 `{"error": …}` — 잘못된 ID 형식 등
    - "transport": dict가 아닌 본문(최종 429 텍스트·HTML 오류 페이지) 또는 `paperId` 없는 dict

    `core.http.get`은 상태 코드를 버리고 본문만 돌려주므로 본문 형태로 되짚는다. 호출측이
    "재시도할 것"과 "정말 없는 것"을 구분해야 무인 실행이 호출 한도를 없는 논문으로 오진하지 않는다.
    """
    if not isinstance(data, dict):
        return "transport"
    if "paperId" in data:
        return None
    if "error" in data:
        return "not_found" if "not found" in str(data["error"]).lower() else "error"
    if "message" in data:
        return "rejected"
    return "transport"


def lookup_error_message(paper_id: str, data) -> str | None:
    """상세 조회 guard용 사용자 메시지. 정상이면 None. `❌`는 미매핑, `⏳`는 재시도 대상."""
    kind = response_error(data)
    if kind is None:
        return None
    if kind == "not_found":
        return f"❌ 논문을 찾을 수 없습니다: {paper_id}"
    if kind == "rejected":
        return (
            f"⏳ Semantic Scholar가 요청을 거절했습니다 (호출 한도 429 등): {paper_id} — "
            f"없는 논문이 아닙니다. 잠시 후 다시 시도하세요. ({data.get('message')})"
        )
    if kind == "error":
        return f"⚠️ Semantic Scholar 오류 응답: {paper_id} — {data.get('error')}"
    return (
        f"⏳ Semantic Scholar 응답이 비정상입니다 (일시 장애·최종 429 텍스트): {paper_id} — "
        f"없는 논문이 아닙니다. 잠시 후 다시 시도하세요."
    )


def _worth_caching(value) -> bool:
    """캐시에 남길 응답인가. 오류 본문(str, `error`/`message` 키)과 빈 페이지(`data: []`)는 남기지 않는다.

    `core.http.get`은 상태 코드와 무관하게 본문을 돌려주고, SS는 색인 지연 중 빈 `data`를 200으로
    준다. 그대로 TTL(7일) 캐시하면 일시적 상태가 고정된다 — autopilot 실측(2026-09-06)에서
    citationCount=2인 논문의 citations 요청이 `data: []`로 굳어 "가져올 수 없습니다"만 재생했다.
    """
    if not isinstance(value, dict):
        return False
    if "error" in value or "message" in value:
        return False
    if "data" in value and not value["data"]:
        return False
    return True


async def ss_get(url: str, params: dict | None = None, ttl: int = SS_CACHE_TTL):
    """SS API 호출 + 디스크 캐시. 모든 SS HTTP 진입점은 이 헬퍼를 거친다.

    일시적 응답(빈 페이지·오류 본문)은 돌려주되 캐시하지 않는다 — `_worth_caching`.
    """
    return await cache.get_or_fetch(
        _cache_key(url, params),
        lambda u=url, p=params: get(u, p),
        ttl=ttl,
        cache_if=_worth_caching,
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
    if is_arxiv_id(paper_id):
        return f"ARXIV:{paper_id}"
    if paper_id.startswith("10."):
        return f"DOI:{paper_id}"
    return paper_id


async def fetch_network_papers(
    pid: str,
    endpoint: str,
    item_key: str,
    max_fetch: int,
    sleep_sec: float = 1.5,
    publication_date_or_year: str | None = None,
) -> list[dict]:
    """SS API offset 기반 페이지네이션으로 citations / references 수집.

    공식 문서 (sources/swagger.json) 기준:
    - limit 최대 1000, 응답 `next` 필드로 다음 offset.
    - **citations endpoint는 publicationDate 내림차순으로 응답** — 인기 논문에서
      첫 페이지는 신생 인용수 0 논문으로 가득. 의미 있는 결과를 얻으려면
      `publication_date_or_year=":YYYY"` 필터로 최근 1년을 잘라낸다.
    - light 필드 + `isInfluential` (ADR-014 보강): 응답 크기는 유지하면서
      velocity 임계값 미달이라도 SS가 영향력 있다고 표시한 인용을 살린다.
      entry top-level의 `isInfluential`은 paper dict의 `is_influential` 키로 주입.
    """
    FIELDS = "paperId,title,year,citationCount,externalIds,isInfluential"
    BATCH = 1000
    all_papers: list[dict] = []
    offset = 0

    while len(all_papers) < max_fetch:
        limit = min(BATCH, max_fetch - len(all_papers))
        url = f"{SS_BASE}/{pid}/{endpoint}"
        params = {"fields": FIELDS, "limit": str(limit), "offset": str(offset)}
        if publication_date_or_year:
            params["publicationDateOrYear"] = publication_date_or_year
        resp = await ss_get(url, params)
        if not isinstance(resp, dict):
            break

        items: list[dict] = []
        for entry in resp.get("data") or []:
            paper = entry.get(item_key) or {}
            if not paper.get("title"):
                continue
            # ADR-021: title에 \bsurvey\b 포함된 논문은 제외.
            if is_survey(paper.get("title")):
                continue
            # entry wrapper의 isInfluential을 paper dict로 주입 (없으면 False).
            paper["is_influential"] = bool(entry.get("isInfluential", False))
            items.append(paper)
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
    if _SHA_RE.match(rid):
        return rid, None
    # DOI 등 — paperId 매칭은 못 함. ArXiv 추정도 못 함.
    return None, None
