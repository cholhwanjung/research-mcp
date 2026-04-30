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
    mcp.tool()(wiki_link)
