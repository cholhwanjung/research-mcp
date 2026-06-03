"""MCP tool: build_citation_graph (Phase 5).

anchor + (ref_groups, cite_groups) → references → anchor → citations 흐름:
1. Mermaid 텍스트 (응답에 즉시 노출, Claude Desktop이 렌더)
2. 같은 Mermaid를 담은 노트를 `vault/graphs/<slug>.md`에 저장 → 옵시디언이 렌더.
   Mermaid는 auto-layout이라 노드가 겹치지 않는다.
"""

from __future__ import annotations

from analysis.viz import build_mermaid as _build_mermaid
from wiki.frontmatter import dump_note
from wiki.vault import vault_root


async def build_citation_graph(
    anchor: dict,
    ref_groups: list[dict],
    cite_groups: list[dict],
    slug: str | None = None,
    direction: str = "LR",
) -> str:
    """anchor + 토픽 그룹으로 인용 흐름 그래프 산출. Mermaid는 응답 + vault 노트에 저장.

    방향: references → anchor → citations (인과 흐름).

    Args:
        anchor:      `{arxiv_id, title, year, citation_count, citation_velocity?}`.
        ref_groups:  anchor가 *인용한* 논문들의 동적 토픽 그룹.
                     `[{"topic": str, "papers": [{arxiv_id, title, year, citation_count}, ...]}]`.
        cite_groups: anchor를 *인용한* 논문들의 동적 토픽 그룹. 동일 스키마.
        slug:        `vault/graphs/<slug>.md` 파일명. 비우면 `anchor.arxiv_id` 사용.
        direction:   Mermaid 방향 ("LR" 기본, "TD"·"RL"·"BT" 가능).
    """
    final_slug = slug or anchor.get("arxiv_id") or "graph"
    mermaid = _build_mermaid(anchor, ref_groups, cite_groups, direction=direction)

    title = anchor.get("title", "anchor")
    frontmatter = {"title": f"인용 흐름 — {title}", "anchor": anchor.get("arxiv_id", "")}
    body = f"# 인용 흐름: {title}\n\n```mermaid\n{mermaid}\n```\n"

    graphs_dir = vault_root() / "graphs"
    graphs_dir.mkdir(parents=True, exist_ok=True)
    graph_path = graphs_dir / f"{final_slug}.md"
    graph_path.write_text(dump_note(frontmatter, body), encoding="utf-8")

    return (
        f"🗺️ 그래프 저장: graphs/{final_slug}.md (옵시디언에서 렌더)\n\n"
        f"```mermaid\n{mermaid}\n```"
    )


def register(mcp) -> None:
    mcp.tool()(build_citation_graph)
