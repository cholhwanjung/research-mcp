"""citation 정렬 + 한국어 리스트 렌더.

- `render_sorted_list(papers, ..., sort='count'|'velocity', current_year)` — Phase 3.1 D-3.
- `citation_velocity(paper, current_year, bias_newcomer=False)` — [ADR-004](../docs/ADR.md#adr-004).
- `sort_by_velocity(papers, current_year, bias_newcomer=False)` — 새 리스트 반환 (input mutate 금지).
"""

from __future__ import annotations


def citation_velocity(
    paper: dict,
    current_year: int,
    bias_newcomer: bool = False,
) -> float:
    """ADR-004: citations / max(1, year_diff). bias_newcomer 시 분모에 +1."""
    cc = paper.get("citationCount")
    year = paper.get("year")
    if not cc or not year:
        return 0.0
    year_diff = current_year - year
    if bias_newcomer:
        year_diff += 1
    return cc / max(1, year_diff)


def sort_by_velocity(
    papers: list[dict],
    current_year: int,
    bias_newcomer: bool = False,
) -> list[dict]:
    """velocity 내림차순 정렬. 원본 mutate 금지 — 새 리스트 반환."""
    return sorted(
        papers,
        key=lambda p: citation_velocity(p, current_year, bias_newcomer),
        reverse=True,
    )


def _passes_velocity(p: dict, current_year: int, min_velocity: float, bias_newcomer: bool = False) -> bool:
    """ADR-014 보강: velocity 미달이라도 SS가 영향력 있다고 표시한 인용은 살림."""
    if citation_velocity(p, current_year, bias_newcomer) >= min_velocity:
        return True
    return bool(p.get("is_influential"))


def interleave_by_year(
    buckets: dict[int, list[dict]],
    current_year: int,
    min_velocity: float = 0.0,
) -> list[dict]:
    """연도 bucket마다 velocity 순 + min_velocity 필터 뒤, 연도 오름차순으로 교대(round-robin) 합침 (ADR-071).

    교대 순서라 앞부분이 뒤의 길이와 무관하게 고정된다 — `top_k`를 늘려 다시 불러도 prefix가 같다.
    """
    ranked: list[list[dict]] = []
    for year in sorted(buckets):
        ps = sort_by_velocity(buckets[year], current_year)
        if min_velocity > 0:
            ps = [p for p in ps if _passes_velocity(p, current_year, min_velocity)]
        ranked.append(ps)
    out: list[dict] = []
    for rank in range(max((len(r) for r in ranked), default=0)):
        for r in ranked:
            if rank < len(r):
                out.append(r[rank])
    return out


def render_sorted_list(
    papers: list[dict],
    header: str,
    total: int,
    fetched: int,
    top_k: int,
    sort: str = "count",
    current_year: int | None = None,
    bias_newcomer: bool = False,
    min_velocity: float = 0.0,
    preserve_order: bool = False,
) -> str:
    """sort='count'(기본)·'velocity'. velocity 모드는 vel 수치 + min_velocity 필터.

    `preserve_order=True`면 정렬·필터 없이 주어진 순서로 `top_k`까지 렌더(호출측이 이미 정렬한 경우)."""
    filtered_out = 0
    if sort == "velocity" and current_year is None:
        from datetime import datetime, timezone

        current_year = datetime.now(timezone.utc).year
    if preserve_order:
        sorted_papers = papers[:top_k]
    elif sort == "velocity":
        ranked = sort_by_velocity(papers, current_year, bias_newcomer)
        if min_velocity > 0:
            kept = [p for p in ranked if _passes_velocity(p, current_year, min_velocity, bias_newcomer)]
            filtered_out = len(ranked) - len(kept)
            ranked = kept
        sorted_papers = ranked[:top_k]
    else:
        sorted_papers = sorted(
            papers, key=lambda p: p.get("citationCount") or 0, reverse=True
        )[:top_k]

    summary = f"   전체: {total} / 수집: {fetched} / 표시: 상위 {len(sorted_papers)}편"
    if sort == "velocity":
        summary += f" (sort=velocity, year={current_year}"
        if min_velocity > 0:
            summary += f", min_velocity={min_velocity}, 필터: {filtered_out}편 제외"
        summary += ")"
    lines = [header, summary, ""]
    for i, p in enumerate(sorted_papers, 1):
        ext = p.get("externalIds") or {}
        aid = ext.get("ArXiv", "")
        url_str = f"https://arxiv.org/abs/{aid}" if aid else p.get("url", "")
        authors = p.get("authors") or []
        first = (
            authors[0].get("name", "")
            if authors and isinstance(authors[0], dict)
            else (authors[0] if authors else "-")
        )
        infl_mark = " ★" if p.get("is_influential") else ""
        line = (
            f"[{i}]{infl_mark} {p.get('title', 'Untitled')}\n"
            f"     1저자: {first}  "
            f"년도: {p.get('year', '-')}  "
            f"venue: {p.get('venue', '-')}\n"
            f"     citations: {p.get('citationCount')}  "
            f"influential: {p.get('influentialCitationCount')}"
        )
        if sort == "velocity":
            vel = citation_velocity(p, current_year, bias_newcomer)
            line += f"  velocity: {vel:.1f}"
        line += f"\n     🔗 {url_str}"
        lines.append(line)
    return "\n".join(lines)
