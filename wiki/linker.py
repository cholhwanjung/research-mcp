"""Obsidian `[[wikilink]]` 파싱 + vault 노트 일괄 로드.

문법: `[[target]]` 또는 `[[target|alias]]`. target만 추출, 순서 보존하며 중복 제거.
첨부 파일 참조(`![[figures/x.png]]`)는 노트 링크가 아니므로 제외 — 링크 그래프에
섞이면 존재하지 않는 노트로 오탐된다. 임베드 문법이어도 대상이 노트면
(`![[graphs/<slug>]]` 트랜스클루전) 링크로 센다 (ADR-033).
`read_vault_notes()`는 vault 전체 `.md`를 {slug: content}로 읽는다 — wiki_search 입력.
"""

from __future__ import annotations

import re

from wiki.vault import vault_root

_WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
# vault에 embed되는 첨부 확장자. slug에 점이 있을 수 있어(arxiv_id) 명시 목록으로 판별.
_ATTACHMENT_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".pdf")


def extract_links(content: str) -> list[str]:
    seen: list[str] = []
    for m in _WIKILINK.finditer(content):
        target = m.group(1).strip()
        if target.lower().endswith(_ATTACHMENT_SUFFIXES):
            continue
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
