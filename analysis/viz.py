"""시각화 산출물 빌더 ([ADR-005](../docs/ADR.md#adr-005)).

두 가지를 동시에 만든다:
- `build_mermaid(anchor, groups, direction)` → Mermaid graph 텍스트 (Claude Desktop이 답변에서 즉시 렌더)
- `build_canvas_json(anchor, groups)` → Obsidian Canvas 1.0 spec dict (사용자가 vault에서 자유 편집)

입력 모델:
- anchor: dict — {arxiv_id, title, year, citation_count, citation_velocity?}
- groups: list of {"topic": str, "papers": list[dict]} — 동적 토픽 (ADR-009)
"""

from __future__ import annotations

# Obsidian Canvas 좌표 (px). anchor 중심, 그룹 수직 분산, 그룹 오른쪽으로 paper.
_NODE_W = 260
_NODE_H = 70
_GROUP_GAP_Y = 180
_COL_GAP_X = 360


def _mermaid_id(prefix: str, i: int) -> str:
    return f"{prefix}{i}"


def _mermaid_label(text: str) -> str:
    """Mermaid 노드 라벨용 escape. 따옴표 안전."""
    return text.replace('"', "'")


def build_mermaid(anchor: dict, groups: list[dict], direction: str = "LR") -> str:
    """anchor + 그룹별 paper로 Mermaid graph 텍스트 생성."""
    lines: list[str] = [f"graph {direction}"]

    anchor_label = _mermaid_label(
        f"{anchor.get('title', 'anchor')} "
        f"({anchor.get('year', '?')}, cited {anchor.get('citation_count', 0)})"
    )
    lines.append(f'  anchor["{anchor_label}"]')

    for gi, g in enumerate(groups):
        gid = _mermaid_id("g", gi)
        glabel = _mermaid_label(g.get("topic", f"group {gi}"))
        lines.append(f'  {gid}["{glabel}"]')
        lines.append(f"  anchor --> {gid}")
        for pi, p in enumerate(g.get("papers") or []):
            pid = _mermaid_id(f"g{gi}p", pi)
            plabel = _mermaid_label(
                f"{p.get('title', 'paper')} ({p.get('year', '?')})"
            )
            lines.append(f'  {pid}["{plabel}"]')
            lines.append(f"  {gid} --> {pid}")
    return "\n".join(lines)


def _canvas_node(nid: str, text: str, x: int, y: int) -> dict:
    return {
        "id": nid,
        "type": "text",
        "text": text,
        "x": x,
        "y": y,
        "width": _NODE_W,
        "height": _NODE_H,
    }


def _canvas_edge(eid: str, src: str, dst: str) -> dict:
    return {
        "id": eid,
        "fromNode": src,
        "toNode": dst,
        "fromSide": "right",
        "toSide": "left",
    }


def build_canvas_json(anchor: dict, groups: list[dict]) -> dict:
    """Obsidian Canvas 1.0 spec dict. JSON dump 가능."""
    nodes: list[dict] = []
    edges: list[dict] = []

    # anchor: column 0, vertical center.
    anchor_text = (
        f"# {anchor.get('title', 'anchor')}\n"
        f"arXiv:{anchor.get('arxiv_id', '')}  · {anchor.get('year', '?')}\n"
        f"cited {anchor.get('citation_count', 0)}"
    )
    if anchor.get("citation_velocity") is not None:
        anchor_text += f"  ·  vel {anchor['citation_velocity']:.1f}"
    nodes.append(_canvas_node("anchor", anchor_text, x=0, y=0))

    n_groups = len(groups)
    # 그룹을 vertically distribute. 중앙 정렬.
    first_y = -((n_groups - 1) * _GROUP_GAP_Y) // 2 if n_groups else 0

    for gi, g in enumerate(groups):
        gid = f"g{gi}"
        gy = first_y + gi * _GROUP_GAP_Y
        nodes.append(
            _canvas_node(
                gid,
                f"## {g.get('topic', f'group {gi}')}",
                x=_COL_GAP_X,
                y=gy,
            )
        )
        edges.append(_canvas_edge(f"e_anchor_{gid}", "anchor", gid))

        papers = g.get("papers") or []
        # paper들은 그룹 우측에 vertically distribute.
        n_papers = len(papers)
        first_py = gy - ((n_papers - 1) * (_NODE_H + 20)) // 2 if n_papers else gy
        for pi, p in enumerate(papers):
            pid = f"g{gi}p{pi}"
            py = first_py + pi * (_NODE_H + 20)
            ptext = (
                f"**{p.get('title', 'paper')}**\n"
                f"arXiv:{p.get('arxiv_id', '')}  · {p.get('year', '?')}\n"
                f"cited {p.get('citation_count', 0)}"
            )
            nodes.append(_canvas_node(pid, ptext, x=2 * _COL_GAP_X, y=py))
            edges.append(_canvas_edge(f"e_{gid}_{pid}", gid, pid))

    return {"nodes": nodes, "edges": edges}
