"""PDF table 추출 — 공용 구현 `wiki/visuals.py`의 kind="table" 진입점.

ADR-018의 caption-아래-260pt 휴리스틱은 caption-below-table layout에서 실패가
확인되어 ADR-019 vision bbox로 교체됨. 세부 흐름은 visuals.py docstring 참조.
"""

from __future__ import annotations

from pathlib import Path

from wiki import visuals


def extract_tables(pdf_path_arg: Path, out_dir: Path, dpi: int = 150) -> list[dict]:
    return visuals.extract_visuals(pdf_path_arg, out_dir, "table", dpi=dpi)


def extract_for_paper(arxiv_id: str, vault_slug: str | None = None) -> list[dict]:
    """`papers/<vault_slug>/tables/`에 저장 (ADR-016)."""
    return visuals.extract_for_paper(arxiv_id, "table", vault_slug=vault_slug)
