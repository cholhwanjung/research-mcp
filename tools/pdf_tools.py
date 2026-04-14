"""MCP tools: download_paper (Phase 2.2 신설), read_paper (cache-aware로 변경).

`read_paper`는 디스크 캐시 hit이면 다운로드 skip. cache miss는 다운로드 + 저장 후 진행.
"""

from __future__ import annotations

import pymupdf

from sources.arxiv import download_pdf as _download_pdf, normalize_arxiv_id
from wiki.figures import extract_for_paper as _extract_for_paper
from wiki.pdf_store import pdf_exists, pdf_path, save_pdf


async def download_paper(paper_id: str) -> str:
    """arXiv 논문 PDF를 로컬에 다운로드해 두고 경로를 반환합니다.
    이미 저장되어 있으면 재다운로드를 skip합니다.

    Args:
        paper_id: arXiv ID (예: "2301.12597"). 'ARXIV:' prefix·버전 접미사 허용.
    """
    aid = normalize_arxiv_id(paper_id)
    if aid is None:
        return f"❌ 유효한 arXiv ID가 아닙니다: {paper_id}\n   예시: 2301.12597"

    if pdf_exists(aid):
        p = pdf_path(aid)
        return f"📁 이미 저장됨 (skip): {p}\n   크기: {p.stat().st_size // 1024} KB"

    try:
        data = await _download_pdf(aid)
    except Exception as e:
        return f"❌ PDF 다운로드 오류: {e}"

    saved = save_pdf(aid, data)
    return f"📥 PDF 저장 완료: {saved}\n   크기: {len(data) // 1024} KB"


async def read_paper(paper_id: str, max_pages: int = 0) -> str:
    """arXiv 논문 PDF를 (필요 시 다운로드 후) 전체 텍스트로 추출합니다.

    캐시 hit이면 디스크에서 바로 읽고, miss면 다운로드 + 저장 후 진행.

    Args:
        paper_id:  arXiv ID (예: "2301.12597").
        max_pages: 추출할 최대 페이지 수. 0이면 전체 (기본: 0).
    """
    aid = normalize_arxiv_id(paper_id)
    if aid is None:
        return f"❌ 유효한 arXiv ID가 아닙니다: {paper_id}\n   예시: 2301.12597"

    if not pdf_exists(aid):
        try:
            data = await _download_pdf(aid)
        except Exception as e:
            return f"❌ PDF 다운로드 오류: {e}"
        save_pdf(aid, data)

    path = pdf_path(aid)
    try:
        doc = pymupdf.open(path)
        total_pages = len(doc)
        pages_to_read = total_pages if max_pages <= 0 else min(max_pages, total_pages)

        text_parts = []
        for i in range(pages_to_read):
            page_text = doc[i].get_text()
            if page_text.strip():
                text_parts.append(f"--- Page {i + 1} ---\n{page_text.strip()}")
        doc.close()
    except Exception as e:
        return f"❌ PDF 텍스트 추출 오류: {e}"

    if not text_parts:
        return f"❌ 텍스트를 추출할 수 없습니다 (스캔된 이미지 PDF일 수 있음): {aid}"

    pdf_url = f"https://arxiv.org/pdf/{aid}"
    header = (
        f"📄 arXiv:{aid} 전문 ({pages_to_read}/{total_pages} 페이지)\n"
        f"🔗 {pdf_url}\n"
    )
    if max_pages > 0 and max_pages < total_pages:
        header += f"⚠️ max_pages={max_pages} 설정으로 처음 {max_pages}페이지만 추출됨\n"

    return f"{header}\n" + "\n\n".join(text_parts)


async def extract_paper_figures(paper_id: str) -> str:
    """캐시된 PDF에서 모든 raster figure를 vault에 저장 (ADR-010).

    저장 위치: `vault/papers/<arxiv_id>/figures/fig_<n>.png`.
    PDF 캐시가 없으면 먼저 `download_paper`를 호출해야 합니다.

    Args:
        paper_id: arXiv ID (예: "2301.12597").
    """
    aid = normalize_arxiv_id(paper_id)
    if aid is None:
        return f"❌ 유효한 arXiv ID가 아닙니다: {paper_id}\n   예시: 2301.12597"
    if not pdf_exists(aid):
        return f"❌ PDF 캐시 없음: {aid}\n   먼저 download_paper(\"{aid}\")를 호출하세요."

    figures = _extract_for_paper(aid)
    if not figures:
        return f"📁 추출된 figure 없음: {aid}"

    lines = [f"🖼️ arXiv:{aid} — {len(figures)}개 figure 추출"]
    for i, f in enumerate(figures[:10], 1):
        cap = f["caption"][:80] if f["caption"] else "(no caption)"
        lines.append(f"  [{i}] {f['file']} — {cap}")
    if len(figures) > 10:
        lines.append(f"  ... (+{len(figures) - 10}개)")
    return "\n".join(lines)


def register(mcp) -> None:
    mcp.tool()(download_paper)
    mcp.tool()(read_paper)
    mcp.tool()(extract_paper_figures)
