"""탐색 주제 seed(S0)와 대기열 리필 — 스킬 모드 seed·리필 절의 코드판.

- query 주제(`members: []`·`seeded: -`): arXiv 검색 → vault·건너뜀·보류·frontier 제외 → velocity 임계
  (미달은 +30일 보류) → 상위 10건 `via seed:<주제>`. 0건이면 `(0건)`. 검색 일시 실패 3회 연속이면 `(실패)`.
- anchor 주제(frontier에 그 seed가 없고 소진·실패가 아님): anchor의 cited_by를 50편 회차로 본다. anchor 노트에
  접두사가 이미 있으면 문맥을 다시 부르지 않고(초록도 부르지 않는다), 판정 에이전트가 접두사·유용도를 매긴다.
  relation에 맞는 상·중 + relation 밖 상만 frontier에. 회차 판정 전부를 anchor 노트 cited_by에 병합한다.
  응답이 끝났거나 2회차 연속 상·중 0건이면 `(소진)`.
- 리필: scope 소속 논문(query 주제 members 포함, anchor 주제 members 제외) 중 inbound 링크가 많은 3편을
  `frontier_anchors`로 순환하며 인용·참조 이웃 → 제목 scope 판정(`all`이면 생략) → velocity 상위 10건.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from agent.autopilot.citations import CitationEntry, judge_entries, merge_citations, prefix_of
from agent.autopilot.control import ControlNote
from agent.autopilot.failures import ToolFailure
from agent.autopilot.notes import PaperMeta
from agent.autopilot.queue import excluded_keys, frontier_candidates
from agent.autopilot.screening import hold_line, scope_context, scope_members, seed_topic
from agent.autopilot.topics import Topic, save_topic
from analysis.linkgraph import build_link_graph
from wiki.frontmatter import dump_note, parse_note
from wiki.linker import extract_links, read_vault_notes
from wiki.vault import resolve_paper_by_arxiv_id, vault_root, write_note

ROUND = 50
QUERY_RESULTS = 20
SEED_TOP = 10
REFILL_TOP = 10
REFILL_ANCHORS = 3
_SEED_FAILURE_LIMIT = 3
_EMPTY_ROUND_LIMIT = 2
_RELATION_PREFIXES = {"평가": {"[평가]", "[평가?]"}, "활용": {"[활용]"}, "비교": {"[비교]"}}
_USEFUL_RANK = {"상": 0, "중": 1, "하": 2}
_USEFUL_SUFFIX = re.compile(r"\s·\s유용\s(상|중|하)\s*$")


@dataclass
class SeedOutcome:
    topic: str
    kind: str
    status: str = "ok"  # ok | empty | exhausted | transient | failed
    added: int = 0
    held: int = 0
    anchor: str | None = None
    judged: int | None = None
    useful: tuple[int, int, int] | None = None

    def log_fields(self) -> dict:
        fields: dict = {"source": "S0", "topic": self.topic}
        if self.kind == "anchor":
            fields.update(anchor=self.anchor, judged=self.judged)
        fields["added"] = self.added
        if self.kind == "query":
            fields["held"] = self.held
        if self.useful is not None:
            fields["useful"] = "/".join(str(n) for n in self.useful)
        if self.status != "ok":
            fields["status"] = self.status
        return fields


@dataclass
class RefillOutcome:
    anchors: list[str] = field(default_factory=list)
    added: int = 0


def seedable_topics(note: ControlNote, scope: list[str], hubs: list[dict], topics: dict[str, Topic]) -> list[Topic]:
    members = scope_members(scope, hubs)
    queued = {seed_topic(c) for c in frontier_candidates(note)}
    out: list[Topic] = []
    for topic in topics.values():
        if members is not None and topic.slug not in members:
            continue
        if topic.kind == "query":
            if not topic.members and topic.seeded == "-":
                out.append(topic)
        elif topic.slug not in queued and not topic.seeded.endswith(("(소진)", "(실패)")):
            out.append(topic)
    return out


def _queued_ids(note: ControlNote, today: date) -> set[str]:
    return excluded_keys(note, today) | {c.arxiv_id for c in frontier_candidates(note) if c.arxiv_id}


def _seed_failed(note: ControlNote, topic: Topic, out: SeedOutcome, today: date) -> SeedOutcome:
    topic.seed_failures += 1
    if topic.seed_failures >= _SEED_FAILURE_LIMIT:
        topic.seeded = f"{today.isoformat()} (실패)"
        out.status = "failed"
    else:
        out.status = "transient"
    save_topic(note, topic)
    return out


async def seed_query_topic(deps, note: ControlNote, topic: Topic, *, today: date, min_velocity: float) -> SeedOutcome:
    out = SeedOutcome(topic.slug, "query")
    try:
        hits = await deps.search(topic.query or topic.definition, max_results=QUERY_RESULTS)
    except ToolFailure:
        return _seed_failed(note, topic, out, today)
    queued = _queued_ids(note, today)
    kept: list[PaperMeta] = []
    seen: set[str] = set()
    for hit in hits:
        aid = hit.arxiv_id
        if not aid or aid in seen or aid in queued or resolve_paper_by_arxiv_id(aid) is not None:
            continue
        seen.add(aid)
        try:
            meta = await deps.paper_info(aid)
        except Exception:
            continue
        if meta is None:
            continue
        if meta.citation_velocity >= min_velocity:
            kept.append(meta)
        else:
            note.add_item("보류", hold_line(aid, meta.title, meta.citation_velocity, today))
            out.held += 1
    kept.sort(key=lambda m: -m.citation_velocity)
    for meta in kept[:SEED_TOP]:
        note.add_item("frontier", f"{meta.arxiv_id} — {meta.title} · vel {meta.citation_velocity:.1f} · via seed:{topic.slug}")
    out.added = min(len(kept), SEED_TOP)
    topic.seed_failures = 0
    if out.added:
        topic.seeded = today.isoformat()
    else:
        topic.seeded, out.status = f"{today.isoformat()} (0건)", "empty"
    save_topic(note, topic)
    return out


def _anchor_meta(anchor_id: str, fm: dict) -> PaperMeta:
    return PaperMeta(arxiv_id=anchor_id, ss_paper_id=str(fm.get("ss_paper_id") or ""), title=str(fm.get("title") or anchor_id),
                     authors=[], year=fm.get("year"), venue=str(fm.get("venue") or ""),
                     citation_count=int(fm.get("citation_count") or 0), influential_citation_count=0,
                     citation_velocity=float(fm.get("citation_velocity") or 0.0), page_count=None)


async def seed_anchor_topic(deps, note: ControlNote, topic: Topic, hubs: list[dict], *, today: date) -> SeedOutcome:
    judged = topic.judged or 0
    out = SeedOutcome(topic.slug, "anchor", anchor=topic.anchor, judged=judged)
    kwargs = {"max_fetch": judged + ROUND} if judged + ROUND > 1000 else {}
    try:
        cites = await deps.citations(topic.anchor, top_k=judged + ROUND, min_velocity=0.0, exclude_recent_year=False, **kwargs)
    except ToolFailure:
        return _seed_failed(note, topic, out, today)
    if len(cites) <= judged:  # 판정할 것이 더 없다
        topic.seeded, topic.seed_failures, out.status = f"{today.isoformat()} (소진)", 0, "exhausted"
        save_topic(note, topic)
        return out

    queued = _queued_ids(note, today)
    candidates = [p for p in cites[judged : judged + ROUND]
                  if p.arxiv_id and p.arxiv_id not in queued and resolve_paper_by_arxiv_id(p.arxiv_id) is None]
    anchor_path = resolve_paper_by_arxiv_id(topic.anchor)
    anchor_fm, anchor_body = parse_note(anchor_path.read_text(encoding="utf-8")) if anchor_path else ({}, "")
    known = {str(e.get("paper_id")): str(e.get("cited_for") or "")
             for e in anchor_fm.get("cited_by") or [] if isinstance(e, dict)}
    entries: list[CitationEntry] = []
    for p in candidates:
        if prefix_of(known.get(p.arxiv_id, "")):
            entries.append(CitationEntry(p, contexts=[f"기존 판정: {known[p.arxiv_id]}"]))
            continue
        try:
            contexts = list(await deps.contexts(p.arxiv_id, topic.anchor) or [])
        except Exception:
            contexts = []
        entries.append(CitationEntry(p, contexts=contexts))
    judgements = (await judge_entries(deps, _anchor_meta(topic.anchor, anchor_fm), "cited_by", entries, hubs,
                                      relation=topic.relation, with_usefulness=True) if entries else [])

    wanted = _RELATION_PREFIXES.get(topic.relation or "", set())
    counts = {"상": 0, "중": 0, "하": 0}
    selected: list[tuple[str, str, object]] = []
    new_entries: list[dict] = []
    usefulness: dict[str, str] = {}
    for j, p in zip(judgements, candidates):
        prefix = prefix_of(known.get(p.arxiv_id, "")) or prefix_of(j.cited_for) or "[평가?]"
        useful = j.usefulness or "하"
        counts[useful] += 1
        usefulness[p.arxiv_id] = useful
        if useful in ("상", "중") and (prefix in wanted or useful == "상"):
            selected.append((useful, prefix, p))
        judged_prefix = prefix_of(j.cited_for)
        context = j.cited_for[len(judged_prefix):].strip() if judged_prefix else j.cited_for.strip()
        text = " ".join(part for part in (prefix, context) if part)
        new_entries.append({"paper_id": p.arxiv_id, "hubs": [], "abstract_summary": p.title, "cited_for": f"{text} · 유용 {useful}"})

    if anchor_path is not None and new_entries:
        for entry in anchor_fm.get("cited_by") or []:  # 접두사가 있던 항목은 유지하고 유용도만 덧붙인다
            pid = str(entry.get("paper_id")) if isinstance(entry, dict) else ""
            if pid in usefulness and not _USEFUL_SUFFIX.search(str(entry.get("cited_for") or "")):
                entry["cited_for"] = f"{entry.get('cited_for')} · 유용 {usefulness[pid]}"
        merge_citations(anchor_fm, "cited_by", new_entries)
        write_note(anchor_path, dump_note(anchor_fm, anchor_body))

    selected.sort(key=lambda s: (_USEFUL_RANK[s[0]], -s[2].velocity))
    for useful, prefix, p in selected:
        note.add_item("frontier", f"{p.arxiv_id} — {p.title} · vel {p.velocity:.1f} · via seed:{topic.slug} · {prefix} · 유용 {useful}")
    topic.judged = judged + ROUND
    topic.seed_failures = 0
    topic.empty_rounds = topic.empty_rounds + 1 if counts["상"] + counts["중"] == 0 else 0
    exhausted = len(cites) < judged + ROUND or topic.empty_rounds >= _EMPTY_ROUND_LIMIT
    topic.seeded = f"{today.isoformat()} (소진)" if exhausted else today.isoformat()
    save_topic(note, topic)
    out.added, out.judged, out.useful = len(selected), topic.judged, (counts["상"], counts["중"], counts["하"])
    return out


def _paper_index() -> list[tuple[str, dict]]:
    base = vault_root() / "papers"
    out: list[tuple[str, dict]] = []
    if not base.is_dir():
        return out
    for folder in sorted(base.iterdir()):
        note = folder / f"{folder.name}.md"
        if not note.is_file():
            continue
        try:
            fm, _ = parse_note(note.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        if isinstance(fm, dict) and fm.get("arxiv_id"):
            out.append((folder.name, fm))
    return out


def _inbound_counts() -> dict[str, int]:
    notes = read_vault_notes()
    graph = build_link_graph(notes, {slug: extract_links(text) for slug, text in notes.items()})
    return {slug.split("/")[-1]: len(sources) for slug, sources in graph.backward.items() if slug.startswith("papers/")}


async def refill(deps, note: ControlNote, scope: list[str], hubs: list[dict], topics: dict[str, Topic], *,
                 today: date, min_velocity: float, current_year: int | None = None) -> RefillOutcome:
    members = scope_members(scope, hubs)
    anchor_members = {m for t in topics.values() if t.kind == "anchor" for m in t.members}
    query_members = {m for t in topics.values() if t.kind == "query" and (members is None or t.slug in members)
                     for m in t.members}
    pool: list[tuple[str, dict]] = []
    for slug, fm in _paper_index():
        if slug in anchor_members:  # 인용 이웃은 anchor 관계를 보존하지 않는다 — 그 주제는 재seed
            continue
        paper_topics = {str(t).strip().strip("[]") for t in fm.get("topics") or []}
        if members is None or paper_topics & members or slug in query_members:
            pool.append((slug, fm))
    inbound = _inbound_counts()
    pool.sort(key=lambda item: (-inbound.get(item[0], 0), item[0]))

    used = list(note.frontmatter.get("frontier_anchors") or [])
    remaining = [item for item in pool if item[0] not in used]
    if not remaining and pool:  # 다 썼으면 비우고 처음부터
        used, remaining = [], list(pool)

    out = RefillOutcome()
    queued = _queued_ids(note, today)
    year = current_year or today.year
    for _ in range(2):
        anchors, remaining = remaining[:REFILL_ANCHORS], remaining[REFILL_ANCHORS:]
        if not anchors:
            break
        found: dict[str, list] = {}
        for slug, fm in anchors:
            aid = str(fm["arxiv_id"])
            recent = int(fm.get("year") or 0) >= year - 1
            neighbours = []
            for fetch in (
                lambda: deps.citations(aid, top_k=REFILL_TOP, min_velocity=min_velocity, exclude_recent_year=not recent),
                lambda: deps.references(aid, top_k=REFILL_TOP, min_velocity=min_velocity),
            ):
                try:
                    neighbours += list(await fetch())
                except Exception:
                    continue
            for p in neighbours:
                if not p.arxiv_id or p.arxiv_id in queued or resolve_paper_by_arxiv_id(p.arxiv_id) is not None:
                    continue
                entry = found.setdefault(p.arxiv_id, [p, []])
                if slug not in entry[1]:
                    entry[1].append(slug)
        picked = list(found.values())
        if members is not None and picked:
            keep = set(await deps.judge_titles([(p.arxiv_id, p.title) for p, _ in picked], scope_context(scope, hubs, topics)))
            picked = [item for item in picked if item[0].arxiv_id in keep]
        picked.sort(key=lambda item: -item[0].velocity)
        for p, via in picked[:REFILL_TOP]:
            note.add_item("frontier", f"{p.arxiv_id} — {p.title} · vel {p.velocity:.1f} · via {','.join(via)}")
        used += [slug for slug, _ in anchors]
        note.frontmatter["frontier_anchors"] = used
        out.anchors += [slug for slug, _ in anchors]
        out.added += min(len(picked), REFILL_TOP)
        if out.added:
            break
    return out
