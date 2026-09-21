"""요약 에이전트에 줄 읽기 컨텍스트를 코드가 모은다.

hub 정의·alias·parent(태깅 근거), scope 안 탐색 주제 정의, vault에서 어휘로 찾은 관련 노트
몇 편(통찰 후보의 근거). 에이전트에 vault 검색 도구를 주지 않고 결정론으로 골라 넣어 요청 수를
늘리지 않는다. 논문 본문은 신뢰 경계 표지로 감싸 프롬프트에 넣는다(`agents.reader_prompt`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from agent.autopilot.topics import Topic
from analysis.retrieval import search
from wiki.frontmatter import parse_note
from wiki.linker import extract_links, read_vault_notes

_RELATED_DIRS = ("papers/", "topics/", "notes/")
_SNIPPET_CHARS = 160
_TLDR = re.compile(r"^## TL;DR\s*\n+(.+)$", re.MULTILINE)


@dataclass
class ReadContext:
    source_text: str = ""
    hub_lines: list[str] = field(default_factory=list)
    topic_lines: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    anchor_lines: list[str] = field(default_factory=list)


def hub_lines(hubs: list[dict]) -> list[str]:
    lines: list[str] = []
    for hub in hubs:
        slug = str(hub["slug"])
        line = slug
        title = hub.get("title")
        if title and title != slug:
            line += f" ({title})"
        if hub.get("summary"):
            line += f" — {hub['summary']}"
        meta = []
        if hub.get("aliases"):
            meta.append("aliases: " + ", ".join(str(a) for a in hub["aliases"]))
        if hub.get("parent"):
            meta.append(f"parent: {hub['parent']}")
        if meta:
            line += " | " + " | ".join(meta)
        lines.append(line)
    return lines


def topic_lines(topics: list[Topic]) -> list[str]:
    return [f"{t.slug} — {t.definition}" for t in topics]


def _snippet(content: str) -> str:
    try:
        fm, body = parse_note(content)
    except Exception:
        fm, body = {}, content
    m = _TLDR.search(body)
    if m:
        text = m.group(1)
    elif isinstance(fm, dict) and fm.get("summary"):
        text = str(fm["summary"])
    else:
        text = next((line for line in body.splitlines() if line.strip() and not line.startswith("#")), "")
    text = " ".join(text.split())
    return text if len(text) <= _SNIPPET_CHARS else text[: _SNIPPET_CHARS - 1] + "…"


def related_notes(query: str, *, exclude: set[str] | frozenset[str] = frozenset(), top_k: int = 5) -> list[str]:
    """`papers/`·`topics/`·`notes/`에서 어휘로 가까운 노트 — `<이름> — <TL;DR 또는 summary>` 줄."""
    notes = {slug: text for slug, text in read_vault_notes().items() if slug.startswith(_RELATED_DIRS)}
    if not notes:
        return []
    adjacency = {slug: extract_links(text) for slug, text in notes.items()}
    out: list[str] = []
    for hit in search(query, notes, adjacency, top_k=top_k + len(exclude), expand=False):
        name = hit.slug.split("/")[-1]
        if name in exclude:
            continue
        out.append(f"{name} — {_snippet(notes[hit.slug])}")
        if len(out) >= top_k:
            break
    return out
