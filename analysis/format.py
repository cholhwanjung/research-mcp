"""논문 dict → 한국어 가독성 텍스트. server.py의 _fmt_paper를 그대로 이전 (Phase 1.3a)."""

from __future__ import annotations


def fmt_paper(p: dict, abstract: bool = True) -> str:
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
