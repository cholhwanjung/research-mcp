"""vault `[[wikilink]]` 링크 그래프 (ADR-033).

노트 본문에서 뽑은 raw target을 실재 노트 slug로 해석해 정방향·역방향 인접과
해석 실패(깨진 링크)를 한 번에 만든다. `wiki_search`의 이웃 확장과 `wiki_backlinks`
tool이 이 그래프를 공유한다 — 링크 해석 규칙이 한 곳에만 있다.

레이어 규약: **순수 함수만.** vault I/O 없음 — 호출측(tools/wiki_tools.py)이
`read_vault_notes()`로 notes를, `extract_links()`로 adjacency를 만들어 넘긴다.
그래서 analysis는 wiki를 import하지 않는다 (단방향 유지).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class LinkGraph:
    """slug 기준 인접. forward/backward는 모든 노트를 키로 갖는다(빈 리스트 포함),
    broken·case_mismatch는 해당 항목이 있는 노트만.

    case_mismatch는 {slug: [(본문 표기, 실제 노트 slug)]} — 해석은 되지만 표기가
    어긋난 링크. vault 표기 드리프트 신호라 깨진 링크와 분리해 남긴다.
    """

    forward: dict[str, list[str]] = field(default_factory=dict)
    backward: dict[str, list[str]] = field(default_factory=dict)
    broken: dict[str, list[str]] = field(default_factory=dict)
    case_mismatch: dict[str, list[tuple[str, str]]] = field(default_factory=dict)


# basename이 여러 노트에 걸릴 때 우선하는 디렉토리. ADR-027 `graphs/<slug>` 노트가
# 논문 노트와 basename을 공유하지만, 본문의 맨 `[[<slug>]]`는 논문을 가리키는 관습이다
# (그래프 트랜스클루전은 항상 `![[graphs/<slug>]]` 전체 경로로 쓴다).
_PREFERRED_DIR = "papers"


def _pick(candidates: list[str]) -> str | None:
    """후보가 유일하면 그것, 여러 개면 papers/ 노트 하나일 때만. 그 외는 미해석."""
    if len(candidates) == 1:
        return candidates[0]
    preferred = [c for c in candidates if c.startswith(_PREFERRED_DIR + "/")]
    return preferred[0] if len(preferred) == 1 else None


def resolve_targets(note_slugs: set[str]) -> Callable[[str], str | None]:
    """link target → 실재 note slug.

    해석 순서: (1) 정확 매칭 → (2) basename(마지막 경로 조각) → (3) 대소문자 무시
    전체 경로 → (4) 대소문자 무시 basename. Obsidian이 대소문자를 무시하고 해석하므로
    `[[topics/agent-reasoning]]`을 `topics/Agent-Reasoning`으로 잇는다 — 깨진 링크
    오탐 방지. ADR-023 노트는 `papers/<slug>/<slug>`로 키잉되지만 본문 wikilink는
    `[[<slug>]]`로 쓰므로 basename 매칭이 필요하다.
    """
    by_base: dict[str, list[str]] = {}
    by_lower: dict[str, list[str]] = {}
    by_base_lower: dict[str, list[str]] = {}
    for slug in sorted(note_slugs):
        base = slug.split("/")[-1]
        by_base.setdefault(base, []).append(slug)
        by_lower.setdefault(slug.lower(), []).append(slug)
        by_base_lower.setdefault(base.lower(), []).append(slug)

    def resolve(target: str) -> str | None:
        t = target.strip()
        if t in note_slugs:
            return t
        for candidates in (
            by_base.get(t.split("/")[-1]),
            by_lower.get(t.lower()),
            by_base_lower.get(t.split("/")[-1].lower()),
        ):
            if candidates:
                picked = _pick(candidates)
                if picked is not None:
                    return picked
        return None

    return resolve


def _is_case_mismatch(raw: str, resolved: str) -> bool:
    """표기만 어긋난 링크인가. basename 축약(`[[blip-2]]`)은 관습이라 제외."""
    if raw == resolved:
        return False
    if raw.lower() == resolved.lower():
        return True
    raw_base, resolved_base = raw.split("/")[-1], resolved.split("/")[-1]
    return raw_base != resolved_base and raw_base.lower() == resolved_base.lower()


def build_link_graph(
    notes: dict[str, str], adjacency: dict[str, list[str]]
) -> LinkGraph:
    """notes({slug: content}) + adjacency({slug: [raw target]}) → LinkGraph.

    자기 자신을 가리키는 링크는 엣지로 세지 않는다 (고아 오판 방지).
    """
    resolve = resolve_targets(set(notes))
    forward: dict[str, set[str]] = {slug: set() for slug in notes}
    backward: dict[str, set[str]] = {slug: set() for slug in notes}
    broken: dict[str, set[str]] = {}
    mismatch: dict[str, list[tuple[str, str]]] = {}

    for slug, targets in adjacency.items():
        if slug not in notes:
            continue
        for raw in targets:
            resolved = resolve(raw)
            if resolved is None:
                broken.setdefault(slug, set()).add(raw.strip())
                continue
            if _is_case_mismatch(raw.strip(), resolved):
                mismatch.setdefault(slug, []).append((raw.strip(), resolved))
            if resolved == slug:
                continue
            forward[slug].add(resolved)
            backward[resolved].add(slug)

    return LinkGraph(
        forward={k: sorted(v) for k, v in forward.items()},
        backward={k: sorted(v) for k, v in backward.items()},
        broken={k: sorted(v) for k, v in broken.items()},
        case_mismatch={k: sorted(set(v)) for k, v in mismatch.items()},
    )


def orphans(graph: LinkGraph) -> list[str]:
    """inbound 링크가 0인 노트 slug 정렬 리스트."""
    return sorted(slug for slug, srcs in graph.backward.items() if not srcs)
