"""arXiv ATOM 파서 + PDF 다운로드.

`parse_arxiv`: server.py의 _parse_arxiv 이전 (Phase 1.2).
`normalize_arxiv_id` + `download_pdf`: Phase 2.2 — PDF persistence 지원.
"""

from __future__ import annotations

import re

import aiohttp

from core.slug import is_arxiv_id


def normalize_arxiv_id(paper_id: str) -> str | None:
    """입력에서 `ARXIV:` prefix 제거 + 형식 검증. 유효하지 않으면 None."""
    paper_id = paper_id.strip()
    if paper_id.upper().startswith("ARXIV:"):
        paper_id = paper_id[6:]
    if not is_arxiv_id(paper_id):
        return None
    return paper_id


def build_pdf_url(arxiv_id: str) -> str:
    """arXiv PDF URL. D-12: HTTPS + `.pdf` suffix (arxiv 공식 권장)."""
    return f"https://arxiv.org/pdf/{arxiv_id}.pdf"


async def download_pdf(arxiv_id: str, timeout: int = 60) -> bytes:
    """arxiv.org/pdf/<id>.pdf에서 PDF bytes 다운로드. 실패 시 RuntimeError."""
    url = build_pdf_url(arxiv_id)
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            if resp.status != 200:
                raise RuntimeError(f"PDF 다운로드 실패 (HTTP {resp.status}): {url}")
            return await resp.read()


def parse_arxiv(xml: str) -> list[dict]:
    papers = []
    for entry in xml.split("<entry>")[1:]:

        def _tag(tag: str) -> str:
            m = re.search(f"<{tag}[^>]*>(.*?)</{tag}>", entry, re.DOTALL)
            return m.group(1).strip().replace("\n", " ") if m else ""

        arxiv_id = ""
        id_text = _tag("id")
        if "/abs/" in id_text:
            arxiv_id = id_text.split("/abs/")[-1]

        url, pdf = "", ""
        for m in re.finditer(r'<link[^>]*href="([^"]*)"[^>]*(?:title="([^"]*)")?', entry):
            href, title = m.groups()
            if title == "pdf":
                pdf = href
            elif "abs" in href:
                url = href

        title = _tag("title")
        abstract = _tag("summary")
        if title and abstract:
            papers.append(
                {
                    "arxiv_id": arxiv_id,
                    "title": title,
                    "authors": re.findall(r"<n>(.+?)</n>", entry)[:5],
                    "abstract": abstract,
                    "url": url or f"https://arxiv.org/abs/{arxiv_id}",
                    "pdf_url": pdf,
                    "published": _tag("published")[:10],
                    "categories": re.findall(r'<category[^>]*term="([^"]*)"', entry)[:5],
                }
            )
    return papers
