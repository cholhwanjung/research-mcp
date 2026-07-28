"""MCP tools: get_tech_blog_posts / read_blog_post / mark_blog_posts_seen (ADR-030).

`tech-blog-digest` 스킬의 입력. seen 상태는 조회(get)와 분리 — 요약을 vault에
저장한 뒤 mark_blog_posts_seen으로 확정해야 다음 실행에서 제외된다.
"""

from __future__ import annotations

from sources import tech_blogs
from wiki.blog_state import mark_seen as _mark_seen, seen_urls as _seen_urls


async def get_tech_blog_posts(limit_per_source: int = 5) -> str:
    """테크 블로그(Anthropic·OpenAI·Google Gemini·DeepMind)의 미요약 신규 포스트를
    소스별 최신순 최대 N개 반환합니다.

    mark_blog_posts_seen으로 처리 완료된 URL은 제외 — 지난 실행 이후 쌓인
    포스트만 나옵니다. 조회만으로 seen 상태는 바뀌지 않습니다.

    Args:
        limit_per_source: 소스당 최대 포스트 수 (기본 5).
    """
    seen = _seen_urls()
    lines = [f"🗞️ Tech Blog 신규 포스트 (소스별 최대 {limit_per_source})"]
    for slug, cfg in tech_blogs.SOURCES.items():
        try:
            posts = await tech_blogs.fetch_posts(slug)
        except Exception as e:
            lines.append(f"\n⚠️ {slug} 수집 실패: {e}")
            continue
        fresh = [p for p in posts if p["url"] not in seen]
        fresh.sort(key=lambda p: p.get("published") or "", reverse=True)
        picked = fresh[:limit_per_source]
        mode = "본문 요약" if cfg["body"] else "RSS 요약 — 본문 차단"
        lines.append(
            f"\n[{slug}] {cfg['label']} — 신규 {len(fresh)}건 중 {len(picked)}건 ({mode})"
        )
        if not picked:
            lines.append("  (신규 없음)")
        for i, p in enumerate(picked, 1):
            pub = f" ({p['published']})" if p.get("published") else ""
            lines.append(f"  [{i}] {p['title']}{pub}\n      {p['url']}")
            if p.get("summary"):
                lines.append(f"      RSS 요약: {p['summary'][:200]}")
    lines.append(
        "\n→ 본문 요약 소스는 read_blog_post(url)로 본문 조회."
        " 요약 저장 완료 후 mark_blog_posts_seen(urls)로 확정."
    )
    return "\n".join(lines)


async def read_blog_post(url: str) -> str:
    """등록된 테크 블로그 글의 본문 텍스트를 반환합니다 (몇 문단 요약의 입력).

    Args:
        url: get_tech_blog_posts 결과의 포스트 URL.
    """
    source = tech_blogs.source_for_url(url)
    if source is None:
        return f"❌ 등록된 테크 블로그 도메인이 아닙니다: {url}"
    cfg = tech_blogs.SOURCES[source]
    if not cfg["body"]:
        return (
            f"❌ {cfg['label']}은 글 페이지가 봇 차단(403)이라 본문을 읽을 수 없습니다.\n"
            "   get_tech_blog_posts의 RSS 요약(description)으로 요약하세요."
        )
    try:
        html_text = await tech_blogs.fetch_post_page(url)
    except Exception as e:
        return f"❌ 페이지 fetch 오류: {e}"
    body = tech_blogs.extract_body(html_text)
    if not body:
        return f"❌ 본문 추출 실패 (페이지 레이아웃 변경 가능성): {url}"
    og = tech_blogs.extract_og(html_text)
    title = og.get("title") or url
    head = f"📰 {title}\n🔗 {url}\n"
    if og.get("description"):
        head += f"한 줄 소개: {og['description']}\n"
    return head + "\n" + body


def mark_blog_posts_seen(urls: list[str]) -> str:
    """요약을 마친 포스트 URL을 seen으로 기록합니다 — 다음 get_tech_blog_posts에서 제외.

    digest 노트 저장이 성공한 뒤에만 호출하세요 (실패 시 호출하면 포스트 유실).

    Args:
        urls: 처리 완료한 포스트 URL 리스트.
    """
    added = _mark_seen(urls)
    return f"✅ seen 기록: 신규 {added}건 (누적 {len(_seen_urls())}건)"


def register(mcp) -> None:
    mcp.tool()(get_tech_blog_posts)
    mcp.tool()(read_blog_post)
    mcp.tool()(mark_blog_posts_seen)
