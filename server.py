import asyncio
import re
import urllib.parse
from datetime import datetime, timezone

import aiohttp
import pymupdf
from fastmcp import FastMCP

mcp = FastMCP("Research Agent")

# ─── Constants ─────────────────────────────────────────────

SS_BASE = "https://api.semanticscholar.org/graph/v1/paper"

# ─── Helpers ───────────────────────────────────────────────


async def _get(url: str, params: dict | None = None) -> dict | str:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url, params=params, timeout=aiohttp.ClientTimeout(total=30)
        ) as resp:
            if resp.content_type == "application/json":
                return await resp.json()
            return await resp.text()


def _resolve_id(paper_id: str) -> str:
    """다양한 입력 형식을 Semantic Scholar API 형식으로 정규화."""
    paper_id = paper_id.strip()
    upper = paper_id.upper()

    if upper.startswith("ARXIV:"):
        return f"ARXIV:{paper_id[6:]}"
    if upper.startswith("DOI:"):
        return f"DOI:{paper_id[4:]}"
    if upper.startswith("CORPUSID:"):
        return f"CorpusId:{paper_id[9:]}"
    if upper.startswith("MAG:"):
        return f"MAG:{paper_id[4:]}"
    if upper.startswith("ACL:"):
        return f"ACL:{paper_id[4:]}"
    if upper.startswith("PMID:"):
        return f"PMID:{paper_id[5:]}"
    if upper.startswith("PMCID:"):
        return f"PMCID:{paper_id[6:]}"
    if re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", paper_id):
        return f"ARXIV:{paper_id}"
    if paper_id.startswith("10."):
        return f"DOI:{paper_id}"
    if re.match(r"^[0-9a-fA-F]{40}$", paper_id):
        return paper_id
    return paper_id


def _parse_arxiv(xml: str) -> list[dict]:
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


def _fmt_paper(p: dict, abstract: bool = True) -> str:
    """논문 dict를 가독성 있는 문자열로 포맷."""
    lines = [f"📄 {p.get('title', 'Untitled')}"]
    authors = p.get("authors", [])
    if authors:
        names = [x.get("name", "") if isinstance(x, dict) else x for x in authors[:5]]
        lines.append(f"   Authors: {', '.join(names)}")
    year = p.get("year") or p.get("published", "")
    if year:
        lines.append(f"   Year: {year}")
    if p.get("venue"):
        lines.append(f"   Venue: {p['venue']}")
    if p.get("citationCount") is not None:
        ic = p.get("influentialCitationCount")
        ic_str = f" (influential: {ic})" if ic is not None else ""
        lines.append(f"   Citations: {p['citationCount']}{ic_str}")
    aid = p.get("arxiv_id") or (p.get("externalIds") or {}).get("ArXiv", "")
    url = f"https://arxiv.org/abs/{aid}" if aid else p.get("url", "")
    if url:
        lines.append(f"   🔗 {url}")
    if abstract and p.get("abstract"):
        ab = p["abstract"]
        lines.append(f"   Abstract: {ab[:500]}..." if len(ab) > 500 else f"   Abstract: {ab}")
    return "\n".join(lines)


async def _fetch_network_papers(
    pid: str,
    endpoint: str,
    item_key: str,
    max_fetch: int,
    sleep_sec: float = 1.5,
) -> list[dict]:
    """SS API offset 기반 페이지네이션으로 citations 또는 references 전량 수집.

    공식 문서 기준:
    - limit 최대 1000 (한 번 요청에 1000개 초과 불가)
    - 응답의 'next' 필드가 다음 offset; 없으면 마지막 페이지
    """
    FIELDS = "title,authors,year,citationCount,influentialCitationCount,externalIds,url,venue"
    BATCH = 1000  # API 허용 최대값
    all_papers: list[dict] = []
    offset = 0

    while len(all_papers) < max_fetch:
        limit = min(BATCH, max_fetch - len(all_papers))
        resp = await _get(
            f"{SS_BASE}/{pid}/{endpoint}",
            {"fields": FIELDS, "limit": str(limit), "offset": str(offset)},
        )
        if not isinstance(resp, dict):
            break

        items = [
            c[item_key]
            for c in (resp.get("data") or [])
            if c.get(item_key, {}).get("title")
        ]
        if not items:
            break

        all_papers.extend(items)

        # 'next' 필드가 없으면 마지막 페이지 → 종료
        next_offset = resp.get("next")
        if next_offset is None:
            break

        offset = next_offset
        await asyncio.sleep(sleep_sec)

    return all_papers


