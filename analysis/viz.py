"""시각화 산출물 빌더 ([ADR-005](../docs/ADR.md#adr-005)).

방향: **references → anchor → citations** (인과 흐름).

두 가지를 동시에 만든다:
- `build_mermaid(anchor, ref_groups, cite_groups, direction)` → Mermaid graph 텍스트
- `build_canvas_json(anchor, ref_groups, cite_groups)` → Obsidian Canvas 1.0 spec dict

입력 모델:
- anchor: dict — {arxiv_id, title, year, citation_count, citation_velocity?}
- ref_groups / cite_groups: list of {"topic": str, "papers": list[dict]} — 동적 토픽 (ADR-009).
  ref_groups의 paper는 anchor가 *인용한* 논문, cite_groups의 paper는 anchor를 *인용한* 논문.
"""

from __future__ import annotations

# Obsidian Canvas 좌표 (px). anchor 중앙 (x=0), refs 왼쪽 (음수), cites 오른쪽 (양수).
_NODE_W = 300
_NODE_H = 100          # 3줄(제목·arXiv·cited)이 잘리지 않도록 상향
_PAPER_V_GAP = 24      # 한 그룹 안 논문 노드 사이 세로 간격
_GROUP_PAD = 60        # 그룹 레인 사이 여백
_COL_GAP_X = 400


def _mermaid_label(text: str) -> str:
    """Mermaid 노드 라벨용 escape."""
    return text.replace('"', "'")


def _paper_label(p: dict) -> str:
    return _mermaid_label(f"{p.get('title', 'paper')} ({p.get('year', '?')})")


def build_mermaid(
    anchor: dict,
    ref_groups: list[dict],
    cite_groups: list[dict],
    direction: str = "LR",
) -> str:
    """anchor를 중심으로 ref_groups → anchor → cite_groups 흐름의 Mermaid graph."""
    lines: list[str] = [f"graph {direction}"]

    anchor_label = _mermaid_label(
        f"{anchor.get('title', 'anchor')} "
        f"({anchor.get('year', '?')}, cited {anchor.get('citation_count', 0)})"
    )
    lines.append(f'  anchor["{anchor_label}"]')

    # references: paper → group → anchor
    for gi, g in enumerate(ref_groups):
        gid = f"r{gi}"
        glabel = _mermaid_label(g.get("topic", f"refs {gi}"))
        lines.append(f'  {gid}["{glabel}"]')
        lines.append(f"  {gid} --> anchor")
        for pi, p in enumerate(g.get("papers") or []):
            pid = f"r{gi}p{pi}"
            lines.append(f'  {pid}["{_paper_label(p)}"]')
            lines.append(f"  {pid} --> {gid}")

    # citations: anchor → group → paper
    for gi, g in enumerate(cite_groups):
        gid = f"c{gi}"
        glabel = _mermaid_label(g.get("topic", f"cites {gi}"))
        lines.append(f'  {gid}["{glabel}"]')
        lines.append(f"  anchor --> {gid}")
        for pi, p in enumerate(g.get("papers") or []):
            pid = f"c{gi}p{pi}"
            lines.append(f'  {pid}["{_paper_label(p)}"]')
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


def _paper_text(p: dict) -> str:
    return (
        f"**{p.get('title', 'paper')}**\n"
        f"arXiv:{p.get('arxiv_id', '')}  · {p.get('year', '?')}\n"
        f"cited {p.get('citation_count', 0)}"
    )


def _papers_block_height(n_papers: int) -> int:
    """n개 논문 노드가 세로로 차지하는 총 높이."""
    if n_papers <= 0:
        return 0
    return n_papers * _NODE_H + (n_papers - 1) * _PAPER_V_GAP


def _place_side(
    groups: list[dict],
    side: str,
    nodes: list[dict],
    edges: list[dict],
) -> None:
    """한 쪽(refs=left, cites=right)의 그룹·논문 노드와 엣지 추가.

    refs 면 edge 방향은 paper → group → anchor.
    cites 면 anchor → group → paper.

    배치: 각 그룹은 자기 논문 수에 맞는 세로 레인을 독점하고, 레인을 위→아래로
    누적 배치한다(고정 간격 X). 레인 높이 = max(노드높이, 논문블록높이)이므로
    같은 컬럼에서 논문끼리도, 인접 그룹끼리도 겹치지 않는다. 전체는 y=0 중심 정렬.
    """
    is_ref = side == "ref"
    sign = -1 if is_ref else 1
    prefix = "r" if is_ref else "c"
    group_x = sign * _COL_GAP_X
    paper_x = sign * 2 * _COL_GAP_X

    lane_heights = [
        max(_NODE_H, _papers_block_height(len(g.get("papers") or []))) for g in groups
    ]
    total_h = sum(lane_heights) + max(0, len(groups) - 1) * _GROUP_PAD
    cursor = -total_h // 2

    for gi, g in enumerate(groups):
        gid = f"{prefix}{gi}"
        lane_h = lane_heights[gi]
        group_cy = cursor + lane_h // 2
        gy = group_cy - _NODE_H // 2
        nodes.append(_canvas_node(gid, f"## {g.get('topic', f'{prefix} {gi}')}", x=group_x, y=gy))
        if is_ref:
            edges.append(_canvas_edge(f"e_{gid}_anchor", gid, "anchor"))
        else:
            edges.append(_canvas_edge(f"e_anchor_{gid}", "anchor", gid))

        papers = g.get("papers") or []
        block_h = _papers_block_height(len(papers))
        first_py = group_cy - block_h // 2
        for pi, p in enumerate(papers):
            pid = f"{gid}p{pi}"
            py = first_py + pi * (_NODE_H + _PAPER_V_GAP)
            nodes.append(_canvas_node(pid, _paper_text(p), x=paper_x, y=py))
            if is_ref:
                edges.append(_canvas_edge(f"e_{pid}_{gid}", pid, gid))
            else:
                edges.append(_canvas_edge(f"e_{gid}_{pid}", gid, pid))

        cursor += lane_h + _GROUP_PAD


def build_canvas_json(
    anchor: dict,
    ref_groups: list[dict],
    cite_groups: list[dict],
) -> dict:
    """Obsidian Canvas 1.0 spec dict. anchor 중앙, refs 왼쪽, cites 오른쪽."""
    nodes: list[dict] = []
    edges: list[dict] = []

    anchor_text = (
        f"# {anchor.get('title', 'anchor')}\n"
        f"arXiv:{anchor.get('arxiv_id', '')}  · {anchor.get('year', '?')}\n"
        f"cited {anchor.get('citation_count', 0)}"
    )
    if anchor.get("citation_velocity") is not None:
        anchor_text += f"  ·  vel {anchor['citation_velocity']:.1f}"
    nodes.append(_canvas_node("anchor", anchor_text, x=0, y=0))

    _place_side(ref_groups, "ref", nodes, edges)
    _place_side(cite_groups, "cite", nodes, edges)

    return {"nodes": nodes, "edges": edges}
