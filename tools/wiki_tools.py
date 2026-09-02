"""MCP wiki tools — Obsidian vault read/write/list/link.

slug 규약 (ADR-016):
- arxiv_id 형식 (예: `"2301.12597"`) → frontmatter scan으로 매칭되는
  `papers/<title-slug>/index.md`. 못 찾으면 `papers/<arxiv_id>/index.md` fallback.
- 일반 단순 식별자 (예: `"blip-2"`) → `papers/<slug>/index.md`.
- `/` 포함 (예: `"topics/vlm"`) → `<vault>/<slug>.md`.
"""

from __future__ import annotations

import json
from pathlib import Path

from core.slug import is_arxiv_id
from wiki.frontmatter import dump_note
from wiki.vault import (
    ensure_vault,
    paper_dir,
    paper_note_path,
    read_note,
    resolve_paper_by_arxiv_id,
    vault_root,
    write_note,
)


def _resolve_slug(slug: str) -> Path:
    s = slug.strip()
    if "/" in s:
        if not s.endswith(".md"):
            s = s + ".md"
        return vault_root() / s
    if is_arxiv_id(s):
        # ADR-016: arxiv_id로 title-slug 폴더 lookup.
        found = resolve_paper_by_arxiv_id(s)
        if found is not None:
            return found
    # ADR-023: <slug>.md 우선. legacy index.md backward compat.
    path = paper_note_path(s)
    if not path.is_file():
        legacy = paper_dir(s) / "index.md"
        if legacy.is_file():
            return legacy
    return path


def wiki_read_note(slug: str) -> str:
    """Obsidian 노트 전문 조회 (frontmatter 포함).

    Args:
        slug: arxiv_id ("2301.12597") 또는 vault 상대경로 ("topics/vlm").
    """
    path = _resolve_slug(slug)
    if not path.is_file():
        return f"❌ 노트 없음: {slug}\n   path: {path}"
    return read_note(path)


def wiki_write_note(slug: str, frontmatter: dict | str | None = None, body: str = "") -> str:
    """노트 저장 (frontmatter + body). 폴더 자동 생성.

    Args:
        slug: arxiv_id 또는 vault 상대경로.
        frontmatter: YAML로 직렬화될 dict. MCP 클라이언트가 string으로 보내면
                     JSON으로 parse 시도 (parse 실패 시 빈 frontmatter로 처리).
        body: 마크다운 본문.
    """
    if isinstance(frontmatter, str):
        try:
            frontmatter = json.loads(frontmatter)
            if not isinstance(frontmatter, dict):
                frontmatter = None
        except (json.JSONDecodeError, ValueError):
            frontmatter = None
    path = _resolve_slug(slug)
    content = dump_note(frontmatter or {}, body)
    write_note(path, content)
    return f"💾 노트 저장: {path}"


def wiki_list(prefix: str = "papers") -> str:
    """vault 안 디렉토리의 노트 목록 (papers/topics/digests 등).

    Args:
        prefix: vault root 기준 디렉토리. 기본 'papers'.
    """
    ensure_vault()
    base = vault_root() / prefix
    if not base.exists():
        return f"❌ 디렉토리 없음: {prefix}"
    items = sorted(
        p.name for p in base.iterdir() if p.is_dir() or p.suffix == ".md"
    )
    if not items:
        return f"({prefix} 비어 있음)"
    return f"📚 {prefix} ({len(items)})\n" + "\n".join(f"  - {i}" for i in items)


