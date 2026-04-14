"""Hugging Face Daily Papers fetcher ([ADR-006](../docs/ADR.md#adr-006)).

Fallback chain:
1. 비공식 JSON API: `https://huggingface.co/api/daily_papers?date=YYYY-MM-DD`
2. HTML 스크래핑 (stub): `https://huggingface.co/papers?date=YYYY-MM-DD`

비공식 엔드포인트라 응답 형식이 변경되거나 사라질 수 있어 호출은 try/except로 감싸고
실패하거나 빈 결과면 HTML로 graceful degrade. 응답 캐시는 1일 TTL.

표준 출력 dict 키: `arxiv_id`, `title`, `authors` (list[str]), `abstract`, `upvotes`, `url`.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from core import cache
from core.http import get

_API_BASE = "https://huggingface.co/api/daily_papers"
_HTML_BASE = "https://huggingface.co/papers"
_CACHE_TTL = 24 * 3600  # 1일


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _normalize_api_item(item: dict) -> dict:
    """비공식 API 응답의 한 항목 → 표준 dict."""
    paper = item.get("paper") or item
    aid = paper.get("id", "")
    authors = [
        a.get("name", "") if isinstance(a, dict) else str(a)
        for a in (paper.get("authors") or [])
    ]
    return {
        "arxiv_id": aid,
        "title": paper.get("title", ""),
        "authors": authors,
        "abstract": paper.get("summary", ""),
        "upvotes": paper.get("upvotes", 0) or 0,
        "url": f"https://huggingface.co/papers/{aid}" if aid else "",
    }


async def _fetch_api(date: str) -> list[dict]:
    """비공식 API 호출. raw 응답 그대로 반환 (정규화는 호출자)."""
    key = f"hf_daily:api:{date}"

    async def _do():
        return await get(f"{_API_BASE}?date={date}")

    resp = await cache.get_or_fetch(key, _do, ttl=_CACHE_TTL)
    return resp if isinstance(resp, list) else []


# `<a href="/papers/{id}" ...>{title}</a>` 패턴. HF 페이지의 paper card는 anchor 태그 안에 title 직접 포함.
# DOTALL 미사용 — title이 single-line 가정 (실제 HF DOM이 그러함).
_HTML_PAPER_RE = re.compile(
    r'<a[^>]+href="/papers/(\d{4}\.\d{4,5})"[^>]*>([^<]{1,200})</a>'
)


async def _fetch_html(date: str) -> list[dict]:
    """HTML fallback. paper ID + title pair 추출 (옵션 A 보강).

    detail endpoint 추가 호출 없이 paper card anchor tag에서 title 직접 추출.
    authors/abstract/upvotes는 paper detail page를 호출해야 하는데 rate-limit 부담이라
    현재는 빈값 유지 — 필요 시 후속 ADR.
    """
    key = f"hf_daily:html:{date}"

    async def _do():
        return await get(f"{_HTML_BASE}?date={date}")

    html = await cache.get_or_fetch(key, _do, ttl=_CACHE_TTL)
    if not isinstance(html, str):
        return []
    seen: dict[str, str] = {}  # aid → first title
    for m in _HTML_PAPER_RE.finditer(html):
        aid = m.group(1)
        title = m.group(2).strip()
        if aid and aid not in seen:
            seen[aid] = title
    return [
        {
            "arxiv_id": aid,
            "title": title,
            "authors": [],
            "abstract": "",
            "upvotes": 0,
            "url": f"https://huggingface.co/papers/{aid}",
        }
        for aid, title in seen.items()
    ]


async def fetch_daily_papers(date: str | None = None, limit: int = 0) -> list[dict]:
    """HF Daily Papers 수집. date=None이면 오늘(UTC). limit>0이면 상위 N개로 truncate.

    Fallback: API → HTML. 둘 다 실패하면 빈 리스트.
    """
    date = date or _today_utc()
    try:
        raw = await _fetch_api(date)
        papers = [_normalize_api_item(x) for x in raw if isinstance(x, dict)]
    except Exception:
        papers = []
    if not papers:
        try:
            papers = await _fetch_html(date)
        except Exception:
            papers = []
    if limit and limit > 0:
        papers = papers[:limit]
    return papers
