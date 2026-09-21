"""이름 → arXiv ID. vault 제목 → arXiv 검색(정규화한 제목·약칭 일치) → 매칭 판정 순.

제목이 뜻으로만 같을 때(표기·부제 차이)는 판정 에이전트가 후보 중에서만 고른다. 검색 일시 장애는 ToolFailure로
올려 호출측이 '못 찾음'과 구분하게 한다.
"""

from __future__ import annotations

from agent.autopilot.citations import short_title
from agent.autopilot.sources import ArxivHit
from agent.autopilot.vaultlinks import normalize_name, vault_papers


def vault_paper_by_name(name: str) -> tuple[str, str, str] | None:
    """(slug, 제목, arXiv ID) — 제목·약칭·slug가 정규화해서 같은 vault 논문."""
    wanted = normalize_name(name)
    if not wanted:
        return None
    for slug, title, arxiv_id in vault_papers():
        if arxiv_id and wanted in {normalize_name(title), normalize_name(short_title(title)), normalize_name(slug)}:
            return slug, title, arxiv_id
    return None


def vault_arxiv_by_name(name: str) -> str | None:
    found = vault_paper_by_name(name)
    return found[2] if found else None


async def resolve_hit(deps, name: str, context: str = "") -> ArxivHit | None:
    search = getattr(deps, "search", None)
    if search is None:
        return None
    hits = [h for h in await search(name, max_results=5) if h.arxiv_id]
    wanted = normalize_name(name)
    for hit in hits:
        if normalize_name(hit.title) == wanted or normalize_name(short_title(hit.title)) == wanted:
            return hit
    matcher = getattr(deps, "match_title", None)
    if matcher is not None and hits:
        chosen = await matcher(name, context, hits)
        return next((h for h in hits if h.arxiv_id == chosen), None)
    return None


async def resolve_name(deps, name: str, context: str = "") -> str | None:
    hit = await resolve_hit(deps, name, context)
    return hit.arxiv_id if hit else None
