"""arXiv ATOM 파서 + PDF 다운로드.

`parse_arxiv`: server.py의 _parse_arxiv 이전 (Phase 1.2).
`normalize_arxiv_id` + `download_pdf`: Phase 2.2 — PDF persistence 지원.
`fetch_dates`: 게시일·수정일 조회 (ADR-079).
"""

from __future__ import annotations

import asyncio
import re

import aiohttp

from core import cache
from core.http import get as _get
from core.slug import is_arxiv_id

ARXIV_API = "https://export.arxiv.org/api/query"
ARXIV_DATES_TTL = 7 * 24 * 3600  # 새 버전이 올라오면 revised가 바뀐다 — SS 메타 캐시와 같은 주기
# 날짜는 부가 정보다. export.arxiv.org는 rate limit 시 40~57초를 끌므로 재시도까지 합쳐 이 시간에 끊는다.
ARXIV_DATES_TIMEOUT = 10


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
                    "updated": _tag("updated")[:10],
                    "categories": re.findall(r'<category[^>]*term="([^"]*)"', entry)[:5],
                }
            )
    return papers


async def fetch_dates(arxiv_id: str) -> dict | None:
    """arXiv `id_list` 1건 조회 → `{published, revised, version}` (ADR-079). 디스크 캐시 경유.

    published는 v1 제출일, revised는 최신 버전 제출일(v1뿐이면 둘이 같다), version은 `v2` 형식.
    arXiv가 시간 안에 응답하지 않거나 피드가 아니면 None — 일시적 응답은 캐시하지 않는다.
    """
    url = f"{ARXIV_API}?id_list={arxiv_id}"
    try:
        xml = await cache.get_or_fetch(
            url,
            lambda: asyncio.wait_for(_get(url), ARXIV_DATES_TIMEOUT),
            ttl=ARXIV_DATES_TTL,
            cache_if=lambda v: isinstance(v, str) and "<entry>" in v,
        )
    except asyncio.TimeoutError:
        return None
    entries = parse_arxiv(xml) if isinstance(xml, str) else []
    if not entries:
        return None
    entry = entries[0]
    version = re.search(r"v\d+$", entry["arxiv_id"])
    return {
        "published": entry["published"],
        "revised": entry["updated"],
        "version": version.group(0) if version else "",
    }