def _render_sorted_list(
    papers: list[dict],
    header: str,
    total: int,
    fetched: int,
    top_k: int,
) -> str:
    """citationCount 기준 내림차순 정렬 후 포맷."""
    sorted_papers = sorted(
        papers, key=lambda p: p.get("citationCount") or 0, reverse=True
    )[:top_k]

    lines = [
        header,
        f"   전체: {total} / 수집: {fetched} / 표시: 상위 {len(sorted_papers)}편",
        "",
    ]
    for i, p in enumerate(sorted_papers, 1):
        ext = p.get("externalIds") or {}
        aid = ext.get("ArXiv", "")
        url_str = f"https://arxiv.org/abs/{aid}" if aid else p.get("url", "")
        authors = p.get("authors") or []
        first = authors[0].get("name", "") if authors and isinstance(authors[0], dict) else (authors[0] if authors else "-")
        lines.append(
            f"[{i}] {p.get('title', 'Untitled')}\n"
            f"     1저자: {first}  "
            f"년도: {p.get('year', '-')}  "
            f"venue: {p.get('venue', '-')}\n"
            f"     citations: {p.get('citationCount')}  "
            f"influential: {p.get('influentialCitationCount')}\n"
            f"     🔗 {url_str}"
        )
    return "\n".join(lines)


# ─── 5 Tools ───────────────────────────────────────────────


