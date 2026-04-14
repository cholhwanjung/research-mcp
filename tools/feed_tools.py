"""MCP tool: get_hf_daily_papers (Phase 4, ADR-006).

ARCHITECTURE §3.1 fetch 카테고리. `daily-digest` 스킬의 입력 소스.

GeekNews는 endpoint가 default-UA 차단/지속 403을 반환 → Phase 4 후속 결정으로 제외.
"""

from __future__ import annotations

from sources.hf_daily import fetch_daily_papers as _fetch_hf


async def get_hf_daily_papers(date: str | None = None, limit: int = 10) -> str:
    """Hugging Face Daily Papers를 받아 인기 순으로 반환합니다 (ADR-006 fallback chain).

    Args:
        date:  YYYY-MM-DD. 비우면 오늘(UTC).
        limit: 상위 N개 (기본 10).
    """
    papers = await _fetch_hf(date=date, limit=limit)
    if not papers:
        return f"❌ HF Daily Papers 결과 없음 (date={date or 'today'})"

    lines = [f"🤗 HF Daily Papers ({date or 'today'}) — {len(papers)}편"]
    for i, p in enumerate(papers, 1):
        title = p.get("title") or p.get("arxiv_id", "Untitled")
        aid = p.get("arxiv_id", "")
        upv = p.get("upvotes", 0)
        authors = p.get("authors") or []
        first = authors[0] if authors else "-"
        lines.append(
            f"[{i}] {title}"
            f"\n     arXiv: {aid}  👍 {upv}  1저자: {first}"
            f"\n     🔗 {p.get('url', '')}"
        )
    return "\n".join(lines)


def register(mcp) -> None:
    mcp.tool()(get_hf_daily_papers)
