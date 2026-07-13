"""PDF에서 figure/table을 vision 추정 bbox로 추출하는 공용 구현 (ADR-019).

figures.py / tables.py의 쌍둥이 코드를 `kind` 파라미터 하나로 통합.
- kind="figure" → `Figure N:` caption, `fig_<N>_<slug>.png`, `figures/` subdir
- kind="table"  → `Table N:` caption, `table_<N>_<slug>.png`, `tables/` subdir

흐름:
1. `<Kind> N:` caption 텍스트 + 페이지 위치를 한 pass로 수집.
2. 해당 페이지를 PNG로 렌더 → `wiki.vision.estimate_bbox`로 영역 추정.
3. 추정 bbox로 clip 후 vault에 저장. 추정 실패(None)는 skip.

`vision.estimate_bbox`는 런타임 속성 참조로 호출 — 테스트가 `wiki.vision`만
monkeypatch하면 됨 (tests/conftest.py).
"""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf

from core import config
from core.slug import slugify_caption
from wiki import vision
from wiki.pdf_store import pdf_path

_RENDER_DPI = 150

# kind → (caption 단어, 파일 접두, vault subdir)
_KINDS = {
    "figure": ("Figure", "fig", "figures"),
    "table": ("Table", "table", "tables"),
}


def _has_caption(caption: str) -> bool:
    """저장 가치 판단: caption 텍스트가 비어 있지 않아야 한다 (ADR-015)."""
    return bool(caption and caption.strip())


def _parse_captions(doc: pymupdf.Document, pattern: re.Pattern) -> dict[int, tuple[str, int]]:
    """{number: (caption_text, page_idx)} — 첫 등장 기준, 문서 한 pass."""
    found: dict[int, tuple[str, int]] = {}
    for pidx, page in enumerate(doc):
        for m in pattern.finditer(page.get_text()):
            found.setdefault(int(m.group(1)), (m.group(2).strip(), pidx))
    return found


def extract_visuals(
    pdf_path_arg: Path, out_dir: Path, kind: str, dpi: int = _RENDER_DPI
) -> list[dict]:
    """vision 추정 bbox로 figure/table 추출 (ADR-019).

    Returns:
        [{"file": "<prefix>_<N>_<caption-slug>.png", "caption": "..."}, ...]
        file은 out_dir 기준 상대 경로. bbox 추정 실패한 항목은 결과에서 제외.
    """
    word, prefix, _ = _KINDS[kind]
    pattern = re.compile(rf"{word}\s+(\d+)\s*[\.:]\s*([^\n]+)", re.IGNORECASE)
    doc = pymupdf.open(pdf_path_arg)
    try:
        captions = _parse_captions(doc, pattern)
        results: list[dict] = []
        if not captions:
            return results
        out_dir.mkdir(parents=True, exist_ok=True)

        for n in sorted(captions):
            cap, pidx = captions[n]
            if not _has_caption(cap):
                continue
            page = doc[pidx]
            page_png = page.get_pixmap(dpi=dpi).tobytes("png")
            bbox = vision.estimate_bbox(
                page_png, cap, page.rect.width, page.rect.height, kind=kind
            )
            if bbox is None:
                continue
            pix = page.get_pixmap(clip=pymupdf.Rect(*bbox), dpi=dpi)
            if pix.n - pix.alpha >= 4:
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            cap_slug = slugify_caption(cap)
            file_name = f"{prefix}_{n}_{cap_slug}.png" if cap_slug else f"{prefix}_{n}.png"
            pix.save(out_dir / file_name)
            results.append({"file": file_name, "caption": cap})
        return results
    finally:
        doc.close()


def extract_for_paper(arxiv_id: str, kind: str, vault_slug: str | None = None) -> list[dict]:
    """편의 wrapper. `papers/<vault_slug>/<subdir>/`에 저장 (ADR-016)."""
    subdir = _KINDS[kind][2]
    slug = vault_slug or arxiv_id
    out_dir = config.VAULT_PATH / "papers" / slug / subdir
    raw = extract_visuals(pdf_path(arxiv_id), out_dir, kind)
    return [{"file": f"{subdir}/{r['file']}", "caption": r["caption"]} for r in raw]
