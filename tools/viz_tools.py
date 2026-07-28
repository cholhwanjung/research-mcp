"""MCP tools: build_citation_graph (Phase 5) + export_citation_network (ADR-031).

- build_citation_graph: anchor 1편 중심 Mermaid → 응답 + `graphs/<slug>.md`.
- export_citation_network: vault 전체 frontmatter 스캔 → 통합 네트워크를
  CSV(Cosmograph)/GEXF(Gephi Lite)로 export. 엣지 임계 이하면 `graphs/unified.md`
  Mermaid도 산출 (2단 렌더러).
"""

from __future__ import annotations

import re

from analysis import network as _network
from analysis.viz import build_mermaid as _build_mermaid
from wiki.frontmatter import dump_note
from wiki.vault import read_paper_frontmatters, vault_root


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


async def export_citation_network(format: str = "csv", scope: str = "vault") -> str:
    """vault 전체 논문 노트의 인용 관계를 통합 네트워크로 export합니다 (ADR 데이터는
    frontmatter가 단일 소스 — 별도 저장소 없이 매번 재구성).

    산출:
    - format="csv"(기본): `graphs/network.csv`(엣지) + `graphs/network-nodes.csv`(노드).
      Cosmograph(https://cosmograph.app/run/)에 두 파일을 올리면 렌더.
    - format="gexf": `graphs/network.gexf` — Gephi / Gephi Lite용.
    - 전역 엣지 수가 임계(200) 이하면 `graphs/unified.md`(Mermaid)도 함께 저장.

    Args:
        format: "csv"(기본) 또는 "gexf".
        scope:  "vault"(기본, 전체) 또는 hub slug — 해당 hub에 태깅된 논문만.
    """
    if format not in ("csv", "gexf"):
        return f'❌ 지원하지 않는 format: {format} ("csv" | "gexf")'

    papers = read_paper_frontmatters()
    if not papers:
        return "❌ vault에 논문 노트가 없습니다 (papers/ 비어 있음). 먼저 paper-ingest를 실행하세요."

    nodes, edges = _network.build_network(papers)
    suffix = ""
    if scope != "vault":
        nodes, edges = _network.filter_by_hub(nodes, edges, scope)
        if not nodes:
            return f"❌ hub '{scope}'에 태깅된 논문이 없습니다. wiki_list_hubs로 hub slug를 확인하세요."
        suffix = "-" + re.sub(r"[^0-9A-Za-z_-]", "-", scope)

    graphs_dir = vault_root() / "graphs"
    graphs_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    if format == "csv":
        nodes_csv, edges_csv = _network.to_csv(nodes, edges)
        (graphs_dir / f"network{suffix}.csv").write_text(edges_csv, encoding="utf-8")
        (graphs_dir / f"network{suffix}-nodes.csv").write_text(nodes_csv, encoding="utf-8")
        written += [f"graphs/network{suffix}.csv", f"graphs/network{suffix}-nodes.csv"]
        viewer = "Cosmograph(https://cosmograph.app/run/)에 엣지 CSV + 노드 CSV를 업로드하면 렌더됩니다."
    else:
        (graphs_dir / f"network{suffix}.gexf").write_text(
            _network.to_gexf(nodes, edges), encoding="utf-8"
        )
        written.append(f"graphs/network{suffix}.gexf")
        viewer = "Gephi Lite(https://gephi.org/gephi-lite/)에서 GEXF를 열면 렌더됩니다."

    mermaid_note = ""
    if len(edges) <= _network.MERMAID_EDGE_LIMIT:
        mermaid = _network.build_network_mermaid(nodes, edges)
        body = f"# 통합 인용 네트워크\n\n```mermaid\n{mermaid}\n```\n"
        unified = graphs_dir / f"unified{suffix}.md"
        unified.write_text(dump_note({"title": "통합 인용 네트워크"}, body), encoding="utf-8")
        written.append(f"graphs/unified{suffix}.md")
        mermaid_note = " (Mermaid 노트 포함 — 옵시디언에서 렌더)"
    else:
        mermaid_note = f" (엣지 {len(edges)} > {_network.MERMAID_EDGE_LIMIT} — Mermaid 생략, 외부 뷰어 사용)"

    n_papers = sum(1 for n in nodes if n["role"] != "hub")
    n_hubs = len(nodes) - n_papers
    return (
        f"🕸️ 통합 인용 네트워크 export 완료 (scope={scope})\n"
        f"   논문 {n_papers} · hub {n_hubs} · 엣지 {len(edges)}{mermaid_note}\n"
        f"   파일: {', '.join(written)}\n"
        f"   → {viewer}"
    )


def register(mcp) -> None:
    mcp.tool()(build_citation_graph)
    mcp.tool()(export_citation_network)
