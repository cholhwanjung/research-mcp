"""Obsidian vault read/write. ADR-002 외부 vault, ADR-010 폴더형 노트 레이아웃,
ADR-016 폴더명은 title-slug (arxiv_id는 frontmatter에 보존).

`core.config.VAULT_PATH`를 매 호출마다 참조 — 테스트에서 monkeypatch 가능.
"""

from __future__ import annotations

import re
from pathlib import Path

from core import config
from wiki.frontmatter import parse_note

_STANDARD_SUBDIRS = ("papers", "topics", "digests", "notes", "_meta")
# frontmatter의 arxiv_id를 quote 유무 모두 매칭.
_ARXIV_LINE_RE = re.compile(
    r'^arxiv_id\s*:\s*["\']?([^"\'\s]+)["\']?\s*$',
    re.MULTILINE,
)


def vault_root() -> Path:
    return config.VAULT_PATH


def ensure_vault() -> None:
    """vault root + 표준 subdir 생성. 이미 있으면 no-op."""
    for sub in _STANDARD_SUBDIRS:
        (vault_root() / sub).mkdir(parents=True, exist_ok=True)


def paper_dir(slug: str) -> Path:
    """slug는 title-slug 또는 호환을 위한 임의 식별자 (ADR-016)."""
    return vault_root() / "papers" / slug


def paper_note_path(slug: str) -> Path:
    """ADR-023: 파일명을 폴더 slug와 동일하게 — Obsidian graph view에서
    노드 텍스트가 'index'가 아닌 사람-가독 slug로 표시되게.
    """
    return paper_dir(slug) / f"{slug}.md"


def read_note(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_note(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def list_hubs() -> list[dict]:
    """vault `topics/*.md`의 frontmatter에서 `tier: hub`인 노트의 메타를 반환 (ADR-022).

    각 항목 dict 키: `slug` (파일명, 확장자 제외), `title`, `aliases`, `parent`,
    `related`, `summary`. 누락된 필드는 안전한 기본값 (`title`은 slug fallback).

    citation-analysis SKILL의 step 7' (LLM hub matching)에서 사용.
    """
    base = vault_root() / "topics"
    if not base.is_dir():
        return []
    hubs: list[dict] = []
    for path in sorted(base.glob("*.md")):
        try:
            fm, _body = parse_note(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        if not isinstance(fm, dict) or fm.get("tier") != "hub":
            continue
        slug = path.stem
        hubs.append(
            {
                "slug": slug,
                "title": fm.get("title") or slug,
                "aliases": list(fm.get("aliases") or []),
                "parent": fm.get("parent"),
                "related": list(fm.get("related") or []),
                "summary": fm.get("summary") or "",
            }
        )
    return hubs


def resolve_paper_by_arxiv_id(arxiv_id: str) -> Path | None:
    """vault `papers/<slug>/<slug>.md` (ADR-023) 또는 legacy `index.md` (ADR-010)의
    frontmatter에서 `arxiv_id`로 노트를 찾는다.

    파일명 우선순위: `<slug>.md` → `index.md` (backward compat).
    못 찾으면 None.
    """
    base = vault_root() / "papers"
    if not base.is_dir():
        return None
    target = arxiv_id.strip()
    for paper in base.iterdir():
        if not paper.is_dir():
            continue
        # ADR-023: <slug>.md 우선, legacy index.md fallback.
        candidates = [paper / f"{paper.name}.md", paper / "index.md"]
        for cand in candidates:
            if not cand.is_file():
                continue
            text = cand.read_text(encoding="utf-8", errors="ignore")
            m = _ARXIV_LINE_RE.search(text)
            if m and m.group(1).strip() == target:
                return cand
    return None
