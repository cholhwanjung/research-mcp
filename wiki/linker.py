"""Obsidian `[[wikilink]]` 파싱 + 백링크 계산.

문법: `[[target]]` 또는 `[[target|alias]]`. target만 추출, 순서 보존하며 중복 제거.

vault 통합 (Phase 3.3, D-2): `read_vault_notes()`로 vault 전체를 dict로 읽어
`backlinks()`와 조합 → `vault_backlinks(target)` 단일 호출.
"""

from __future__ import annotations

import re

from wiki.vault import vault_root

_WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")


def extract_links(content: str) -> list[str]:
    seen: list[str] = []
    for m in _WIKILINK.finditer(content):
        target = m.group(1).strip()
        if target and target not in seen:
            seen.append(target)
    return seen


def backlinks(target: str, notes: dict[str, str]) -> list[str]:
    """target을 가리키는 노트 ID 정렬 리스트. notes는 {note_id: content}."""
    referring = [nid for nid, body in notes.items() if target in extract_links(body)]
    return sorted(referring)


def _slug_for(md_path) -> str:
    """vault 안 md 파일 경로 → wikilink target과 일치하는 slug.

    - `papers/<id>/index.md` → `<id>` (ADR-010 폴더형, 사용자가 wikilink로 자주 쓰는 형태)
    - 그 외 평탄형 `<dir>/<name>.md` → `<dir>/<name>`
    """
    rel = md_path.relative_to(vault_root())
    parts = rel.parts
    if (
        len(parts) == 3
        and parts[0] == "papers"
        and parts[2] == "index.md"
    ):
        return parts[1]
    # 평탄형: 확장자 제거
    return str(rel.with_suffix(""))


def read_vault_notes() -> dict[str, str]:
    """vault 전체에서 `.md` 노트만 수집 → {slug: content}."""
    root = vault_root()
    if not root.exists():
        return {}
    return {_slug_for(p): p.read_text(encoding="utf-8") for p in root.rglob("*.md")}


def vault_backlinks(target: str) -> list[str]:
    """vault 전체에서 `target` wikilink를 가진 노트 slug 정렬 리스트."""
    return backlinks(target, read_vault_notes())
