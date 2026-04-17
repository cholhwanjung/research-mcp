"""MCP tools: download_paper (Phase 2.2 신설), read_paper (cache-aware로 변경).

`read_paper`는 디스크 캐시 hit이면 다운로드 skip. cache miss는 다운로드 + 저장 후 진행.
"""

from __future__ import annotations

import re

import pymupdf

from core import config
from sources.arxiv import download_pdf as _download_pdf, normalize_arxiv_id
from wiki.figures import extract_for_paper as _extract_for_paper
from wiki.pdf_store import pdf_exists, pdf_path, save_pdf
from wiki.tables import extract_for_paper as _extract_tables_for_paper


def _build_keep_matcher(keep: list[str], prefix: str):
    """`keep` 입력을 (정확 파일명 set, number set, full-string set) 셋으로 정규화.

    `prefix`는 'fig' 또는 'table'. number 매칭 패턴: `<prefix>_<N>(.png)?`.
    """
    exact: set[str] = set()
    numbers: set[int] = set()
    pat = re.compile(rf"^{re.escape(prefix)}_(\d+)(?:\.png)?$")
    for k in keep:
        if not k or not k.strip():
            continue
        k = k.rsplit("/", 1)[-1].strip()
        m = pat.match(k)
        if m:
            numbers.add(int(m.group(1)))
        else:
            exact.add(k)
    return exact, numbers


def _keep_decision(name: str, prefix: str, exact: set[str], numbers: set[int]) -> bool:
    if name in exact:
        return True
    # `<prefix>_<N>[_<rest>].png` 형식에서 N 추출.
    m = re.match(rf"^{re.escape(prefix)}_(\d+)(?:_.*)?\.png$", name)
    if m and int(m.group(1)) in numbers:
        return True
    return False


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


async def extract_paper_figures(paper_id: str, slug: str | None = None) -> str:
    """캐시된 PDF에서 caption 매칭된 raster figure를 vault에 저장 (ADR-010, ADR-015, ADR-016).

    저장 위치: `vault/papers/<slug>/figures/fig_<n>.png`. slug 미지정 시 arxiv_id를
    fallback (legacy 호환).

    Args:
        paper_id: arXiv ID (예: "2301.12597") — PDF 캐시 검색용.
        slug:     vault 디렉토리명 (title-slug). 비우면 arxiv_id 사용.
    """
    aid = normalize_arxiv_id(paper_id)
    if aid is None:
        return f"❌ 유효한 arXiv ID가 아닙니다: {paper_id}\n   예시: 2301.12597"
    if not pdf_exists(aid):
        return f"❌ PDF 캐시 없음: {aid}\n   먼저 download_paper(\"{aid}\")를 호출하세요."

    figures = _extract_for_paper(aid, vault_slug=slug)
    if not figures:
        return f"📁 추출된 figure 없음: {aid}"

    where = slug or aid
    lines = [f"🖼️ arXiv:{aid} → papers/{where}/ — {len(figures)}개 figure 추출"]
    for i, f in enumerate(figures[:10], 1):
        cap = f["caption"][:80] if f["caption"] else "(no caption)"
        lines.append(f"  [{i}] {f['file']} — {cap}")
    if len(figures) > 10:
        lines.append(f"  ... (+{len(figures) - 10}개)")
    return "\n".join(lines)


async def prune_paper_figures(paper_id: str, keep: list[str], slug: str | None = None) -> str:
    """vault의 `papers/<slug>/figures/` 에서 `keep`에 명시된 파일만 남기고 나머지 삭제
    (ADR-015, ADR-016).

    LLM이 `extract_paper_figures` 결과의 caption을 보고 핵심 architecture / 결과
    plot만 선별 → 선별 결과를 `keep`으로 넘겨 호출. 나머지 figure는 디스크에서 제거.

    Args:
        paper_id: arXiv ID (정규화 검사용).
        keep:     남길 figure의 파일 식별자 리스트. "figures/fig_1.png" 또는
                  "fig_1.png" 둘 다 허용. 빈 리스트면 모든 figure 삭제.
        slug:     vault 디렉토리명 (title-slug). 비우면 arxiv_id 사용 (legacy 호환).
    """
    aid = normalize_arxiv_id(paper_id)
    if aid is None:
        return f"❌ 유효한 arXiv ID가 아닙니다: {paper_id}"

    where = slug or aid
    fig_dir = config.VAULT_PATH / "papers" / where / "figures"
    if not fig_dir.is_dir():
        return f"❌ figures 디렉토리 없음: {fig_dir}\n   먼저 extract_paper_figures를 호출하세요."

    exact, numbers = _build_keep_matcher(keep, "fig")
    all_figs = sorted(fig_dir.glob("fig_*.png"))
    deleted: list[str] = []
    kept: list[str] = []
    for p in all_figs:
        if _keep_decision(p.name, "fig", exact, numbers):
            kept.append(p.name)
        else:
            p.unlink()
            deleted.append(p.name)

    return (
        f"🧹 prune 완료: arXiv:{aid}\n"
        f"   유지: {len(kept)}개 — {', '.join(kept) if kept else '(없음)'}\n"
        f"   삭제: {len(deleted)}개"
    )


