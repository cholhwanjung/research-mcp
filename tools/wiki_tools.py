"""MCP wiki tools — Obsidian vault read/write/list/link.

slug 규약:
- 단순 식별자 (예: `"2301.12597"`) → `papers/<id>/index.md` (ADR-010 폴더형)
- `/` 포함 (예: `"topics/vlm"`, `"papers/<id>/index"`) → `<vault>/<slug>.md`
"""

from __future__ import annotations

import json
from pathlib import Path

from wiki.frontmatter import dump_note
from wiki.vault import ensure_vault, paper_note_path, read_note, vault_root, write_note


def _resolve_slug(slug: str) -> Path:
    s = slug.strip()
    if "/" not in s:
        return paper_note_path(s)
    if not s.endswith(".md"):
        s = s + ".md"
    return vault_root() / s


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
    mcp.tool()(wiki_list)
    mcp.tool()(wiki_link)
