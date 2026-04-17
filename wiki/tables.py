"""PDF에서 table을 vision model이 추정한 bbox로 추출 (ADR-019).

ADR-018의 caption-아래-260pt 휴리스틱은 ICML 등 caption-below-table layout에서
완전히 실패하는 것이 확인 — vision으로 전면 교체.

흐름은 figures와 동일:
1. `Table N:` caption 텍스트 + 페이지 위치 수집.
2. 페이지를 PNG 렌더 → `wiki.vision.estimate_bbox(..., kind="table")`.
3. 추정 bbox로 clip 후 저장.
4. 추정 실패는 skip.
"""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf

from core import config
from core.slug import slugify_caption
from wiki.pdf_store import pdf_path
from wiki.vision import estimate_bbox

_CAPTION_RE = re.compile(r"Table\s+(\d+)\s*[\.:]\s*([^\n]+)", re.IGNORECASE)
_RENDER_DPI = 150


def _has_caption(caption: str) -> bool:
    return bool(caption and caption.strip())


def _parse_caption_text(doc: pymupdf.Document) -> dict[int, str]:
    captions: dict[int, str] = {}
    for page in doc:
        for m in _CAPTION_RE.finditer(page.get_text()):
            n = int(m.group(1))
            captions.setdefault(n, m.group(2).strip())
    return captions


def _parse_caption_pages(doc: pymupdf.Document) -> dict[int, int]:
    pages: dict[int, int] = {}
    for pidx, page in enumerate(doc):
        nums_on_page = {int(m.group(1)) for m in _CAPTION_RE.finditer(page.get_text())}
        for n in nums_on_page:
            pages.setdefault(n, pidx)
    return pages


def extract_tables(pdf_path_arg: Path, out_dir: Path, dpi: int = _RENDER_DPI) -> list[dict]:
    """vision 추정 bbox로 table 추출 (ADR-019).

    Returns:
        [{"file": "table_<N>_<caption-slug>.png", "caption": "..."}, ...]
        bbox 추정 실패한 table은 결과에서 제외.
    """
    doc = pymupdf.open(pdf_path_arg)
    try:
        caption_text = _parse_caption_text(doc)
        caption_pages = _parse_caption_pages(doc)
        tables: list[dict] = []
        if not caption_pages:
            return tables
        out_dir.mkdir(parents=True, exist_ok=True)

        for n in sorted(caption_pages.keys()):
            cap = caption_text.get(n, "")
            if not _has_caption(cap):
                continue
            pidx = caption_pages[n]
            page = doc[pidx]
            page_png = page.get_pixmap(dpi=dpi).tobytes("png")
            bbox = estimate_bbox(page_png, cap, page.rect.width, page.rect.height, kind="table")
            if bbox is None:
                continue
            clip = pymupdf.Rect(*bbox)
            pix = page.get_pixmap(clip=clip, dpi=dpi)
            if pix.n - pix.alpha >= 4:
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            cap_slug = slugify_caption(cap)
            file_name = f"table_{n}_{cap_slug}.png" if cap_slug else f"table_{n}.png"
            pix.save(out_dir / file_name)
            pix = None
            tables.append({"file": file_name, "caption": cap})
        return tables
    finally:
        doc.close()


def extract_for_paper(arxiv_id: str, vault_slug: str | None = None) -> list[dict]:
    """편의 wrapper. `papers/<vault_slug>/tables/`에 저장 (ADR-016)."""
    pdf = pdf_path(arxiv_id)
    slug = vault_slug or arxiv_id
    out_dir = config.VAULT_PATH / "papers" / slug / "tables"
    raw = extract_tables(pdf, out_dir)
    return [{"file": f"tables/{r['file']}", "caption": r["caption"]} for r in raw]
