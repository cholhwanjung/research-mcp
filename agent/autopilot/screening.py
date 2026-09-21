"""후보를 ingest 전에 거른다 — 스킬 모드의 scope 필터·scope 게이트·중요도 게이트.

- seed 항목(`via seed:<주제>`)은 그 주제가 scope 안(자식 hub 포함)일 때만 후보다.
- scope 게이트는 제목·초록 판정이라 판정 에이전트가 한다. 우선 큐·백필·hub 본문 평문 이름(scope hub가
  스스로 부른 논문)·anchor seed(seed 때 인용 문맥으로 이미 판정)는 면제.
- 중요도 게이트는 결정론: velocity ≥ `min_velocity` 또는 참조 2곳 이상이면 통과, 미달은 +30일 보류.
  P0·P1·P2·백필·anchor seed는 면제.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import NamedTuple

from pydantic import BaseModel, Field

from agent.autopilot.control import ControlNote, item_arxiv_id, item_key
from agent.autopilot.queue import Candidate, expand_scope
from agent.autopilot.topics import Topic

HOLD_DAYS = 30
_REEVAL = re.compile(r"재평가\s+(\d{4}-\d{2}-\d{2})")
_HOLD_VELOCITY = re.compile(r"velocity\s+([\d.]+)")
_EXEMPT_RANKS = {"P0", "P1", "P2"}
_NO_SCOPE_GATE_SOURCES = {"P0", "PA", "S2"}


class ScopeVerdict(BaseModel):
    """scope 판정 에이전트의 구조화 출력."""

    in_scope: bool = Field(description="논문 자신의 주제가 scope hub 정의·alias나 탐색 주제 정의·검색어에 맞으면 true")
    reason: str = Field(default="", description="판정 근거 한 줄")


class TitleVerdicts(BaseModel):
    """제목만으로 한 scope 판정(리필 후보 배치)."""

    in_scope: list[str] = Field(default_factory=list, description="scope 안으로 판정한 paper_id")


@dataclass
class ScopeContext:
    scope: list[str]
    hubs: list[dict] = field(default_factory=list)
    topics: list[Topic] = field(default_factory=list)


class GateResult(NamedTuple):
    passed: bool
    label: str


def seed_topic(c: Candidate) -> str | None:
    if c.via and c.via.startswith("seed:"):
        return c.via[len("seed:"):]
    return None


def scope_members(scope: list[str], hubs: list[dict]) -> set[str] | None:
    """scope slug + 자손 hub. `all`이면 None(제한 없음)."""
    if scope == ["all"]:
        return None
    return expand_scope(scope, hubs)


def filter_seeds_by_scope(queue: list[Candidate], scope: list[str], hubs: list[dict]) -> list[Candidate]:
    members = scope_members(scope, hubs)
    if members is None:
        return list(queue)
    return [c for c in queue if (topic := seed_topic(c)) is None or topic in members]


def is_anchor_seed(c: Candidate, topics: dict[str, Topic]) -> bool:
    topic = seed_topic(c)
    return bool(topic and topic in topics and topics[topic].kind == "anchor")


def needs_scope_gate(c: Candidate, scope: list[str], topics: dict[str, Topic]) -> bool:
    if scope == ["all"]:
        return False
    if c.source in _NO_SCOPE_GATE_SOURCES or c.rank in _EXEMPT_RANKS:
        return False
    return not is_anchor_seed(c, topics)


def velocity_gate(
    c: Candidate, velocity: float | None, min_velocity: float, topics: dict[str, Topic], *, refs: int = 0
) -> GateResult:
    if c.rank in _EXEMPT_RANKS or c.source == "PA":
        return GateResult(True, f"exempt({c.rank if c.rank != '-' else c.source})")
    if is_anchor_seed(c, topics):
        return GateResult(True, "exempt(anchor)")
    if c.source == "F" and c.via:
        refs = max(refs, len([v for v in c.via.split(",") if v.strip() and not v.strip().startswith("seed:")]))
    v = float(velocity or 0.0)
    if v >= min_velocity:
        return GateResult(True, f"pass(v={v:.1f})")
    if refs >= 2:
        return GateResult(True, f"pass(refs={refs})")
    return GateResult(False, f"held(v={v:.1f})")


def hold_line(arxiv_id: str, title: str, velocity: float, today: date, days: int = HOLD_DAYS) -> str:
    until = today + timedelta(days=days)
    return f"{arxiv_id} ({title}) — velocity {float(velocity):.1f} ({today.isoformat()}) · 재평가 {until.isoformat()}"


def expired_hold_candidates(note: ControlNote, today: date) -> list[Candidate]:
    """재평가일이 지난 보류 항목 — frontier 후보로 되돌린다."""
    out: list[Candidate] = []
    for item in note.items("보류"):
        m = _REEVAL.search(item)
        aid = item_arxiv_id(item)
        if not m or not aid or date.fromisoformat(m.group(1)) > today:
            continue
        vel = _HOLD_VELOCITY.search(item)
        out.append(Candidate(item_key(item), aid, "F", "-", velocity=float(vel.group(1)) if vel else None, line=item))
    return out


def scope_context(scope: list[str], hubs: list[dict], topics: dict[str, Topic]) -> ScopeContext:
    members = scope_members(scope, hubs)
    if members is None:
        return ScopeContext(list(scope), list(hubs), list(topics.values()))
    return ScopeContext(
        list(scope),
        [h for h in hubs if h["slug"] in members],
        [t for slug, t in topics.items() if slug in members],
    )
