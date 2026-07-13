"""Obsidian `[[wikilink]]` 파싱 + vault 노트 일괄 로드.

문법: `[[target]]` 또는 `[[target|alias]]`. target만 추출, 순서 보존하며 중복 제거.
`read_vault_notes()`는 vault 전체 `.md`를 {slug: content}로 읽는다 — wiki_search 입력.
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
