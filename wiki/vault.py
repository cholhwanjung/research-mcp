"""Obsidian vault read/write. ADR-002 외부 vault, ADR-010 폴더형 노트 레이아웃,
ADR-016 폴더명은 title-slug (arxiv_id는 frontmatter에 보존).

`core.config.VAULT_PATH`를 매 호출마다 참조 — 테스트에서 monkeypatch 가능.
"""

from __future__ import annotations

import re
from pathlib import Path

from core import config

_STANDARD_SUBDIRS = ("papers", "topics", "digests", "_meta")
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
    return paper_dir(slug) / "index.md"


def read_note(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_note(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def list_papers() -> list[str]:
    base = vault_root() / "papers"
    if not base.exists():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir())


def resolve_paper_by_arxiv_id(arxiv_id: str) -> Path | None:
    """vault `papers/*/index.md`의 frontmatter에서 `arxiv_id`로 노트를 찾는다 (ADR-016).

    title-slug 폴더 명명 도입 후 외부 호출자(citation-analysis 등)가 arxiv_id로
    노트 위치를 찾을 때 사용. 못 찾으면 None.
    """
    base = vault_root() / "papers"
    if not base.is_dir():
        return None
    target = arxiv_id.strip()
    for paper in base.iterdir():
        idx = paper / "index.md"
        if not idx.is_file():
            continue
        text = idx.read_text(encoding="utf-8", errors="ignore")
        m = _ARXIV_LINE_RE.search(text)
        if m and m.group(1).strip() == target:
            return idx
    return None
