"""제어 노트 `## 탐색 주제` 한 줄 ↔ 구조.

줄 형식: `<slug> — <정의> · query: "<검색어>" | anchor: <arXiv ID> · relation: <관계> · parent: <hub|->
· members: [a, b] · seeded: <-|날짜|날짜 (0건)|(소진)|(실패)> · judged: <n> · seed_failures: <n> · empty_rounds: <n>
· 승격 <날짜>`.
query 주제는 검색어로 한 번 seed하고, anchor 주제는 anchor의 cited_by를 회차로 판정해 seed한다.
코드가 members·seeded·judged·승격을 갱신하고 모르는 필드는 끝에 그대로 둔다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent.autopilot.control import ControlNote, item_key

SECTION = "탐색 주제"
_DEF_SEP = " — "
_SEP = " · "
_PROMOTED = "승격 "


@dataclass
class Topic:
    slug: str
    definition: str = ""
    query: str | None = None
    anchor: str | None = None
    relation: str | None = None
    parent: str | None = None
    members: list[str] = field(default_factory=list)
    seeded: str = "-"
    judged: int | None = None
    seed_failures: int = 0  # seed 일시 실패 연속 횟수 — 3이면 seeded (실패)
    empty_rounds: int = 0  # anchor 회차 상·중 0건 연속 횟수 — 2면 seeded (소진)
    promoted: str | None = None
    extra: list[str] = field(default_factory=list)

    @property
    def kind(self) -> str:
        return "anchor" if self.anchor else "query"


def parse_topic(item: str) -> Topic:
    head, _, rest = item.strip().partition(_DEF_SEP)
    parts = rest.split(_SEP)
    topic = Topic(slug=head.strip(), definition=parts[0].strip())
    for raw in parts[1:]:
        part = raw.strip()
        if part.startswith(_PROMOTED):
            topic.promoted = part[len(_PROMOTED):].strip()
            continue
        key, sep, value = part.partition(": ")
        value = value.strip()
        if not sep:
            topic.extra.append(part)
        elif key == "query":
            topic.query = value[1:-1] if len(value) >= 2 and value[0] == value[-1] == '"' else value
        elif key == "anchor":
            topic.anchor = value
        elif key == "relation":
            topic.relation = value
        elif key == "parent":
            topic.parent = None if value in ("", "-") else value
        elif key == "members":
            topic.members = [m.strip() for m in value.strip("[]").split(",") if m.strip()]
        elif key == "seeded":
            topic.seeded = value
        elif key == "judged" and value.isdigit():
            topic.judged = int(value)
        elif key in ("seed_failures", "empty_rounds") and value.isdigit():
            setattr(topic, key, int(value))
        else:
            topic.extra.append(part)
    return topic


def render_topic(topic: Topic) -> str:
    parts = [topic.definition]
    if topic.anchor:
        parts.append(f"anchor: {topic.anchor}")
    elif topic.query is not None:
        parts.append(f'query: "{topic.query}"')
    if topic.relation:
        parts.append(f"relation: {topic.relation}")
    parts.append(f"parent: {topic.parent or '-'}")
    parts.append(f"members: [{', '.join(topic.members)}]")
    parts.append(f"seeded: {topic.seeded}")
    if topic.judged is not None:
        parts.append(f"judged: {topic.judged}")
    if topic.seed_failures:
        parts.append(f"seed_failures: {topic.seed_failures}")
    if topic.empty_rounds:
        parts.append(f"empty_rounds: {topic.empty_rounds}")
    if topic.promoted:
        parts.append(f"{_PROMOTED}{topic.promoted}")
    parts.extend(topic.extra)
    return topic.slug + _DEF_SEP + _SEP.join(parts)


def topics_by_slug(note: ControlNote) -> dict[str, Topic]:
    out: dict[str, Topic] = {}
    for item in note.items(SECTION):
        topic = parse_topic(item)
        out[topic.slug] = topic
    return out


def save_topic(note: ControlNote, topic: Topic) -> None:
    """같은 slug 줄을 제자리에서 바꾼다. 없으면 절 끝에 붙인다."""
    line = render_topic(topic)
    for item in note.items(SECTION):
        if item_key(item) == topic.slug:
            note.replace_item(SECTION, item, line)
            return
    note.add_item(SECTION, line)
