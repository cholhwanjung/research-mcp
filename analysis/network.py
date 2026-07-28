"""통합 인용 네트워크 빌더 + 직렬화 (ADR-031). 순수 함수 — vault I/O 없음.

입력: paper frontmatter dict 리스트 (호출측 tools/viz_tools.py가 vault 스캔).
엣지 의미론: paper-paper 엣지는 항상 **source가 target에게 인용됨** (지식 흐름).
- anchor.references[]  → (ref → anchor)
- anchor.cited_by[]    → (anchor → citing)
같은 관계가 양쪽 노트에 기록될 수 있으므로 (source, target) 기준 dedup — kind는
"cites" 하나로 통일한다. paper→hub 소속 엣지는 kind="hub".

노드 role: anchor(vault에 노트 존재) > neighbor(엣지 항목에만 등장) / hub.
"""

from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET

MERMAID_EDGE_LIMIT = 200  # 초과 시 통합 Mermaid 생략 (Obsidian maxEdges 여유분)

_ID_SAFE_RE = re.compile(r"[^0-9A-Za-z_]")


def sanitize_node_id(paper_id: str) -> str:
    """paper_id → Mermaid-safe 안정 노드 ID. 예: '2301.12597' → 'p2301_12597'."""
    return "p" + _ID_SAFE_RE.sub("_", paper_id.strip())


def _hub_node_id(slug: str) -> str:
    return "hub_" + _ID_SAFE_RE.sub("_", slug.strip())


def build_network(papers: list[dict]) -> tuple[list[dict], list[dict]]:
    """frontmatter dict 리스트 → (nodes, edges).

    nodes: {id, title, year, citation_count, role: anchor|neighbor|hub, hubs: [slug]}
    edges: {source, target, kind: cites|hub} — (source, target) 기준 dedup.
    """
    nodes: dict[str, dict] = {}
    hub_slugs: list[str] = []
    edges: list[dict] = []
    seen_edges: set[tuple[str, str]] = set()

    def ensure_paper(
        pid: str,
        *,
        title: str = "",
        year=None,
        citation_count=None,
        role: str = "neighbor",
        hubs: list[str] | None = None,
    ) -> None:
        n = nodes.get(pid)
        if n is None:
            nodes[pid] = {
                "id": pid,
                "title": title,
                "year": year,
                "citation_count": citation_count,
                "role": role,
                "hubs": list(hubs or []),
            }
            return
        if title and not n["title"]:
            n["title"] = title
        if year is not None and n["year"] is None:
            n["year"] = year
        if citation_count is not None and n["citation_count"] is None:
            n["citation_count"] = citation_count
        if role == "anchor":
            n["role"] = "anchor"
        for h in hubs or []:
            if h not in n["hubs"]:
                n["hubs"].append(h)

    def add_edge(source: str, target: str, kind: str) -> None:
        key = (source, target)
        if key in seen_edges:
            return
        seen_edges.add(key)
        edges.append({"source": source, "target": target, "kind": kind})

    def ensure_hub(slug: str) -> None:
        if slug not in hub_slugs:
            hub_slugs.append(slug)

    for p in papers:
        pid = str(p.get("arxiv_id") or p.get("ss_paper_id") or p.get("slug") or "").strip()
        if not pid:
            continue
        topics = [str(t).strip() for t in (p.get("topics") or []) if str(t).strip()]
        ensure_paper(
            pid,
            title=str(p.get("title") or ""),
            year=p.get("year"),
            citation_count=p.get("citation_count"),
            role="anchor",
            hubs=topics,
        )
        for t in topics:
            ensure_hub(t)
            add_edge(pid, t, "hub")
        for e in p.get("references") or []:
            rid = str(e.get("paper_id") or "").strip()
            if not rid:
                continue
            ehubs = [str(h).strip() for h in (e.get("hubs") or []) if str(h).strip()]
            ensure_paper(rid, hubs=ehubs)
            add_edge(rid, pid, "cites")
            for h in ehubs:
                ensure_hub(h)
                add_edge(rid, h, "hub")
        for e in p.get("cited_by") or []:
            cid = str(e.get("paper_id") or "").strip()
            if not cid:
                continue
            ehubs = [str(h).strip() for h in (e.get("hubs") or []) if str(h).strip()]
            ensure_paper(cid, hubs=ehubs)
            add_edge(pid, cid, "cites")
            for h in ehubs:
                ensure_hub(h)
                add_edge(cid, h, "hub")

    node_list = list(nodes.values()) + [
        {"id": h, "title": h, "year": None, "citation_count": None, "role": "hub", "hubs": []}
        for h in hub_slugs
    ]
    if not node_list:
        return [], []
    return node_list, edges