def wiki_list_hubs() -> str:
    """vault `topics/*.md` 중 frontmatter `tier: hub`인 안정 hub 목록 + 메타 (ADR-022).

    citation-analysis SKILL의 hub matching step에서 LLM이 자유 토픽 생성 대신
    기존 hub 매칭을 시도할 때 사용. 응답에 slug · title · aliases · parent · related · summary
    포함.
    """
    from wiki.vault import list_hubs as _list_hubs

    ensure_vault()
    hubs = _list_hubs()
    if not hubs:
        return "(hub 없음 — topics/*.md에 `tier: hub` 노트가 아직 없음)"
    lines = [f"🏷️ Hubs ({len(hubs)})\n"]
    for h in hubs:
        line = f"- [[{h['slug']}]]"
        if h["title"] and h["title"] != h["slug"]:
            line += f" ({h['title']})"
        if h["summary"]:
            line += f" — {h['summary']}"
        lines.append(line)
        meta = []
        if h["aliases"]:
            meta.append(f"aliases: {', '.join(h['aliases'])}")
        if h["parent"]:
            meta.append(f"parent: {h['parent']}")
        if h["related"]:
            meta.append(f"related: {', '.join(h['related'])}")
        if meta:
            lines.append(f"    {' | '.join(meta)}")
    return "\n".join(lines)


def wiki_search(query: str, top_k: int = 5, expand: bool = True) -> str:
    """질문과 관련된 vault 노트를 어휘 매칭 + 링크 이웃 확장으로 검색 (ADR-028).

    vault 전체를 컨텍스트에 로드하지 않고 관련 노트 slug만 추려준다 — 이후
    상세는 `wiki_read_note(slug)`로 조회. 임베딩·외부 호출 없음.

    Args:
        query: 자연어 질의 (예: "frozen visual encoder를 쓰는 논문").
        top_k: 최대 결과 수 (기본 5).
        expand: True면 어휘 seed에서 `[[wikilink]]` 1-hop 이웃까지 확장 (기본 True).
    """
    from analysis.retrieval import search
    from wiki.linker import extract_links, read_vault_notes

    notes = read_vault_notes()
    if not notes:
        return "❌ vault가 비어 있습니다 (검색할 노트 없음)."
    adjacency = {slug: extract_links(content) for slug, content in notes.items()}
    hits = search(query, notes, adjacency, top_k=top_k, expand=expand)
    if not hits:
        return f'🔎 "{query}" — 관련 노트를 찾지 못했습니다.'
    lines = [f'🔎 wiki_search "{query}" — 관련 노트 {len(hits)}개']
    for i, h in enumerate(hits, 1):
        tag = ("어휘: " + ", ".join(h.matched)) if h.via == "lexical" else "이웃 확장"
        lines.append(f"{i}. [[{h.slug}]]  (score {h.score:.1f} · {tag})")
        if h.snippet:
            lines.append(f"   {h.snippet}")
    lines.append("\n→ 상세는 wiki_read_note(slug)로 조회하세요.")
    return "\n".join(lines)


def _format_graph(graph) -> str:
    from analysis.linkgraph import orphans

    resolved = sum(len(v) for v in graph.forward.values())
    broken_n = sum(len(v) for v in graph.broken.values())
    orph = orphans(graph)
    lines = [
        "🕸️ wiki_backlinks — vault 전체 링크 그래프",
        f"   노트 {len(graph.forward)} · 링크 {resolved + broken_n}"
        f" (해석 {resolved} · 깨짐 {broken_n}) · 고아 {len(orph)}",
    ]
    if graph.broken:
        lines.append(f"\n⚠️ 깨진 링크 {broken_n}건 — 실재 노트로 해석 안 됨")
        for slug in sorted(graph.broken):
            targets = ", ".join(f"[[{t}]]" for t in graph.broken[slug])
            lines.append(f"  - {slug} → {targets}")
    if graph.case_mismatch:
        n = sum(len(v) for v in graph.case_mismatch.values())
        lines.append(f"\n✏️ 표기 불일치 {n}건 — 해석은 되지만 본문 표기가 노트명과 다름")
        for slug in sorted(graph.case_mismatch):
            pairs = ", ".join(
                f"[[{raw}]] → {real}" for raw, real in graph.case_mismatch[slug]
            )
            lines.append(f"  - {slug}: {pairs}")
    if orph:
        lines.append(f"\n🕳️ 고아 노트 {len(orph)}건 — inbound 0")
        lines += [f"  - {slug}" for slug in orph]
    inbound = [(slug, srcs) for slug, srcs in sorted(graph.backward.items()) if srcs]
    if inbound:
        lines.append(f"\n📇 backlink (inbound 있는 노트 {len(inbound)})")
        for slug, srcs in inbound:
            lines.append(f"  - {slug} ← {len(srcs)}: " + ", ".join(srcs))
    lines.append("\n→ 본문이 필요한 노트만 wiki_read_note(slug)로 조회하세요.")
    return "\n".join(lines)


