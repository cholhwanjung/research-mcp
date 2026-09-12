"""다음 후보 유도 — 제어 노트(우선 큐·frontier·건너뜀·보류)와 vault frontmatter만으로.

hub 본문의 평문 논문명·깨진 링크·seed 판정은 판단이나 vault 전수 읽기가 필요해 여기서
다루지 않는다. 등급 순서는 스킬 모드와 같다: 우선 큐 → seed → 백필 → 나머지 frontier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from agent.autopilot.control import ControlNote, item_arxiv_id, item_key

_VEL = re.compile(r"\bvel\s+([\d.]+)")
_VIA = re.compile(r"\bvia\s+(\S+)")
_USEFUL = re.compile(r"유용\s+(상|중|하)")
_REEVAL = re.compile(r"재평가\s+(\d{4}-\d{2}-\d{2})")
_USEFUL_ORDER = {"상": 0, "중": 1}


@dataclass
class Candidate:
    key: str
    arxiv_id: str | None
    source: str
    rank: str
    velocity: float | None = None
    via: str | None = None
    usefulness: str | None = None
    line: str = ""


def priority_candidates(note: ControlNote) -> list[Candidate]:
    return [
        Candidate(item_key(item), item_arxiv_id(item), "P0", "P0", line=item)
        for item in note.items("우선 큐")
    ]


def frontier_candidates(note: ControlNote) -> list[Candidate]:
    out: list[Candidate] = []
    for item in note.items("frontier"):
        vel, via, useful = _VEL.search(item), _VIA.search(item), _USEFUL.search(item)
        via_value = via.group(1) if via else None
        seed = bool(via_value and via_value.startswith("seed:"))
        out.append(
            Candidate(
                key=item_key(item),
                arxiv_id=item_arxiv_id(item),
                source="S0" if seed else "F",
                rank="P5" if seed else "-",
                velocity=float(vel.group(1)) if vel else None,
                via=via_value,
                usefulness=useful.group(1) if useful else None,
                line=item,
            )
        )
    return out


def excluded_keys(note: ControlNote, today: date) -> set[str]:
    """건너뜀 전부 + 재평가일이 아직 오지 않은 보류. 식별 부분과 arXiv ID 둘 다 담는다."""
    keys: set[str] = set()

    def add(item: str) -> None:
        keys.add(item_key(item))
        aid = item_arxiv_id(item)
        if aid:
            keys.add(aid)

    for item in note.items("건너뜀"):
        add(item)
    for item in note.items("보류"):
        m = _REEVAL.search(item)
        if m and date.fromisoformat(m.group(1)) <= today:
            continue
        add(item)
    return keys


def expand_scope(scope: list[str], hubs: list[dict]) -> set[str]:
    """scope slug와 그 자손 hub(parent 체인). 부모는 넣지 않는다."""
    children: dict[str, list[str]] = {}
    for hub in hubs:
        parent = hub.get("parent")
        if parent:
            children.setdefault(str(parent), []).append(str(hub["slug"]))
    out: set[str] = set()
    stack = list(scope)
    while stack:
        slug = stack.pop()
        if slug in out:
            continue
        out.add(slug)
        stack.extend(children.get(slug, []))
    return out


def _topic_slugs(paper: dict) -> set[str]:
    return {str(t).strip().strip("[]") for t in (paper.get("topics") or [])}


def backfill_candidates(papers: list[dict], scope: list[str], hubs: list[dict]) -> list[Candidate]:
    """읽었지만 인용 지도(references·cited_by)가 없는 scope 소속 논문."""
    everything = scope == ["all"]
    allowed = set() if everything else expand_scope(scope, hubs)
    out: list[Candidate] = []
    for paper in papers:
        if paper.get("references") or paper.get("cited_by"):
            continue
        if not everything and not (_topic_slugs(paper) & allowed):
            continue
        aid = str(paper.get("arxiv_id") or "").strip()
        if aid:
            out.append(Candidate(aid, aid, "PA", "-"))
    return out


def _is_excluded(c: Candidate, excluded: set[str]) -> bool:
    return c.key in excluded or bool(c.arxiv_id and c.arxiv_id in excluded)


def ordered_queue(
    note: ControlNote,
    papers: list[dict],
    scope: list[str],
    hubs: list[dict],
    today: date,
) -> list[Candidate]:
    excluded = excluded_keys(note, today)
    frontier = [c for c in frontier_candidates(note) if not _is_excluded(c, excluded)]
    seeds = sorted(
        (c for c in frontier if c.rank == "P5"),
        key=lambda c: (_USEFUL_ORDER.get(c.usefulness or "", 2), -(c.velocity or 0.0)),
    )
    rest = sorted((c for c in frontier if c.rank != "P5"), key=lambda c: -(c.velocity or 0.0))
    backfill = [c for c in backfill_candidates(papers, scope, hubs) if not _is_excluded(c, excluded)]

    queue: list[Candidate] = []
    seen: set[str] = set()
    for c in priority_candidates(note) + seeds + backfill + rest:
        ident = c.arxiv_id or c.key
        if ident in seen:
            continue
        seen.add(ident)
        queue.append(c)
    return queue