def filter_by_hub(
    nodes: list[dict], edges: list[dict], hub_slug: str
) -> tuple[list[dict], list[dict]]:
    """hub에 태깅된 논문 + 그 hub 노드만 남긴다. cites 엣지는 양끝 모두 남을 때만."""
    kept_papers = {n["id"] for n in nodes if n["role"] != "hub" and hub_slug in n["hubs"]}
    kept_ids = kept_papers | {hub_slug}
    f_nodes = [n for n in nodes if n["id"] in kept_ids]
    f_edges = [
        e
        for e in edges
        if (e["kind"] == "cites" and e["source"] in kept_papers and e["target"] in kept_papers)
        or (e["kind"] == "hub" and e["source"] in kept_papers and e["target"] == hub_slug)
    ]
    return f_nodes, f_edges


# ---------- 직렬화 ----------

_NODE_COLUMNS = ("id", "title", "year", "citation_count", "role", "hubs")


def to_csv(nodes: list[dict], edges: list[dict]) -> tuple[str, str]:
    """(nodes_csv, edges_csv). Cosmograph는 edges의 source/target 열을 자동 인식."""
    nbuf = io.StringIO()
    w = csv.writer(nbuf, lineterminator="\n")
    w.writerow(_NODE_COLUMNS)
    for n in nodes:
        w.writerow(
            [
                n["id"],
                n["title"],
                n["year"] if n["year"] is not None else "",
                n["citation_count"] if n["citation_count"] is not None else "",
                n["role"],
                ";".join(n["hubs"]),
            ]
        )
    ebuf = io.StringIO()
    w = csv.writer(ebuf, lineterminator="\n")
    w.writerow(["source", "target", "kind"])
    for e in edges:
        w.writerow([e["source"], e["target"], e["kind"]])
    return nbuf.getvalue(), ebuf.getvalue()


def to_gexf(nodes: list[dict], edges: list[dict]) -> str:
    """GEXF 1.2 (Gephi / Gephi Lite). label은 title, 없으면 id."""
    gexf = ET.Element("gexf", {"xmlns": "http://gexf.net/1.2", "version": "1.2"})
    graph = ET.SubElement(gexf, "graph", {"defaultedgetype": "directed"})
    attrs = ET.SubElement(graph, "attributes", {"class": "node"})
    for i, (name, typ) in enumerate(
        [("year", "integer"), ("citation_count", "integer"), ("role", "string"), ("hubs", "string")]
    ):
        ET.SubElement(attrs, "attribute", {"id": str(i), "title": name, "type": typ})
    xnodes = ET.SubElement(graph, "nodes")
    for n in nodes:
        xn = ET.SubElement(xnodes, "node", {"id": n["id"], "label": n["title"] or n["id"]})
        av = ET.SubElement(xn, "attvalues")
        for i, val in enumerate(
            [n["year"], n["citation_count"], n["role"], ";".join(n["hubs"])]
        ):
            if val is not None and val != "":
                ET.SubElement(av, "attvalue", {"for": str(i), "value": str(val)})
    xedges = ET.SubElement(graph, "edges")
    for i, e in enumerate(edges):
        ET.SubElement(
            xedges, "edge", {"id": str(i), "source": e["source"], "target": e["target"]}
        )
    return ET.tostring(gexf, encoding="unicode", xml_declaration=True)


def build_network_mermaid(nodes: list[dict], edges: list[dict], direction: str = "LR") -> str:
    """통합 그래프의 Mermaid 렌더. paper는 사각형, hub는 스타디움 + 점선 소속 엣지."""
    lines = [f"graph {direction}"]
    id_map: dict[str, str] = {}
    for n in nodes:
        if n["role"] == "hub":
            nid = _hub_node_id(n["id"])
            id_map[n["id"]] = nid
            label = n["id"].replace('"', "'")
            lines.append(f'  {nid}(["{label}"])')
        else:
            nid = sanitize_node_id(n["id"])
            id_map[n["id"]] = nid
            label = (n["title"] or n["id"]).replace('"', "'")
            lines.append(f'  {nid}["{label}"]')
    for e in edges:
        src = id_map.get(e["source"])
        dst = id_map.get(e["target"])
        if src is None or dst is None:
            continue
        arrow = "-.->" if e["kind"] == "hub" else "-->"
        lines.append(f"  {src} {arrow} {dst}")
    return "\n".join(lines)