@mcp.tool()
async def search_papers(
    query: str,
    max_results: int = 20,
    category: str = "",
) -> str:
    """주제/키워드로 arXiv에서 논문을 검색합니다.
    결과는 관련도 순으로 정렬되며, 최근 1년 / 3년 / 5년 이내로 분류해 반환합니다.

    Args:
        query:       검색 키워드 (예: "vision language model", "contrastive learning")
        max_results: 최대 논문 수 (기본 20, 최대 50)
        category:    arXiv 카테고리 필터 (예: "cs.CV"). 비우면 전체 검색.
    """
    max_results = min(max_results, 50)
    search = f"all:{query}"
    if category:
        search = f"cat:{category}+AND+{search}"

    url = "http://export.arxiv.org/api/query?" + urllib.parse.urlencode(
        {
            "search_query": search,
            "sortBy": "relevance",
            "sortOrder": "descending",
            "max_results": str(max_results),
        },
        safe=":+",
    )

    xml = await _get(url)
    if not isinstance(xml, str):
        return "❌ arXiv API 응답 오류"

    papers = _parse_arxiv(xml)
    if not papers:
        return f"'{query}'에 대한 검색 결과가 없습니다."

    now = datetime.now(timezone.utc)

    def _year_diff(published: str) -> float:
        try:
            pub_dt = datetime.strptime(published[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return (now - pub_dt).days / 365.25
        except Exception:
            return float("inf")

    buckets: dict[str, list] = {"1y": [], "3y": [], "5y": [], "old": []}
    for p in papers:
        diff = _year_diff(p.get("published", ""))
        key = "1y" if diff <= 1 else "3y" if diff <= 3 else "5y" if diff <= 5 else "old"
        buckets[key].append(p)

    lines = [f"🔍 '{query}' 검색 결과 ({len(papers)}편) — 관련도 순 정렬\n"]

    bucket_meta = [
        ("1y",  "📅 최근 1년 이내"),
        ("3y",  "📅 1년 ~ 3년 이내"),
        ("5y",  "📅 3년 ~ 5년 이내"),
        ("old", "📦 5년 초과"),
    ]
    for key, label in bucket_meta:
        bucket = buckets[key]
        if not bucket:
            continue
        lines.append(f"{label} ({len(bucket)}편)")
        lines.append("─" * 60)
        for i, p in enumerate(bucket, 1):
            lines.append(f"[{i}] {_fmt_paper(p)}\n")

    return "\n".join(lines)


@mcp.tool()
async def get_paper_by_id(paper_id: str) -> str:
    """논문 ID로 상세 정보를 조회합니다.
    arXiv ID, DOI, Semantic Scholar ID를 모두 지원합니다.

    Args:
        paper_id: arXiv ID (예: "2301.12597"), DOI (예: "10.48550/arXiv.2301.12597"),
                  또는 Semantic Scholar SHA ID.
    """
    fields = (
        "title,authors,abstract,url,year,venue,citationCount,"
        "referenceCount,influentialCitationCount,fieldsOfStudy,"
        "publicationTypes,externalIds,tldr"
    )
    data = await _get(f"{SS_BASE}/{_resolve_id(paper_id)}", {"fields": fields})

    if isinstance(data, str) or "paperId" not in data:
        return f"❌ 논문을 찾을 수 없습니다: {paper_id}"

    lines = [f"📄 {data.get('title', 'Untitled')}\n"]

    authors = data.get("authors", [])
    if authors:
        lines.append(f"Authors: {', '.join(a.get('name', '') for a in authors[:10])}")
    if data.get("year"):
        lines.append(f"Year: {data['year']}")
    if data.get("venue"):
        lines.append(f"Venue: {data['venue']}")
    if data.get("fieldsOfStudy"):
        lines.append(f"Fields: {', '.join(data['fieldsOfStudy'])}")

    lines.append(f"Citations: {data.get('citationCount', 0)}")
    lines.append(f"Influential Citations: {data.get('influentialCitationCount', 0)}")
    lines.append(f"References: {data.get('referenceCount', 0)}")

    tldr = data.get("tldr")
    if tldr and tldr.get("text"):
        lines.append(f"\n💡 TL;DR: {tldr['text']}")

    if data.get("abstract"):
        lines.append(f"\n📝 Abstract:\n{data['abstract']}")

    ext = data.get("externalIds") or {}
    if ext.get("ArXiv"):
        lines.append(f"\n🔗 arXiv: https://arxiv.org/abs/{ext['ArXiv']}")
    if ext.get("DOI"):
        lines.append(f"🔗 DOI: https://doi.org/{ext['DOI']}")
    if data.get("url"):
        lines.append(f"🔗 Semantic Scholar: {data['url']}")

    return "\n".join(lines)


@mcp.tool()
async def read_paper(paper_id: str, max_pages: int = 0) -> str:
    """arXiv 논문 PDF를 다운로드하고 전체 텍스트를 추출합니다.
    추출된 텍스트를 바탕으로 요약, 질의응답 등에 활용할 수 있습니다.

    Args:
        paper_id:  arXiv ID (예: "2301.12597"). 'v1' 등 버전 접미사 포함 가능.
        max_pages: 추출할 최대 페이지 수. 0이면 전체 (기본: 0).
    """
    paper_id = paper_id.strip()
    if paper_id.upper().startswith("ARXIV:"):
        paper_id = paper_id[6:]

    if not re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", paper_id):
        return f"❌ 유효한 arXiv ID가 아닙니다: {paper_id}\n   예시: 2301.12597"

    pdf_url = f"https://arxiv.org/pdf/{paper_id}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(pdf_url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status != 200:
                    return f"❌ PDF 다운로드 실패 (HTTP {resp.status}): {pdf_url}"
                pdf_bytes = await resp.read()
    except Exception as e:
        return f"❌ PDF 다운로드 오류: {e}"

    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
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
        return f"❌ 텍스트를 추출할 수 없습니다 (스캔된 이미지 PDF일 수 있음): {paper_id}"

    header = (
        f"📄 arXiv:{paper_id} 전문 ({pages_to_read}/{total_pages} 페이지)\n"
        f"🔗 {pdf_url}\n"
    )
    if max_pages > 0 and max_pages < total_pages:
        header += f"⚠️ max_pages={max_pages} 설정으로 처음 {max_pages}페이지만 추출됨\n"

    return f"{header}\n" + "\n\n".join(text_parts)


@mcp.tool()
async def get_references_by_citations(
    paper_id: str,
    top_k: int = 20,
) -> str:
    """논문이 참조(reference)한 논문들을 인용수(citationCount) 기준으로 정렬해 반환합니다.
    해당 논문이 어떤 중요 선행 연구에 기반하는지 파악할 때 사용합니다.

    Args:
        paper_id: arXiv ID (예: "2301.12597"), DOI, 또는 Semantic Scholar ID.
        top_k:    반환할 상위 논문 수 (기본 20).
    """
    detail = await _get(
        f"{SS_BASE}/{_resolve_id(paper_id)}",
        {"fields": "paperId,title,referenceCount"},
    )
    if isinstance(detail, str) or "paperId" not in detail:
        return f"❌ 논문을 찾을 수 없습니다: {paper_id}"

    pid = detail["paperId"]
    paper_title = detail.get("title", paper_id)
    total = detail.get("referenceCount", 0)

    refs = await _fetch_network_papers(pid, "references", "citedPaper", max_fetch=500)

    if not refs:
        return f"'{paper_title}'의 reference 논문을 가져올 수 없습니다."

    return _render_sorted_list(
        refs,
        f"📤 '{paper_title}' — Reference 논문 (인용수 순 정렬)",
        total,
        len(refs),
        top_k,
    )


@mcp.tool()
async def get_citations_by_citations(
    paper_id: str,
    top_k: int = 20,
    max_fetch: int = 1000,
) -> str:
    """논문을 인용(citation)한 후속 연구들을 인용수(citationCount) 기준으로 정렬해 반환합니다.
    가장 영향력 있는 후속 연구를 파악할 때 사용합니다.

    SS API는 최신순으로 반환하므로 max_fetch를 충분히 크게 설정해야
    오래된 핵심 후속 연구까지 수집할 수 있습니다.

    Args:
        paper_id:  arXiv ID (예: "2304.08485"), DOI, 또는 Semantic Scholar ID.
        top_k:     반환할 상위 논문 수 (기본 20).
        max_fetch: 최대 수집 citation 수 (기본 1000).
    """
    detail = await _get(
        f"{SS_BASE}/{_resolve_id(paper_id)}",
        {"fields": "paperId,title,citationCount"},
    )
    if isinstance(detail, str) or "paperId" not in detail:
        return f"❌ 논문을 찾을 수 없습니다: {paper_id}"

    pid = detail["paperId"]
    paper_title = detail.get("title", paper_id)
    total = detail.get("citationCount", 0)

    cits = await _fetch_network_papers(
        pid, "citations", "citingPaper", max_fetch=max_fetch
    )

    if not cits:
        return f"'{paper_title}'의 인용 논문을 가져올 수 없습니다."

    return _render_sorted_list(
        cits,
        f"📥 '{paper_title}' — Citation 논문 (인용수 순 정렬)",
        total,
        len(cits),
        top_k,
    )


if __name__ == "__main__":
    mcp.run()
