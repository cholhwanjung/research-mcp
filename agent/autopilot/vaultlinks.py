"""vault 노트 사이의 링크·인용 항목 — 대기열 후보를 뽑고, 방금 들어온 논문으로 링크를 정정한다.

- 깨진 wikilink(S1): `_meta/` 출처 제외. 등급은 통찰 노트의 열린 질문이 부르면 P1, hub 본문이면 P2, 논문·통찰 노트면
  P3, 그 밖(다이제스트 등)만이면 P4. 같은 줄의 arXiv ID와 링크 표기를 모은다. scope 실행이면 참조 노트가 scope 소속
  이거나 소속이 없는 노트일 때만(제목은 scope 게이트가 본다).
- hub 본문의 평문 논문 이름(S2): 이름 추출 판정을 hub 본문 해시로 캐시한다(본문이 바뀌면 다시 뽑는다).
- 링크 정정: 이 논문을 가리키던 깨진 링크 → `[[slug|표기]]`(frontmatter 바이트 보존), scope hub 본문의 평문 이름 첫 언급
  → `[[slug|표기]]`(이미 그 논문을 링크한 hub는 건드리지 않는다).
- anchor 관계 확정: anchor 노트 `cited_by`의 그 논문 항목을 갱신(seed 때 붙인 유용도는 보존).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from agent.autopilot.queue import Candidate
from agent.autopilot.screening import scope_members
from analysis.linkgraph import build_link_graph
from core.slug import is_arxiv_id
from wiki.frontmatter import dump_note, parse_note
from wiki.linker import extract_links, read_vault_notes
from wiki.vault import resolve_paper_by_arxiv_id, vault_root, write_note

_USEFUL = re.compile(r"\s·\s유용\s(상|중|하)\s*$")
_ARXIV = re.compile(r"(?<![\d.])(\d{4}\.\d{4,5})(?:v\d+)?(?![\d.])")
_LINK = re.compile(r"\[\[[^\]]*\]\]")
_OPEN_QUESTIONS = re.compile(r"^## 열린 질문[ \t]*\n(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)
_ASCII_WORD = "A-Za-z0-9_\\-"
_PLAIN_CACHE: dict[tuple[str, str, str], list["PlainName"]] = {}


class PlainName(BaseModel):
    name: str = Field(description="hub 본문 표기 그대로")
    arxiv_id: str = Field(default="", description="본문에 arXiv ID가 함께 적혀 있으면")
    in_vault_slug: str = Field(default="", description="vault 논문 목록 중 같은 논문이면 그 slug")


class PlainNames(BaseModel):
    entries: list[PlainName] = Field(default_factory=list)


@dataclass
class LinkRef:
    target: str
    sources: list[str] = field(default_factory=list)
    surface: str = ""
    arxiv_id: str | None = None
    line: str = ""


def normalize_name(text: str) -> str:
    return re.sub(r"[\W_]+", "", str(text).lower())


def _body_split(text: str) -> tuple[str, str]:
    """(frontmatter 원문, 본문) — frontmatter 바이트를 그대로 되돌리려고 나눈다."""
    _, body = parse_note(text)
    return text[: len(text) - len(body)], body


def _note_path(slug: str):
    return vault_root() / f"{slug}.md" if "/" in slug else vault_root() / "papers" / slug / "index.md"


def _graph():
    notes = read_vault_notes()
    return notes, build_link_graph(notes, {slug: extract_links(text) for slug, text in notes.items()})


def broken_link_refs() -> list[LinkRef]:
    notes, graph = _graph()
    refs: dict[str, LinkRef] = {}
    for src in sorted(graph.broken):
        if src.startswith("_meta/"):
            continue
        for target in graph.broken[src]:
            ref = refs.setdefault(target, LinkRef(target=target, surface=target))
            ref.sources.append(src)
            for line in notes[src].splitlines():
                at = line.find(f"[[{target}")
                if at == -1:
                    continue
                alias = re.search(rf"\[\[{re.escape(target)}\|([^\]]+)\]\]", line)
                if alias and ref.surface == target:
                    ref.surface = alias.group(1)
                found = _ARXIV.search(line, at) or _ARXIV.search(line)
                if found and ref.arxiv_id is None:
                    ref.arxiv_id, ref.line = found.group(1), line.strip()
                elif not ref.line:
                    ref.line = line.strip()
    return list(refs.values())


def _topics_of(text: str) -> set[str]:
    try:
        fm, _ = parse_note(text)
    except Exception:
        return set()
    raw = fm.get("topics") if isinstance(fm, dict) else None
    return {str(t).strip().strip("'\"").strip("[]") for t in raw or []}


def _membership(src: str, text: str, members: set[str]) -> bool | None:
    """참조 노트가 scope 소속인가. 소속을 따질 수 없는 노트(다이제스트 등)는 None."""
    if src.startswith("topics/"):
        return src.split("/")[-1] in members
    if src.startswith("papers/") or "/" not in src:
        return bool(_topics_of(text) & members)
    if src.startswith("notes/"):
        topics = _topics_of(text)
        return bool(topics & members) if topics else None
    return None


def _rank(ref: LinkRef, notes: dict[str, str]) -> str:
    ranks = []
    for src in ref.sources:
        if src.startswith("notes/") and any(f"[[{ref.target}" in m.group(1) for m in _OPEN_QUESTIONS.finditer(notes[src])):
            ranks.append("P1")
        elif src.startswith("topics/"):
            ranks.append("P2")
        elif src.startswith(("papers/", "notes/")) or "/" not in src:
            ranks.append("P3")
        else:
            ranks.append("P4")
    return min(ranks)


def s1_candidates(scope: list[str], hubs: list[dict]) -> list[Candidate]:
    members = scope_members(scope, hubs)
    notes, _ = _graph()
    out: list[Candidate] = []
    for ref in broken_link_refs():
        if members is not None and not any(_membership(s, notes[s], members) is not False for s in ref.sources):
            continue
        arxiv_id = ref.arxiv_id or (ref.target if is_arxiv_id(ref.target) else None)
        out.append(Candidate(key=ref.target, arxiv_id=arxiv_id, source="S1", rank=_rank(ref, notes), refs=len(ref.sources),
                             line=ref.line))
    out.sort(key=lambda c: (c.rank, -c.refs))
    return out


def vault_paper_details() -> list[tuple[str, str, str, list[str], float]]:
    """(slug, 제목, arXiv ID, topics, velocity) — `papers/<slug>/<slug>.md` 전수."""
    base = vault_root() / "papers"
    out: list[tuple[str, str, str, list[str], float]] = []
    if not base.is_dir():
        return out
    for folder in sorted(base.iterdir()):
        note = folder / f"{folder.name}.md"
        if note.is_file():
            try:
                fm, _ = parse_note(note.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
            fm = fm if isinstance(fm, dict) else {}
            try:
                velocity = float(fm.get("citation_velocity") or 0.0)
            except (TypeError, ValueError):
                velocity = 0.0
            out.append((folder.name, str(fm.get("title") or folder.name), str(fm.get("arxiv_id") or ""),
                        [str(t).strip("[]") for t in fm.get("topics") or []], velocity))
    return out


def vault_papers() -> list[tuple[str, str, str]]:
    """(slug, 제목, arXiv ID)."""
    return [(slug, title, aid) for slug, title, aid, _, _ in vault_paper_details()]


def _paper_titles() -> list[tuple[str, str]]:
    return [(slug, title) for slug, title, _ in vault_papers()]


def scope_hub_slugs(scope: list[str], hubs: list[dict]) -> list[str]:
    members = scope_members(scope, hubs)
    return [h["slug"] for h in hubs if members is None or h["slug"] in members]


async def s2_candidates(deps, scope: list[str], hubs: list[dict]) -> list[Candidate]:
    """scope hub 본문이 평문으로 부르는 미수록 논문 — 추출 판정은 hub 본문 해시로 캐시한다."""
    extract = getattr(deps, "extract_plain_names", None)
    if extract is None:
        return []
    titles = None
    found: dict[str, Candidate] = {}
    for slug in scope_hub_slugs(scope, hubs):
        path = vault_root() / "topics" / f"{slug}.md"
        if not path.is_file():
            continue
        _, body = _body_split(path.read_text(encoding="utf-8"))
        key = (str(vault_root()), slug, hashlib.sha1(body.encode("utf-8")).hexdigest())
        if key not in _PLAIN_CACHE:
            titles = titles if titles is not None else _paper_titles()
            _PLAIN_CACHE[key] = list((await extract(slug, body, titles)).entries)
        for entry in _PLAIN_CACHE[key]:
            name = " ".join(entry.name.split())
            if not name or entry.in_vault_slug:
                continue
            arxiv_id = entry.arxiv_id.strip() if is_arxiv_id(entry.arxiv_id.strip()) else None
            cand = found.setdefault(arxiv_id or name, Candidate(key=name, arxiv_id=arxiv_id, source="S2", rank="P2",
                                                                via=slug, line=name))
            cand.refs += 1
    return list(found.values())


def plain_surfaces(arxiv_id: str) -> set[str]:
    """캐시된 hub 평문 이름 중 이 논문을 가리키는 표기."""
    root = str(vault_root())
    return {e.name for (r, _, _), entries in _PLAIN_CACHE.items() if r == root for e in entries if e.arxiv_id == arxiv_id}


def fix_links_to(slug: str, title: str, arxiv_id: str, *, extra: list[str] | tuple[str, ...] = ()) -> int:
    """이 논문을 가리키던 깨진 링크를 `[[slug|표기]]`로 바꾼다. `_meta/` 제외. 바꾼 링크 수."""
    head = title.split(":", 1)[0]
    aliases = {normalize_name(x) for x in (slug, title, head, arxiv_id, *extra) if x and normalize_name(x)}
    _, graph = _graph()
    fixed = 0
    for src, targets in graph.broken.items():
        hits = [t for t in targets if normalize_name(t) in aliases]
        if src.startswith("_meta/") or not hits:
            continue
        path = _note_path(src)
        if not path.is_file():
            continue
        head_text, body = _body_split(path.read_text(encoding="utf-8"))
        for target in hits:
            body, n = re.subn(rf"\[\[{re.escape(target)}(?:\|([^\]]*))?\]\]",
                              lambda m, t=target: f"[[{slug}|{m.group(1) or t}]]", body)
            fixed += n
        write_note(path, head_text + body)
    return fixed


def link_plain_names(hub_slugs: list[str], slug: str, surfaces: list[str] | set[str]) -> int:
    """scope hub 본문에서 이 논문 이름의 첫 평문 언급을 링크한다. 이미 이 논문을 링크한 hub는 건너뛴다."""
    names = sorted({" ".join(s.split()) for s in surfaces if len(" ".join(s.split())) >= 3}, key=len, reverse=True)
    fixed = 0
    for hub in hub_slugs:
        path = vault_root() / "topics" / f"{hub}.md"
        if not path.is_file():
            continue
        head_text, body = _body_split(path.read_text(encoding="utf-8"))
        if re.search(rf"\[\[{re.escape(slug)}(?:[|#][^\]]*)?\]\]", body):
            continue
        changed = False
        for name in names:
            spans = [(m.start(), m.end()) for m in _LINK.finditer(body)]
            pattern = re.compile(rf"(?<![{_ASCII_WORD}]){re.escape(name)}(?![{_ASCII_WORD}])")
            for m in pattern.finditer(body):
                line_start = body.rfind("\n", 0, m.start()) + 1
                if body.startswith("#", line_start) or any(a <= m.start() < b for a, b in spans):
                    continue
                body = body[: m.start()] + f"[[{slug}|{name}]]" + body[m.end():]
                fixed += 1
                changed = True
                break
            if changed:
                break
        if changed:
            write_note(path, head_text + body)
    return fixed


def update_cited_by_entry(anchor_id: str, paper_id: str, *, hubs: list[str], abstract_summary: str,
                          cited_for: str) -> str | None:
    """anchor 노트의 cited_by 항목을 갱신(없으면 추가)하고 anchor slug를 돌려준다. anchor 노트가 없으면 None."""
    path = resolve_paper_by_arxiv_id(anchor_id)
    if path is None:
        return None
    fm, body = parse_note(path.read_text(encoding="utf-8"))
    entries = fm.get("cited_by") if isinstance(fm.get("cited_by"), list) else []
    existing = next((e for e in entries if isinstance(e, dict) and str(e.get("paper_id")) == str(paper_id)), None)
    useful = _USEFUL.search(str(existing.get("cited_for") or "")) if existing else None
    if useful and not _USEFUL.search(cited_for):
        cited_for = f"{cited_for} · 유용 {useful.group(1)}"
    entry = {"paper_id": paper_id, "hubs": list(hubs), "abstract_summary": abstract_summary, "cited_for": cited_for}
    if existing is not None:
        existing.clear()
        existing.update(entry)
    else:
        entries.append(entry)
    fm["cited_by"] = entries
    write_note(path, dump_note(fm, body))
    return path.parent.name
