"""MCP tools: get_references_by_citations, get_citations_by_citations.

D-3 (Phase 3.1):
- 기본 `max_fetch=200`로 lazy growth — 첫 호출 부하 완화.
- `sort='count'|'velocity'` 옵션 — velocity는 ADR-004.
ADR-071: `get_citations_by_citations` 기본은 연도별 층화 + 잘린 연도 OpenAlex 보강.
"""

from __future__ import annotations

from analysis.ranking import render_sorted_list as _render_sorted_list
from analysis.ranking import interleave_by_year as _interleave_by_year
from core.filter import is_survey as _is_survey
from sources.openalex import (
    resolve_work_id as _oa_resolve_work_id,
    top_citing_by_year as _oa_top_citing_by_year,
)
from sources.semantic_scholar import (
    SS_BASE,
    fetch_citations_by_month as _fetch_citations_by_month,
    fetch_citations_by_year as _fetch_citations_by_year,
    fetch_network_papers as _fetch_network_papers,
    lookup_error_message as _lookup_error_message,
    get_contexts as _get_contexts,
    resolve_id as _resolve_id,
    ss_get as _ss_get,
)


async def get_references_by_citations(
    paper_id: str,
    top_k: int = 20,
    max_fetch: int = 500,
    sort: str = "velocity",
    current_year: int | None = None,
    min_velocity: float = 10.0,
) -> str:
    """논문이 참조(reference)한 논문들을 정렬해 반환합니다.

    Args:
        paper_id:     arXiv ID (예: "2301.12597"), DOI, 또는 Semantic Scholar ID.
        top_k:        반환할 상위 논문 수 (기본 20).
        max_fetch:    최대 수집 reference 수 (기본 500). 대부분 논문은 references가 100 이내라
                      한 번에 다 가져온다.
        sort:         "velocity"(기본, ADR-004) 또는 "count"(인용수 순).
        current_year: velocity 계산 기준 연도. None이면 현재.
        min_velocity: velocity 모드일 때 최소 velocity 임계값 (기본 10).
                      신생 인용수 낮은 노이즈 논문을 제거한다.
    """
    detail = await _ss_get(
        f"{SS_BASE}/{_resolve_id(paper_id)}",
        {"fields": "paperId,title,referenceCount"},
    )
    err = _lookup_error_message(paper_id, detail)
    if err:
        return err

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
        min_velocity=min_velocity,
    )


