"""신규 hub·탐색 주제 승격을 코드가 쓴다.

hub 노트 frontmatter(tier·title·slug·aliases·parent·related·summary·seed_paper·created_at)와 본문(소속 논문
`[[slug|표기]]`), 소속 논문 → hub 링크, 부모 hub `## 하위 갈래` 줄. 문안은 hub-curator 판정(HubCuration)이
주고 구조·링크는 여기서 고정한다. vault 본문 격리 위반이면 쓰지 않는다.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field

from agent.autopilot.citations import short_title
from agent.autopilot.notes import VaultIsolationError, find_meta_identifiers
from analysis.retrieval import search
from tools.wiki_tools import wiki_link
from wiki.frontmatter import dump_note, parse_note
from wiki.linker import extract_links, read_vault_notes
from wiki.vault import paper_note_path, vault_root, write_note

SUBTOPICS = "하위 갈래"
_TLDR = re.compile(r"^## TL;DR\s*\n+(.+)$", re.MULTILINE)
_SUBTOPIC_CHARS = 120


class MemberLine(BaseModel):
    slug: str
    line: str = ""


class HubCuration(BaseModel):
    """hub-curator 판정 — 소속 논문 선택과 hub 문안."""

    members: list[str] = Field(default_factory=list, description="후보 중 이 hub가 그 논문 자신의 주제인 slug")
    title: str = Field(description="hub 제목(영문 Title-Case, 하이픈)")
    summary: str = Field(description="이 축이 무엇을 묻고 무엇으로 갈리는지 한두 문장")
    aliases: list[str] = Field(default_factory=list, description="영문 kebab-case 동의어")
    intro: str = Field(default="", description="본문 첫 인용구 한 문장")
    member_lines: list[MemberLine] = Field(default_factory=list, description="소속 논문마다 한 줄")
    within_intent: bool = Field(default=False, description="이 주제가 scope 원문의 의도 안에 드는가")
    query: str = Field(default="", description="이 주제를 arXiv에서 찾을 영어 검색어(4~8단어)")


def hub_path(slug: str) -> Path:
    return vault_root() / "topics" / f"{slug}.md"


def paper_brief(slug: str) -> dict | None:
    path = paper_note_path(slug)
    if not path.is_file():
        return None
    fm, body = parse_note(path.read_text(encoding="utf-8"))
    m = _TLDR.search(body)
    return {"slug": slug, "arxiv_id": str(fm.get("arxiv_id") or ""), "title": str(fm.get("title") or slug),
            "year": fm.get("year"), "tldr": m.group(1).strip() if m else ""}


def hub_member_candidates(query: str, *, exclude: set[str] | frozenset[str] = frozenset(), top_k: int = 10) -> list[dict]:
    """어휘로 가까운 논문 노트 — hub 소속 판정 후보."""
    notes = {slug: text for slug, text in read_vault_notes().items() if slug.startswith("papers/")}
    adjacency = {slug: extract_links(text) for slug, text in notes.items()}
    out: list[dict] = []
    for hit in search(query, notes, adjacency, top_k=top_k + len(exclude), expand=False):
        slug = hit.slug.split("/")[-1]
        if slug in exclude:
            continue
        brief = paper_brief(slug)
        if brief:
            out.append(brief)
        if len(out) >= top_k:
            break
    return out


def _one_line(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def add_subtopic(parent: str, slug: str, summary: str) -> bool:
    """부모 hub `## 하위 갈래`에 한 줄. 절이 없으면 `## 관련 hub` 앞(없으면 끝)에 만든다."""
    path = hub_path(parent)
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    if re.search(rf"\[\[{re.escape(slug)}(?:[|#][^\]]*)?\]\]", text):
        return False
    line = f"- [[{slug}]] — {_one_line(summary, _SUBTOPIC_CHARS)}"
    header = re.search(rf"^## {SUBTOPICS}[ \t]*\n", text, re.MULTILINE)
    if header:
        start = header.end()
        nxt = re.search(r"^## ", text[start:], re.MULTILINE)
        section = text[start : start + nxt.start()] if nxt else text[start:]
        bullets = list(re.finditer(r"^- .*$", section, re.MULTILINE))
        if bullets:
            at = start + bullets[-1].end()
            text = text[:at] + "\n" + line + text[at:]
        else:
            text = text[:start] + line + "\n" + text[start:]
    else:
        related = re.search(r"^## 관련 hub[ \t]*$", text, re.MULTILINE)
        block = f"## {SUBTOPICS}\n{line}\n\n"
        text = text[: related.start()] + block + text[related.start():] if related else text.rstrip("\n") + "\n\n" + block.rstrip("\n") + "\n"
    write_note(path, text)
    return True


def create_hub(slug: str, curation: HubCuration, *, parent: str | None, members: list[str], today: date) -> Path | None:
    """hub 노트를 만들고 소속 논문·부모 hub를 잇는다. 이미 있으면 None."""
    path = hub_path(slug)
    if path.exists():
        return None
    lines_by_slug = {m.slug: _one_line(m.line, 300) for m in curation.member_lines if m.line.strip()}
    found = find_meta_identifiers("\n".join([curation.title, curation.summary, curation.intro, *curation.aliases,
                                             *lines_by_slug.values()]))
    if found:
        raise VaultIsolationError(", ".join(found))
    briefs = [b for b in (paper_brief(s) for s in dict.fromkeys(members)) if b]
    body = [f"# {curation.title}", ""]
    if curation.intro.strip():
        body += [f"> {_one_line(curation.intro, 300)}", ""]
    body.append("## 핵심 paper")
    for b in briefs:
        line = f"- [[{b['slug']}|{short_title(b['title'])}]] ({b['year'] or '-'})"
        if lines_by_slug.get(b["slug"]):
            line += f" — {lines_by_slug[b['slug']]}"
        body.append(line)
    body.append("")
    if parent:
        body += ["## 관련 hub", f"- [[{parent}]] — 상위 축", ""]
    fm = {
        "tier": "hub",
        "title": curation.title,
        "slug": slug,
        "aliases": list(dict.fromkeys(a.strip() for a in curation.aliases if a.strip())),
        "parent": parent,
        "related": [parent] if parent else [],
        "summary": _one_line(curation.summary, 400),
        "seed_paper": briefs[0]["arxiv_id"] if briefs else "",
        "created_at": today.isoformat(),
    }
    write_note(path, dump_note(fm, "\n".join(body)))
    for b in briefs:
        wiki_link(b["slug"], slug)
    if parent:
        add_subtopic(parent, slug, curation.summary)
    return path


def add_hub_to_paper(slug: str, hub: str) -> None:
    """논문 frontmatter `topics`에 hub를 더하고 Related 링크를 잇는다."""
    path = paper_note_path(slug)
    fm, body = parse_note(path.read_text(encoding="utf-8"))
    topics = list(fm.get("topics") or [])
    if hub not in topics:
        topics.append(hub)
    fm["topics"] = topics
    write_note(path, dump_note(fm, body))
    wiki_link(slug, hub)
