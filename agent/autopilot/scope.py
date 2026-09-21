"""자연어 scope → hub slug 집합 + 탐색 주제 등록.

해석 판정(ScopeInterpretation)이 hub slug와 주제 제안을 준다. 코드는 존재하는 hub만 받고, 기존 탐색 주제는 slug로
재사용하며, 새 query 주제는 영어 검색어와 함께 등록한다. 관계 의도("X를 도전한 논문")는 anchor 논문을 vault 제목 또는
검색으로 arXiv ID까지 풀어 anchor 주제로 — slug는 `<anchor slug>-<challengers|adopters|successors>`, parent는 anchor
노트의 첫 topics. X가 hub 이름이면(`anchor_hub`) 제안된 벤치마크 논문을 velocity 순으로 `max_topics`까지만 펼치고 나머지는
`not_expanded`로 알린다. anchor를 풀지 못하면 등록하지 않는다. `all`은 명시했을 때만.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from agent.autopilot.control import ControlNote
from agent.autopilot.failures import ToolFailure
from agent.autopilot.resolve import resolve_hit, vault_paper_by_name
from agent.autopilot.topics import Topic, save_topic
from core.slug import is_arxiv_id, slugify_title
from wiki.frontmatter import parse_note
from wiki.vault import resolve_paper_by_arxiv_id

_RELATION_SUFFIX = {"평가": "challengers", "활용": "adopters", "비교": "successors"}


class TopicSpec(BaseModel):
    slug: str = Field(description="영문 kebab-case slug. 기존 탐색 주제와 같은 주제면 그 slug")
    definition: str = Field(default="", description="이 주제가 무엇을 모으는지 한 줄")
    query: str = Field(default="", description="query 주제면 arXiv 영어 검색어(4~8단어)")
    anchor_name: str = Field(default="", description="관계 의도(X를 평가·활용·비교한 논문)면 anchor 논문 X의 이름")
    anchor_arxiv_id: str = Field(default="", description="anchor가 vault 논문 목록에 있을 때만 그 arXiv ID")
    anchor_hub: str = Field(default="", description="X가 hub 이름이라 그 hub의 벤치마크 논문을 anchor로 펼친 것이면 그 hub slug")
    relation: Literal["평가", "활용", "비교", ""] = Field(default="", description="anchor 주제의 관계")
    parent: str = Field(default="", description="기존 hub 중 가장 가까운 상위 hub slug")


class ScopeInterpretation(BaseModel):
    all: bool = Field(default=False, description='"전체"·"all"·"모든 hub"를 명시했을 때만 true')
    hubs: list[str] = Field(default_factory=list, description="scope 원문이 가리키는 기존 hub slug")
    topics: list[TopicSpec] = Field(default_factory=list, description="hub에 닿지 않는 주제")


@dataclass
class _Anchor:
    arxiv_id: str
    base: str
    parent: str | None
    velocity: float


async def _resolve_anchor(deps, spec: TopicSpec, hub_slugs: set[str]) -> _Anchor | None:
    given = spec.anchor_arxiv_id.strip()
    base = ""
    if is_arxiv_id(given):
        arxiv_id = given
    else:
        found = vault_paper_by_name(spec.anchor_name)
        if found:
            arxiv_id = found[2]
        else:
            try:
                hit = await resolve_hit(deps, spec.anchor_name, spec.definition)
            except ToolFailure:
                hit = None
            if hit is None:
                return None
            arxiv_id, base = hit.arxiv_id, slugify_title(hit.title)
    path = resolve_paper_by_arxiv_id(arxiv_id)
    fm = parse_note(path.read_text(encoding="utf-8"))[0] if path is not None else {}
    fm = fm if isinstance(fm, dict) else {}
    if path is not None:
        base = path.parent.name
    base = base or slugify_title(spec.anchor_name) if spec.anchor_name.strip() else base or arxiv_id.replace(".", "-")
    first = next((str(t).strip("[]") for t in fm.get("topics") or []), None)
    parent = first if first in hub_slugs else (spec.parent if spec.parent in hub_slugs else None)
    try:
        velocity = float(fm.get("citation_velocity") or 0.0)
    except (TypeError, ValueError):
        velocity = 0.0
    return _Anchor(arxiv_id, base, parent, velocity)


async def apply_interpretation(deps, note: ControlNote, interp: ScopeInterpretation, hubs: list[dict],
                               topics: dict[str, Topic], *, max_topics: int = 3,
                               not_expanded: list[str] | None = None) -> tuple[list[str], list[str]]:
    """(scope slug 목록, 새로 등록한 탐색 주제 slug). 등록은 제어 노트(메모리)에만 — 저장은 호출측."""
    if interp.all:
        return ["all"], []
    hub_slugs = {h["slug"] for h in hubs}
    scope = [slug for slug in dict.fromkeys(interp.hubs) if slug in hub_slugs]
    registered: list[str] = []

    def use(slug: str) -> bool:
        if slug in hub_slugs or slug in topics:
            scope.append(slug)
            return True
        return False

    def register(topic: Topic) -> None:
        save_topic(note, topic)
        topics[topic.slug] = topic
        registered.append(topic.slug)
        scope.append(topic.slug)

    def add_anchor(spec: TopicSpec, anchor: _Anchor) -> None:
        relation = spec.relation or "평가"
        slug = f"{anchor.base}-{_RELATION_SUFFIX[relation]}"
        if not use(slug):
            register(Topic(slug=slug, definition=" ".join(spec.definition.split()), anchor=anchor.arxiv_id,
                           relation=relation, parent=anchor.parent, judged=0))

    grouped: dict[str, list[TopicSpec]] = {}
    for spec in interp.topics:
        if spec.anchor_hub.strip():
            grouped.setdefault(spec.anchor_hub.strip(), []).append(spec)
            continue
        if spec.anchor_name.strip() or spec.anchor_arxiv_id.strip():
            anchor = await _resolve_anchor(deps, spec, hub_slugs)
            if anchor is not None:
                add_anchor(spec, anchor)
            continue
        slug = slugify_title(spec.slug)
        if not slug or slug == "untitled" or use(slug):
            continue
        register(Topic(slug=slug, definition=" ".join(spec.definition.split()),
                       query=" ".join((spec.query or spec.definition).split()),
                       parent=spec.parent if spec.parent in hub_slugs else None))

    for specs in grouped.values():  # hub 이름 anchor — velocity 순 max_topics까지만 펼친다
        resolved: list[tuple[TopicSpec, _Anchor]] = []
        for spec in specs:
            anchor = await _resolve_anchor(deps, spec, hub_slugs)
            if anchor is not None:
                resolved.append((spec, anchor))
        resolved.sort(key=lambda pair: -pair[1].velocity)
        for spec, anchor in resolved[:max_topics]:
            add_anchor(spec, anchor)
        if not_expanded is not None:
            not_expanded.extend(anchor.base for _, anchor in resolved[max_topics:])
    return list(dict.fromkeys(scope)), registered


def scope_request_message(hubs: list[dict]) -> str:
    children: dict[str, list[str]] = {}
    for hub in hubs:
        if hub.get("parent"):
            children.setdefault(str(hub["parent"]), []).append(hub["slug"])
    lines = [
        "🛑 autopilot — scope가 없어 시작하지 않았습니다",
        "   이번 실행에서 다룰 hub를 골라 주세요 (쉼표로 여러 개, 자식 hub 자동 포함, 자연어도 됩니다 — "
        "hub에 없는 주제는 탐색 주제로 등록됩니다):",
    ]
    for hub in hubs:
        line = f"   - {hub['slug']}"
        if hub.get("summary"):
            line += f" — {hub['summary']}"
        if children.get(hub["slug"]):
            line += f" (자식: {', '.join(children[hub['slug']])})"
        lines.append(line)
    lines.append('   전체를 대상으로 하려면 "전체"라고 명시해 주세요. 실행: python -m agent.autopilot --scope …')
    return "\n".join(lines)