async def get_citations_by_citations(
    paper_id: str,
    top_k: int = 20,
    max_fetch: int = 1000,
    sort: str = "velocity",
    current_year: int | None = None,
    min_velocity: float = 10.0,
    exclude_recent_year: bool = True,
    stratify: bool = True,
) -> str:
    """논문을 인용(citation)한 후속 연구들을 시기별로 균등하게 정렬해 반환합니다.

    SS citations endpoint는 **publicationDate 내림차순**으로 응답한다. 인기 논문(연 인용 1,000건
    초과)은 한 번에 `max_fetch`를 자르면 가장 최근 몇 달만 남아 2~3년 전 주요 후속작이 빠진다
    (LoRA 실측: 1,000편 전부 2025년). 기본(`stratify=True`)은 anchor 출판연도부터 기준연도까지
    **연도마다** 받아 velocity 순으로 정리한 뒤 연도 교대로 상위를 뽑는다 — 앞부분은 `top_k`와
    무관하게 고정된다. 한 해가 `max_fetch`로 잘렸으면 월별 `YYYY-MM` 12회로 다시 받아 교체하고
    (ADR-072), 월도 잘리면 OpenAlex의 그 해 인용수 상위를 SS에서 DOI로 되찾아 합집합으로 섞는다
    (ADR-071). 응답 끝의 `year=… fetched=… truncated=… openalex_added=… split=none|month` 줄이
    연도별 커버리지다.

    `exclude_recent_year=True`이면 가장 최근 1년(기준연도)을 제외 — velocity ≥ 10 같은 임계값과
    정합 (신생 1년 미만은 누적 인용 시간 부족).

    Args:
        paper_id:            arXiv ID (예: "2304.08485"), DOI, 또는 Semantic Scholar ID.
        top_k:               반환할 상위 논문 수 (기본 20).
        max_fetch:           연도별·월별(층화) 또는 전체(비층화) 최대 수집 citation 수 (기본 1000).
        sort:                "velocity"(기본, ADR-004) 또는 "count". 층화 모드는 velocity 고정.
        current_year:        velocity·연도 범위 기준 연도. None이면 현재.
        min_velocity:        velocity 모드일 때 최소 velocity (기본 10). 층화 모드는 연도별 적용.
        exclude_recent_year: True면 기준연도(가장 최근 1년)를 제외 (기본 True).
        stratify:            False면 예전처럼 한 번에 `max_fetch`만 받는다(anchor 출판연도를 모를 때도 이 경로).
    """
    from datetime import datetime, timezone

    detail = await _ss_get(
        f"{SS_BASE}/{_resolve_id(paper_id)}",
        {"fields": "paperId,title,citationCount,year,externalIds"},
    )
    err = _lookup_error_message(paper_id, detail)
    if err:
        return err

    pid = detail["paperId"]
    paper_title = detail.get("title", paper_id)
    total = detail.get("citationCount", 0)

    if current_year is None:
        current_year = datetime.now(timezone.utc).year
    end_year = current_year - 1 if exclude_recent_year else current_year
    anchor_year = detail.get("year")

    if stratify and anchor_year and anchor_year <= end_year:
        return await _citations_stratified(
            detail, pid, paper_title, total, list(range(anchor_year, end_year + 1)),
            top_k, max_fetch, current_year, min_velocity,
        )

    pub_date_filter = f":{end_year}" if exclude_recent_year else None
    cits = await _fetch_network_papers(
        pid,
        "citations",
        "citingPaper",
        max_fetch=max_fetch,
        publication_date_or_year=pub_date_filter,
    )

    if not cits:
        # 도구 실패가 아니라 0건이다 — 호출자(autopilot 워커 등)가 실패로 오판하지 않게
        # SS 인용수·적용된 필터·재시도 힌트를 함께 낸다.
        if total == 0:
            return f"'{paper_title}' — 인용 논문 0건 (SS citationCount=0)."
        filters = ["survey 제외"]
        if pub_date_filter:
            filters.insert(0, f"최근 1년 제외(publicationDateOrYear={pub_date_filter})")
            hint = "exclude_recent_year=False로 다시 부르면 최근 1년 인용이 포함된다"
        else:
            hint = "SS 인용 색인 지연이 유력 — 나중에 다시 시도"
        return (
            f"'{paper_title}' — 인용 논문 0건 반환 (SS citationCount={total}). "
            f"{' · '.join(filters)} 후 남은 것이 없거나 SS 인용 색인 지연. 도구 실패가 아니다. {hint}."
        )

    header_suffix = "velocity 순" if sort == "velocity" else "인용수 순"
    return _render_sorted_list(
        cits,
        f"📥 '{paper_title}' — Citation 논문 ({header_suffix} 정렬)",
        total,
        len(cits),
        top_k,
        sort=sort,
        current_year=current_year,
        min_velocity=min_velocity,
    )


OPENALEX_TOP_PER_YEAR = 10  # 잘린 연도마다 OpenAlex에서 확인할 인용수 상위 수


def _paper_keys(p: dict) -> set[str]:
    ext = p.get("externalIds") or {}
    keys = {k for k in (p.get("paperId"), ext.get("ArXiv"), ext.get("DOI")) if k}
    return {str(k).lower() for k in keys}


