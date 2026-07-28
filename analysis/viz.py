"""시각화 산출물 빌더.

방향: **references → anchor → citations** (인과 흐름).

`build_mermaid(anchor, ref_groups, cite_groups, direction)` → Mermaid graph 텍스트.
Mermaid는 auto-layout이라 좌표를 직접 계산하지 않는다 (노드·엣지 관계만 정의).

입력 모델:
- anchor: dict — {arxiv_id, title, year, citation_count, citation_velocity?}
- ref_groups / cite_groups: list of {"topic": str, "papers": list[dict]} — 동적 토픽.
  ref_groups의 paper는 anchor가 *인용한* 논문, cite_groups의 paper는 anchor를 *인용한* 논문.
"""

from __future__ import annotations

from analysis.network import sanitize_node_id


def _mermaid_label(text: str) -> str:
    """Mermaid 노드 라벨용 escape."""
    return text.replace('"', "'")


def _paper_label(p: dict) -> str:
    return _mermaid_label(f"{p.get('title', 'paper')} ({p.get('year', '?')})")


def _paper_node_id(p: dict, fallback: str) -> str:
    """arxiv_id 기반 안정 노드 ID — 실행 간 동일 논문이 같은 ID (ADR-031).

    arxiv_id가 없으면 순번 fallback (기존 동작 보전).
    """
    aid = str(p.get("arxiv_id") or "").strip()
    return sanitize_node_id(aid) if aid else fallback


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
            pid = _paper_node_id(p, f"r{gi}p{pi}")
            lines.append(f'  {pid}["{_paper_label(p)}"]')
            lines.append(f"  {pid} --> {gid}")

    # citations: anchor → group → paper
    for gi, g in enumerate(cite_groups):
        gid = f"c{gi}"
        glabel = _mermaid_label(g.get("topic", f"cites {gi}"))
        lines.append(f'  {gid}["{glabel}"]')
        lines.append(f"  anchor --> {gid}")
        for pi, p in enumerate(g.get("papers") or []):
            pid = _paper_node_id(p, f"c{gi}p{pi}")
            lines.append(f'  {pid}["{_paper_label(p)}"]')
            lines.append(f"  {gid} --> {pid}")

    return "\n".join(lines)
