"""PDF에서 raster figure + caption 추출 (ADR-010 멀티모달 wiki).

- 모든 embedded raster image를 PNG로 추출 → `out_dir/fig_<n>.png`
- "Figure N:" 또는 "Figure N." 패턴을 PDF 텍스트에서 찾아 순번으로 매칭
- 벡터 그림은 본 모듈에서 추출하지 않음 (후속 ADR로 보강 가능)
"""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf

from core import config
from wiki.pdf_store import pdf_path

_CAPTION_RE = re.compile(r"Figure\s+(\d+)\s*[\.:]\s*([^\n]+)", re.IGNORECASE)


def _parse_captions(doc: pymupdf.Document) -> dict[int, str]:
    """Returns {figure_number: caption_text}."""
    text = "\n".join(page.get_text() for page in doc)
    captions: dict[int, str] = {}
    for m in _CAPTION_RE.finditer(text):
        n = int(m.group(1))
        captions.setdefault(n, m.group(2).strip())
    return captions


def extract_figures(pdf_path_arg: Path, out_dir: Path) -> list[dict]:
    """PDF에서 모든 raster figure 추출 → out_dir/fig_<n>.png 저장.

    Returns:
        [{"file": "fig_1.png", "caption": "..."}, ...]
        file은 out_dir 기준 상대 경로.
    """
    doc = pymupdf.open(pdf_path_arg)
    try:
        captions = _parse_captions(doc)
        figures: list[dict] = []
        seen_xref: set[int] = set()
        counter = 0

        for page in doc:
            for img_info in page.get_images(full=True):
                xref = img_info[0]
                if xref in seen_xref:
                    continue
                seen_xref.add(xref)
                counter += 1

                pix = pymupdf.Pixmap(doc, xref)
                # CMYK 등 4채널 이상은 RGB로 변환
                if pix.n - pix.alpha >= 4:
                    pix = pymupdf.Pixmap(pymupdf.csRGB, pix)

                out_dir.mkdir(parents=True, exist_ok=True)
                file_name = f"fig_{counter}.png"
                pix.save(out_dir / file_name)
                pix = None  # release

                figures.append({
                    "file": file_name,
                    "caption": captions.get(counter, ""),
                })

        return figures
    finally:
        doc.close()


def extract_for_paper(arxiv_id: str) -> list[dict]:
    """편의 wrapper: arxiv_id → pdf_store.pdf_path + vault paper figures 디렉토리.

    반환 dict의 `file`은 vault note 기준 상대 경로 (`figures/fig_<n>.png`) —
    frontmatter `figures: [...]`에 그대로 들어가는 형식 (ARCHITECTURE §5.1).
    """
    pdf = pdf_path(arxiv_id)
    paper_root = config.VAULT_PATH / "papers" / arxiv_id
    out_dir = paper_root / "figures"
    raw = extract_figures(pdf, out_dir)
    return [{"file": f"figures/{r['file']}", "caption": r["caption"]} for r in raw]