async def _openalex_fill(detail: dict, year: int, bucket: list[dict], work_id: str | None) -> int:
    """잘린 `year` bucket에 OpenAlex 인용수 상위를 SS로 되찾아(DOI) 합집합으로 추가. 추가된 수를 돌려준다."""
    if not work_id:
        return 0
    present: set[str] = set()
    for p in bucket:
        present |= _paper_keys(p)
    added = 0
    for w in await _oa_top_citing_by_year(work_id, year, limit=OPENALEX_TOP_PER_YEAR):
        doi = w.get("doi")
        if not doi or doi.lower() in present:
            continue
        if _is_survey(w.get("title")):  # ADR-021 survey 제외는 보강분에도 — SS 되찾기 전에 걸러 호출을 아낀다
            continue
        found = await _ss_get(
            f"{SS_BASE}/DOI:{doi}",
            {"fields": "paperId,title,year,citationCount,externalIds"},
        )
        if not isinstance(found, dict) or not found.get("paperId") or not found.get("title"):
            continue
        keys = _paper_keys(found) | {doi.lower()}
        if keys & present:
            continue
        found.setdefault("is_influential", False)
        found["source"] = "openalex"
        bucket.append(found)
        present |= keys
        added += 1
    return added


async def _citations_stratified(
    detail: dict, pid: str, paper_title: str, total: int, years: list[int],
    top_k: int, max_fetch: int, current_year: int, min_velocity: float,
) -> str:
    raw = await _fetch_citations_by_year(pid, years, max_fetch_per_year=max_fetch)
    buckets: dict[int, list[dict]] = {}
    truncated: dict[int, bool] = {}
    split: dict[int, str] = {}
    for y in years:
        ps, t = raw[y]
        if t:
            # 연 1,000건 초과(또는 응답 실패)로 잘린 해는 월별로 다시 받아 교체 — 월은 보통 1,000건 아래 (ADR-072)
            ps, t = await _fetch_citations_by_month(pid, y, max_fetch_per_month=max_fetch)
            split[y] = "month"
        buckets[y], truncated[y] = list(ps), t
    fetched_ss = sum(len(ps) for ps in buckets.values())
    coverage: list[str] = []

    work_id: str | None = None
    if any(truncated.values()):
        ext = detail.get("externalIds") or {}
        work_id = await _oa_resolve_work_id(arxiv_id=ext.get("ArXiv"), doi=ext.get("DOI"))

    for y in years:
        ss_n = len(buckets[y])
        added = await _openalex_fill(detail, y, buckets[y], work_id) if truncated[y] else 0
        coverage.append(
            f"   year={y} fetched={ss_n} truncated={'true' if truncated[y] else 'false'} "
            f"openalex_added={added} split={split.get(y, 'none')}"
        )

    merged = _interleave_by_year(buckets, current_year, min_velocity)
    if not merged:
        if total == 0:
            return f"'{paper_title}' — 인용 논문 0건 (SS citationCount=0)."
        return (
            f"'{paper_title}' — 인용 논문 0건 반환 (SS citationCount={total}). "
            f"연도 {years[0]}~{years[-1]} · survey 제외 · min_velocity={min_velocity} 후 남은 것이 없거나 "
            f"SS 인용 색인 지연. 도구 실패가 아니다. exclude_recent_year=False 또는 min_velocity=0으로 다시 불러 본다."
        )

    body = _render_sorted_list(
        merged,
        f"📥 '{paper_title}' — Citation 논문 (연도 교대 · 연도별 velocity 순 정렬)",
        total,
        fetched_ss + sum(1 for ps in buckets.values() for p in ps if p.get("source") == "openalex"),
        top_k,
        sort="velocity",
        current_year=current_year,
        preserve_order=True,
    )
    head, _, rest = body.partition("\n\n")
    strat = f"   층화: years={years[0]}-{years[-1]} min_velocity={min_velocity} (연도별 적용) 후보={len(merged)}"
    return "\n".join([head, strat, *coverage, "", rest])


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
