"""테크 블로그 목록/본문 fetch + 파싱 (ADR-030).

소스 레지스트리 (실측 2026-07-13):
- anthropic: RSS 없음 → `/news` HTML anchor 파싱 (anchor 텍스트에 title·날짜 포함).
  본문은 `<article>` 스코프로 깨끗하게 추출됨.
- openai:    공식 RSS. 개별 글 페이지는 403 JS challenge (브라우저 UA로도 차단)
  → `body: False`, RSS description으로만 요약.
- gemini:    blog.google Gemini 제품 RSS (redirect 1회). description에 HTML 섞임.
- deepmind:  공식 RSS. 글 페이지에 `<article>` 없음 → `<main>` fallback.

본문 추출 휴리스틱: script/style 제거 → `<article>` (없으면 `<main>`) 스코프 →
`<p>` 중 80자 이상만 join. 새 의존성 없음 (stdlib re + html + ElementTree).
"""

from __future__ import annotations

import html as html_lib
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from core import cache
from core.http import get

LIST_CACHE_TTL = 6 * 3600  # 목록 6시간 — 신규 글 반영과 재실행 부담의 절충
BODY_CACHE_TTL = 30 * 24 * 3600  # 본문 30일 — 게시 후 사실상 불변

SOURCES: dict[str, dict] = {
    "anthropic": {
        "label": "Anthropic",
        "kind": "anthropic_html",
        "url": "https://www.anthropic.com/news",
        "body": True,
        "domains": ("www.anthropic.com", "anthropic.com"),
    },
    "openai": {
        "label": "OpenAI",
        "kind": "rss",
        "url": "https://openai.com/news/rss.xml",
        "body": False,  # 글 페이지 403 — RSS description만 사용
        "domains": ("openai.com", "www.openai.com"),
    },
    "gemini": {
        "label": "Google Gemini",
        "kind": "rss",
        "url": "https://blog.google/products/gemini/rss/",
        "body": True,
        "domains": ("blog.google",),
    },
    "deepmind": {
        "label": "Google DeepMind",
        "kind": "rss",
        "url": "https://deepmind.google/blog/rss.xml",
        "body": True,
        "domains": ("deepmind.google",),
    },
}

_MIN_PARA_LEN = 80
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(text: str) -> str:
    """태그 제거 + entity unescape + 공백 정규화."""
    return re.sub(r"\s+", " ", html_lib.unescape(_TAG_RE.sub(" ", text))).strip()


def _rfc822_to_iso(text: str) -> str:
    """RSS pubDate (RFC 822) → 'YYYY-MM-DD'. 실패 시 빈 문자열."""
    try:
        return parsedate_to_datetime(text.strip()).date().isoformat()
    except (ValueError, TypeError):
        return ""


def parse_rss(xml_text: str, source: str) -> list[dict]:
    """RSS 2.0 → 표준 post dict 리스트. 파싱 불가면 빈 리스트.

    표준 키: source, title, url, summary(태그 스트립), published(ISO date).
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    posts: list[dict] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        if not title or not url:
            continue
        posts.append(
            {
                "source": source,
                "title": title,
                "url": url,
                "summary": _strip_tags(item.findtext("description") or ""),
                "published": _rfc822_to_iso(item.findtext("pubDate") or ""),
            }
        )
    return posts


_ANTHROPIC_BASE = "https://www.anthropic.com"
_NEWS_ANCHOR_RE = re.compile(r'<a[^>]+href="(/news/[^"#?]+)"[^>]*>(.*?)</a>', re.DOTALL)
_ANTHROPIC_DATE_RE = re.compile(r"[A-Z][a-z]{2} \d{1,2}, \d{4}")


def parse_anthropic_news(html_text: str) -> list[dict]:
    """`/news` HTML의 카드 anchor → post dict. 순서 보존 + href 중복 제거.

    title은 anchor 텍스트 그대로 (카테고리·날짜 문자열 혼재 — 정확한 제목은
    read 시점의 og:title이 담당). published는 anchor 안 'Jun 30, 2026' 패턴.
    """
    posts: list[dict] = []
    seen: set[str] = set()
    for m in _NEWS_ANCHOR_RE.finditer(html_text):
        href, inner = m.groups()
        if href in seen:
            continue
        seen.add(href)
        text = _strip_tags(inner)
        published = ""
        dm = _ANTHROPIC_DATE_RE.search(text)
        if dm:
            try:
                published = datetime.strptime(dm.group(0), "%b %d, %Y").date().isoformat()
            except ValueError:
                pass
        posts.append(
            {
                "source": "anthropic",
                "title": text or href.rsplit("/", 1)[-1],
                "url": _ANTHROPIC_BASE + href,
                "summary": "",
                "published": published,
            }
        )
    return posts


def extract_body(html_text: str, max_chars: int = 12000) -> str:
    """글 페이지 HTML → 본문 문단 텍스트 (요약 입력용).

    script/style 제거 → <article> (없으면 <main>) 스코프 → <p> 80자 이상만.
    본문을 못 찾으면 빈 문자열.
    """
    cleaned = re.sub(
        r"<(script|style)[^>]*>.*?</\1>", "", html_text, flags=re.DOTALL | re.IGNORECASE
    )
    scope = cleaned
    for tag in ("article", "main"):
        m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", cleaned, flags=re.DOTALL | re.IGNORECASE)
        if m:
            scope = m.group(1)
            break
    paras: list[str] = []
    total = 0
    for p in re.findall(r"<p[^>]*>(.*?)</p>", scope, flags=re.DOTALL | re.IGNORECASE):
        text = _strip_tags(p)
        if len(text) < _MIN_PARA_LEN:
            continue
        paras.append(text)
        total += len(text)
        if total >= max_chars:
            break
    return "\n\n".join(paras)[:max_chars]


def extract_og(html_text: str) -> dict:
    """og:title / og:description 메타. 없으면 빈 문자열."""
    out: dict = {}
    for key in ("title", "description"):
        m = re.search(
            rf'<meta[^>]+property="og:{key}"[^>]+content="([^"]*)"', html_text
        ) or re.search(rf'<meta[^>]+content="([^"]*)"[^>]+property="og:{key}"', html_text)
        out[key] = html_lib.unescape(m.group(1)) if m else ""
    return out


def source_for_url(url: str) -> str | None:
    """URL 도메인 → 소스 slug. 미등록 도메인은 None (read_blog_post 허용 범위 제한)."""
    host = urlparse(url).netloc.lower()
    for slug, cfg in SOURCES.items():
        if host in cfg["domains"]:
            return slug
    return None


async def fetch_posts(source: str) -> list[dict]:
    """소스의 목록 endpoint를 fetch(디스크 캐시 경유) 후 표준 post 리스트로 파싱."""
    cfg = SOURCES[source]

    async def _do():
        return await get(cfg["url"])

    text = await cache.get_or_fetch(f"tech_blogs:list:{source}", _do, ttl=LIST_CACHE_TTL)
    if not isinstance(text, str):
        return []
    if cfg["kind"] == "rss":
        return parse_rss(text, source=source)
    return parse_anthropic_news(text)


async def fetch_post_page(url: str) -> str:
    """글 페이지 HTML fetch (디스크 캐시 경유). 본문은 불변이라 TTL 30일."""

    async def _do():
        return await get(url)

    html_text = await cache.get_or_fetch(f"tech_blogs:page:{url}", _do, ttl=BODY_CACHE_TTL)
    return html_text if isinstance(html_text, str) else ""
