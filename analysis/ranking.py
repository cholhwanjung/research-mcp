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
) -> str:
    """sort='count'(기본)·'velocity'. velocity 모드는 vel 수치 + min_velocity 필터."""
    filtered_out = 0
    if sort == "velocity":
        if current_year is None:
            from datetime import datetime, timezone

            current_year = datetime.now(timezone.utc).year
        ranked = sort_by_velocity(papers, current_year, bias_newcomer)
        if min_velocity > 0:
            # ADR-014 보강: velocity 미달이라도 SS가 영향력 있다고 표시한 인용은 살림.
            def _keep(p: dict) -> bool:
                if citation_velocity(p, current_year, bias_newcomer) >= min_velocity:
                    return True
                return bool(p.get("is_influential"))
            kept = [p for p in ranked if _keep(p)]
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