async def extract_paper_tables(paper_id: str, slug: str | None = None) -> str:
    """캐시된 PDF에서 caption 기준 영역 crop으로 table을 vault에 저장 (ADR-018).

    저장 위치: `vault/papers/<slug>/tables/table_<n>.png`. 각 table은 caption +
    그 아래 일정 영역을 raster로 렌더해 1 PNG에 보존 (table 본체는 PDF 내부 vector
    text라 sub-image 분리가 불가능 — 영역 crop이 유일한 방법).

    Args:
        paper_id: arXiv ID.
        slug:     vault 디렉토리명. 비우면 arxiv_id 사용.
    """
    aid = normalize_arxiv_id(paper_id)
    if aid is None:
        return f"❌ 유효한 arXiv ID가 아닙니다: {paper_id}\n   예시: 2301.12597"
    if not pdf_exists(aid):
        return f"❌ PDF 캐시 없음: {aid}\n   먼저 download_paper(\"{aid}\")를 호출하세요."

    tables = _extract_tables_for_paper(aid, vault_slug=slug)
    if not tables:
        return f"📁 추출된 table 없음: {aid}"

    where = slug or aid
    lines = [f"📊 arXiv:{aid} → papers/{where}/ — {len(tables)}개 table 추출"]
    for i, t in enumerate(tables[:10], 1):
        cap = t["caption"][:80] if t["caption"] else "(no caption)"
        lines.append(f"  [{i}] {t['file']} — {cap}")
    if len(tables) > 10:
        lines.append(f"  ... (+{len(tables) - 10}개)")
    return "\n".join(lines)


async def prune_paper_tables(paper_id: str, keep: list[str], slug: str | None = None) -> str:
    """vault의 `papers/<slug>/tables/` 에서 `keep`에 명시된 파일만 남기고 나머지 삭제.

    Args:
        paper_id: arXiv ID.
        keep:     남길 table 파일 식별자 ("tables/table_1.png" 또는 "table_1.png").
        slug:     vault 디렉토리명.
    """
    aid = normalize_arxiv_id(paper_id)
    if aid is None:
        return f"❌ 유효한 arXiv ID가 아닙니다: {paper_id}"

    where = slug or aid
    tab_dir = config.VAULT_PATH / "papers" / where / "tables"
    if not tab_dir.is_dir():
        return f"❌ tables 디렉토리 없음: {tab_dir}\n   먼저 extract_paper_tables를 호출하세요."

    exact, numbers = _build_keep_matcher(keep, "table")
    all_tabs = sorted(tab_dir.glob("table_*.png"))
    deleted: list[str] = []
    kept: list[str] = []
    for p in all_tabs:
        if _keep_decision(p.name, "table", exact, numbers):
            kept.append(p.name)
        else:
            p.unlink()
            deleted.append(p.name)
    return (
        f"🧹 table prune: arXiv:{aid}\n"
        f"   유지: {len(kept)}개 — {', '.join(kept) if kept else '(없음)'}\n"
        f"   삭제: {len(deleted)}개"
    )


async def render_paper_page(
    paper_id: str,
    page: int,
    slug: str | None = None,
    dpi: int = 150,
) -> str:
    """PDF의 특정 페이지를 통째로 PNG로 렌더해 vault에 저장 (ADR-018 옵션).

    ColPali 스타일 page-as-image의 단순 도구. figure crop이 잡지 못한 케이스나
    수식이 많은 페이지를 시각적으로 보존하고 싶을 때 사용.

    Args:
        paper_id: arXiv ID.
        page:     1-base 페이지 번호.
        slug:     vault 디렉토리명.
        dpi:      렌더 해상도 (기본 150).
    """
    aid = normalize_arxiv_id(paper_id)
    if aid is None:
        return f"❌ 유효한 arXiv ID가 아닙니다: {paper_id}"
    if not pdf_exists(aid):
        return f"❌ PDF 캐시 없음: {aid}"
    if page < 1:
        return f"❌ page는 1 이상이어야 합니다: {page}"

    where = slug or aid
    out_dir = config.VAULT_PATH / "papers" / where / "pages"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        doc = pymupdf.open(pdf_path(aid))
        if page > len(doc):
            doc.close()
            return f"❌ 페이지 범위 초과: {page} > {len(doc)}"
        p = doc[page - 1]
        pix = p.get_pixmap(dpi=dpi)
        if pix.n - pix.alpha >= 4:
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        file = out_dir / f"page_{page}.png"
        pix.save(file)
        pix = None
        doc.close()
    except Exception as e:
        return f"❌ 페이지 렌더 오류: {e}"

    return (
        f"📃 page 렌더: arXiv:{aid} page={page} → papers/{where}/pages/page_{page}.png "
        f"({file.stat().st_size // 1024} KB, dpi={dpi})"
    )


def register(mcp) -> None:
    mcp.tool()(download_paper)
    mcp.tool()(read_paper)
    mcp.tool()(extract_paper_figures)
    mcp.tool()(prune_paper_figures)
    mcp.tool()(extract_paper_tables)
    mcp.tool()(prune_paper_tables)
    mcp.tool()(render_paper_page)
