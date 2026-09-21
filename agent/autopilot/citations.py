"""인용 분석(스킬 모드의 인용 흐름 누적) — 수집·판정 배치·검증·병합·References 절·그래프.

refs·cites 중 arXiv ID가 있는 것만 다룬다(노트 간 링크·seed 후보가 arXiv ID를 키로 쓴다). 각 항목에
초록·인용 문맥을 붙여 판정 에이전트에 25건씩 넘기고, 돌아온 판정을 관계 접두사·기존 hub로 검증한다.
판정이 빠진 항목은 제목만으로 `[평가?]`. frontmatter는 paper_id 기준 병합(기존 항목 유지), 본문
References 절은 관계별 목록(hub 링크 포함), 그래프는 `graphs/<slug>.md`.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from agent.autopilot.notes import PaperMeta, VaultIsolationError, find_meta_identifiers, known_note_slugs, unlink_unknown
from agent.autopilot.sources import NetworkPaper
from tools.viz_tools import build_citation_graph
from wiki.frontmatter import dump_note, parse_note
from wiki.vault import write_note

RELATION_PREFIXES = ("[평가]", "[활용]", "[비교]", "[언급]", "[평가?]")
_ORDER = {"[평가]": 0, "[비교]": 1, "[활용]": 2, "[평가?]": 3, "[언급]": 4}
BATCH_SIZE = 25
TOP_K = 20
_CONCURRENCY = 2
FALLBACK_CITED_FOR = "[평가?] 인용 문맥 판정 누락"
_USEFUL_SUFFIX = re.compile(r"\s·\s유용\s(상|중|하)\s*$")


class CitationJudgement(BaseModel):
    paper_id: str = Field(description="입력 항목의 paper_id 그대로")
    hubs: list[str] = Field(default_factory=list, description="hub 목록 중 그 논문 자신의 주제 slug(없으면 빈 목록)")
    abstract_summary: str = Field(default="", description="초록을 한국어 한 문장으로")
    cited_for: str = Field(default="", description="관계 접두사([평가]·[활용]·[비교]·[언급]·[평가?])로 시작하는 문맥 근거 한 줄")
    group: str = Field(default="", description="그래프에서 묶을 짧은 이름(20자 이내)")
    usefulness: Literal["상", "중", "하"] | None = Field(default=None, description="메시지가 요구할 때만")


class CitationBatch(BaseModel):
    entries: list[CitationJudgement] = Field(default_factory=list)


class ReferencesSynthesis(BaseModel):
    references: str = Field(default="", description="이 논문이 인용한 연구 — 역할별 묶음·계보 연결·데이터 품질 판단 3~6문장")
    cited_by: str = Field(default="", description="이 논문을 인용한 연구 — 역할별 묶음·계보 연결·데이터 품질 판단 3~6문장")


@dataclass
class CitationEntry:
    paper: NetworkPaper
    abstract: str = ""
    contexts: list[str] = field(default_factory=list)


@dataclass
class CitationResult:
    refs: int
    cites: int
    synthesis: str = "-"  # References 종합 문단: ok · fail · -(종합 없음)


def prefix_of(cited_for: str) -> str | None:
    text = cited_for.strip()
    return next((p for p in RELATION_PREFIXES if text.startswith(p)), None)


def short_title(title: str) -> str:
    return title.split(":", 1)[0].strip() or title.strip()


def normalize_judgement(j: CitationJudgement, allowed_hubs: set[str]) -> CitationJudgement:
    cited_for = " ".join(j.cited_for.split())
    if prefix_of(cited_for) is None:
        cited_for = f"[평가?] {cited_for}".strip()
    return j.model_copy(update={
        "hubs": [h for h in dict.fromkeys(h.strip() for h in j.hubs) if h in allowed_hubs],
        "abstract_summary": " ".join(j.abstract_summary.split()),
        "cited_for": cited_for,
        "group": j.group.strip()[:20],
    })


def fallback_judgement(entry: CitationEntry) -> CitationJudgement:
    return CitationJudgement(paper_id=entry.paper.arxiv_id or entry.paper.ss_id,
                             abstract_summary=entry.paper.title, cited_for=FALLBACK_CITED_FOR)


def to_frontmatter_entry(j: CitationJudgement) -> dict:
    cited_for = j.cited_for
    if j.usefulness and not _USEFUL_SUFFIX.search(cited_for):
        cited_for = f"{cited_for} · 유용 {j.usefulness}"
    return {"paper_id": j.paper_id, "hubs": list(j.hubs), "abstract_summary": j.abstract_summary, "cited_for": cited_for}


def merge_citations(fm: dict, key: str, entries: list[dict]) -> int:
    """paper_id 기준 병합. 이미 있는 항목은 건드리지 않는다. 키는 0건이어도 남긴다(분석했다는 표시)."""
    existing = fm.get(key) if isinstance(fm.get(key), list) else []
    known = {str(e.get("paper_id")) for e in existing if isinstance(e, dict)}
    added = 0
    for entry in entries:
        pid = str(entry["paper_id"])
        if pid in known:
            continue
        existing.append(entry)
        known.add(pid)
        added += 1
    fm[key] = existing
    return added


def _sorted(pairs: list[tuple[CitationJudgement, NetworkPaper]]):
    return sorted(pairs, key=lambda jp: (_ORDER.get(prefix_of(jp[0].cited_for) or "[평가?]", 9), -jp[1].velocity))


def _lines(pairs: list[tuple[CitationJudgement, NetworkPaper]]) -> list[str]:
    out: list[str] = []
    for j, p in _sorted(pairs):
        prefix = prefix_of(j.cited_for) or "[평가?]"
        rest = j.cited_for.strip()[len(prefix):].strip() if j.cited_for.strip().startswith(prefix) else j.cited_for.strip()
        line = f"- **{prefix}** {short_title(p.title)} (arXiv:{p.arxiv_id})"
        if rest:
            line += f" — {rest}"
        if j.hubs:
            line += " · " + ", ".join(f"[[{h}]]" for h in j.hubs)
        out.append(line)
    return out


def _paragraph(text: str) -> list[str]:
    return [text.strip(), ""] if text.strip() else []


def render_references_section(
    refs: list[tuple[CitationJudgement, NetworkPaper]],
    cites: list[tuple[CitationJudgement, NetworkPaper]],
    synthesis: ReferencesSynthesis | None = None,
) -> str:
    if not refs and not cites:
        return "인용 DB에서 arXiv ID가 있는 인용·참조를 찾지 못했다."
    synthesis = synthesis or ReferencesSynthesis()
    parts = [f"이 논문이 인용한 연구 {len(refs)}편 · 이 논문을 인용한 연구 {len(cites)}편 (velocity 상위, arXiv ID가 있는 것)."]
    if cites:
        parts += ["", "### 이 논문을 인용한 연구", *_paragraph(synthesis.cited_by), *_lines(cites)]
    if refs:
        parts += ["", "### 이 논문이 인용한 연구", *_paragraph(synthesis.references), *_lines(refs)]
    return "\n".join(parts)


def graph_groups(pairs: list[tuple[CitationJudgement, NetworkPaper]]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for j, p in _sorted(pairs):
        prefix = (prefix_of(j.cited_for) or "[평가?]")[1:-1]
        label = f"{prefix} — {j.group}" if j.group else prefix
        groups.setdefault(label, []).append(
            {"arxiv_id": p.arxiv_id, "title": short_title(p.title), "year": p.year, "citation_count": p.citation_count}
        )
    return [{"topic": label, "papers": papers} for label, papers in groups.items()]


def replace_section(body: str, name: str, content: str) -> str:
    """`## name` 절 내용을 바꾼다. 절이 없으면 끝에 붙인다."""
    pattern = re.compile(rf"^## {re.escape(name)}[ \t]*\n(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)
    block = f"## {name}\n{content.rstrip()}\n\n"
    m = pattern.search(body)
    if m is None:
        return body.rstrip("\n") + "\n\n" + block.rstrip("\n") + "\n"
    return body[: m.start()] + block + body[m.end():]


async def collect_entries(deps, papers: list[NetworkPaper], *, anchor_id: str, direction: str) -> list[CitationEntry]:
    """초록·인용 문맥을 붙인다. 조회 실패는 빈 값 — 판정이 제목·문맥 없이 보수적으로 한다."""
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def one(p: NetworkPaper) -> CitationEntry:
        async with sem:
            citing, cited = (anchor_id, p.arxiv_id) if direction == "references" else (p.arxiv_id, anchor_id)
            try:
                abstract = getattr(await deps.paper_info(p.arxiv_id), "abstract", "") or ""
            except Exception:
                abstract = ""
            try:
                contexts = list(await deps.contexts(citing, cited) or [])
            except Exception:
                contexts = []
            return CitationEntry(p, abstract=abstract, contexts=contexts)

    return list(await asyncio.gather(*(one(p) for p in papers)))


async def judge_entries(
    deps, meta: PaperMeta, direction: str, entries: list[CitationEntry], hubs: list[dict], *,
    relation: str | None = None, with_usefulness: bool = False,
) -> list[CitationJudgement]:
    allowed = {h["slug"] for h in hubs}
    out: list[CitationJudgement] = []
    for start in range(0, len(entries), BATCH_SIZE):
        chunk = entries[start : start + BATCH_SIZE]
        batch = await deps.judge_citations(meta, direction, chunk, hubs, relation=relation, with_usefulness=with_usefulness)
        by_id = {j.paper_id.strip(): j for j in batch.entries}
        for entry in chunk:
            judged = by_id.get(entry.paper.arxiv_id or "")
            out.append(normalize_judgement(judged, allowed) if judged else fallback_judgement(entry))
    return out


async def analyze_citations(
    deps, meta: PaperMeta, note_path: Path, hubs: list[dict], *, now: datetime, top_k: int = TOP_K
) -> CitationResult:
    recent = meta.year is not None and meta.year >= now.year - 1
    refs = [p for p in await deps.references(meta.arxiv_id, top_k=top_k, min_velocity=10.0) if p.arxiv_id]
    cites = [
        p for p in await deps.citations(meta.arxiv_id, top_k=top_k, min_velocity=0.0 if recent else 10.0,
                                        exclude_recent_year=not recent)
        if p.arxiv_id
    ]
    ref_judged = await judge_entries(deps, meta, "references",
                                     await collect_entries(deps, refs, anchor_id=meta.arxiv_id, direction="references"), hubs)
    cite_judged = await judge_entries(deps, meta, "cited_by",
                                      await collect_entries(deps, cites, anchor_id=meta.arxiv_id, direction="cited_by"), hubs)
    ref_pairs, cite_pairs = list(zip(ref_judged, refs)), list(zip(cite_judged, cites))

    synthesis, state = None, "-"
    synthesize = getattr(deps, "synthesize_references", None)
    if synthesize is not None and (ref_pairs or cite_pairs):
        from agent.autopilot.vaultlinks import vault_papers

        known = {aid: slug for slug, _, aid in vault_papers() if aid and aid != meta.arxiv_id}
        try:
            raw = await synthesize(meta, ref_pairs, cite_pairs, known)
            names = known_note_slugs()
            synthesis = ReferencesSynthesis(references=unlink_unknown(raw.references, names),
                                            cited_by=unlink_unknown(raw.cited_by, names))
            state = "ok"
        except Exception:  # 종합 문단은 신호다 — 실패해도 목록은 쓴다(로그 references_synthesis=fail)
            state = "fail"
    section = render_references_section(ref_pairs, cite_pairs, synthesis)
    found = find_meta_identifiers(section)
    if found:
        raise VaultIsolationError(", ".join(found))
    fm, body = parse_note(note_path.read_text(encoding="utf-8"))
    merge_citations(fm, "references", [to_frontmatter_entry(j) for j in ref_judged])
    merge_citations(fm, "cited_by", [to_frontmatter_entry(j) for j in cite_judged])
    write_note(note_path, dump_note(fm, replace_section(body, "References", section)))

    anchor = {"arxiv_id": meta.arxiv_id, "title": short_title(meta.title), "year": meta.year,
              "citation_count": meta.citation_count}
    await build_citation_graph(anchor, graph_groups(ref_pairs), graph_groups(cite_pairs),
                               slug=str(fm.get("slug") or note_path.parent.name))
    return CitationResult(refs=len(ref_judged), cites=len(cite_judged), synthesis=state)
