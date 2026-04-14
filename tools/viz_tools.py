"""MCP tool: build_citation_canvas (Phase 5, ADR-005).

anchor + 동적 토픽 groups를 받아:
1. Mermaid 텍스트 (응답에 즉시 노출, Claude Desktop이 렌더)
2. Obsidian Canvas JSON을 `vault/canvases/<slug>.canvas`에 저장
"""

from __future__ import annotations

import json

from analysis.viz import build_canvas_json as _build_canvas_json, build_mermaid as _build_mermaid
from wiki.vault import vault_root


async def build_citation_canvas(
    anchor: dict,
    groups: list[dict],
    slug: str | None = None,
    direction: str = "LR",
) -> str:
    """anchor + 토픽 그룹으로 시각화 산출. Mermaid는 응답, Canvas는 vault에 저장.

    Args:
        anchor:    `{arxiv_id, title, year, citation_count, citation_velocity?}`.
        groups:    `[{"topic": str, "papers": [{arxiv_id, title, year, citation_count}, ...]}]`.
        slug:      `vault/canvases/<slug>.canvas` 파일명. 비우면 `anchor.arxiv_id` 사용.
        direction: Mermaid 방향 ("LR" 기본, "TD"·"RL"·"BT" 가능).
    """
    final_slug = slug or anchor.get("arxiv_id") or "canvas"
    canvas_data = _build_canvas_json(anchor, groups)
    mermaid = _build_mermaid(anchor, groups, direction=direction)

    canvas_dir = vault_root() / "canvases"
    canvas_dir.mkdir(parents=True, exist_ok=True)
    canvas_path = canvas_dir / f"{final_slug}.canvas"
    canvas_path.write_text(
        json.dumps(canvas_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return (
        f"🗺️ Canvas 저장: canvases/{final_slug}.canvas "
        f"(nodes={len(canvas_data['nodes'])}, edges={len(canvas_data['edges'])})\n\n"
        f"```mermaid\n{mermaid}\n```"
    )


def register(mcp) -> None:
    mcp.tool()(build_citation_canvas)