def _format_note_links(slug: str, graph, notes: dict) -> str:
    from analysis.linkgraph import resolve_targets

    key = resolve_targets(set(notes))(slug)
    if key is None:
        return f"❌ 노트 없음: {slug}"
    inbound = graph.backward.get(key, [])
    outbound = graph.forward.get(key, [])
    lines = [
        f"🔗 wiki_backlinks — {key}",
        f"   inbound {len(inbound)}: " + (", ".join(inbound) or "(없음)"),
        f"   outbound {len(outbound)}: " + (", ".join(outbound) or "(없음)"),
    ]
    bad = graph.broken.get(key, [])
    if bad:
        lines.append(f"   깨진 링크 {len(bad)}: " + ", ".join(f"[[{t}]]" for t in bad))
    return "\n".join(lines)


def wiki_backlinks(slug: str = "") -> str:
    """vault `[[wikilink]]` 링크 그래프 조회 — 읽기 전용 (ADR-033).

    인자 없이 부르면 vault 전체 그래프를 한 번에 반환한다: 노트별 inbound 링크,
    inbound 0인 고아 노트, 실재 노트로 해석 안 되는 깨진 링크, 해석은 되지만 표기가
    어긋난 링크. 노트 본문을 전수 읽지 않고 링크 정합성을 점검할 때 쓴다
    (wiki-lint의 깨진링크·고아·누락참조 입력).

    Args:
        slug: 비우면 vault 전체 그래프. 주면 그 노트의 inbound/outbound만.
              vault 상대경로("topics/vlm") 또는 본문 wikilink 표기("blip-2").
    """
    from analysis.linkgraph import build_link_graph
    from wiki.linker import extract_links, read_vault_notes

    notes = read_vault_notes()
    if not notes:
        return "❌ vault가 비어 있습니다 (링크 그래프 없음)."
    adjacency = {s: extract_links(content) for s, content in notes.items()}
    graph = build_link_graph(notes, adjacency)
    target = slug.strip()
    return _format_note_links(target, graph, notes) if target else _format_graph(graph)


def wiki_link(source: str, target: str, note: str = "") -> str:
    """source 노트 본문 끝에 `- [[target]]` 라인 추가. 중복이면 skip.

    Args:
        source: 링크를 추가할 노트 slug.
        target: 가리킬 노트 slug (Obsidian wikilink).
        note: 링크 옆 한 줄 설명 (옵션).
    """
    path = _resolve_slug(source)
    if not path.is_file():
        return f"❌ source 노트 없음: {source}"
    existing = read_note(path)
    line = f"- [[{target}]]" + (f" — {note}" if note else "")
    if line in existing:
        return f"⏭️ 이미 링크 있음: {source} → {target}"
    write_note(path, existing.rstrip() + "\n" + line + "\n")
    return f"🔗 링크 추가: {source} → {target}"


def register(mcp) -> None:
    mcp.tool()(wiki_read_note)
    mcp.tool()(wiki_write_note)
    mcp.tool()(wiki_list_hubs)
    mcp.tool()(wiki_list)
    mcp.tool()(wiki_search)
    mcp.tool()(wiki_backlinks)
    mcp.tool()(wiki_link)
