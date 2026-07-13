"""PDF figure 추출 — 공용 구현 `wiki/visuals.py`의 kind="figure" 진입점.

ADR-010(폴더형 vault), ADR-015(caption 매칭만 저장), ADR-016(title-slug),
ADR-019(vision bbox). 세부 흐름은 visuals.py docstring 참조.
"""

from __future__ import annotations

from pathlib import Path

from wiki import visuals


def extract_figures(pdf_path_arg: Path, out_dir: Path, dpi: int = 150) -> list[dict]:
    return visuals.extract_visuals(pdf_path_arg, out_dir, "figure", dpi=dpi)


def extract_for_paper(arxiv_id: str, vault_slug: str | None = None) -> list[dict]:
    """`papers/<vault_slug>/figures/`에 저장 (ADR-016)."""
    return visuals.extract_for_paper(arxiv_id, "figure", vault_slug=vault_slug)
