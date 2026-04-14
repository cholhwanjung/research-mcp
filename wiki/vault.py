"""Obsidian vault read/write. ADR-002 외부 vault, ADR-010 폴더형 노트 레이아웃.

`core.config.VAULT_PATH`를 매 호출마다 참조 — 테스트에서 monkeypatch 가능.
"""

from __future__ import annotations

from pathlib import Path

from core import config

_STANDARD_SUBDIRS = ("papers", "topics", "digests", "_meta")


def vault_root() -> Path:
    return config.VAULT_PATH


def ensure_vault() -> None:
    """vault root + 표준 subdir 생성. 이미 있으면 no-op."""
    for sub in _STANDARD_SUBDIRS:
        (vault_root() / sub).mkdir(parents=True, exist_ok=True)


def paper_dir(arxiv_id: str) -> Path:
    return vault_root() / "papers" / arxiv_id


def paper_note_path(arxiv_id: str) -> Path:
    return paper_dir(arxiv_id) / "index.md"


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
