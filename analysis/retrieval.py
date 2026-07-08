"""vault 어휘 검색 + 링크 이웃 확장 (ADR-028).

"질문 → 관련 노트" 리트리벌. obsidian-llm-wiki의 lex→graph 캐스케이드에서
Monte-Carlo PPR을 뺀 경량판 — 어휘 매칭으로 seed를 뽑고, `[[wikilink]]` 그래프의
1-hop 이웃(정방향 링크 + 백링크)으로 확장한다. 임베딩·외부 호출 0.

레이어 규약: **순수 함수만.** vault I/O 없음 — 호출측(tools/wiki_tools.py)이
`read_vault_notes()`로 notes를, `extract_links()`로 adjacency를 만들어 넘긴다.
그래서 analysis는 wiki를 import하지 않는다 (단방향 유지).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_SLUG_BOOST = 5.0
_NEIGHBOR_WEIGHT = 0.3
_SNIPPET_WIDTH = 140


@dataclass
class SearchHit:
    slug: str
    score: float
    matched: list[str] = field(default_factory=list)
    via: str = "lexical"  # "lexical" | "neighbor"
    snippet: str = ""


def _tokens(text: str) -> list[str]:
    """`\\w+` 토큰(중복 포함), 1글자 제외. 소문자."""
    return [t.lower() for t in _TOKEN_RE.findall(text) if len(t) >= 2]


def tokenize(text: str) -> list[str]:
    """중복 제거 + 순서 보존 토큰 리스트."""
    seen: list[str] = []
    for t in _tokens(text):
        if t not in seen:
            seen.append(t)
    return seen


def _score_note(terms: list[str], slug: str, content: str) -> tuple[float, list[str]]:
    tf = Counter(_tokens(content))
    slug_tokens = set(_tokens(slug))
    score = 0.0
    matched: list[str] = []
    for t in terms:
        count = tf.get(t, 0)
        boost = _SLUG_BOOST if t in slug_tokens else 0.0
        if count or boost:
            score += count + boost
            matched.append(t)
    return score, matched


def _snippet(content: str, matched: list[str]) -> str:
    low = content.lower()
    idx = -1
    for t in matched:
        i = low.find(t)
        if i >= 0:
            idx = i if idx < 0 else min(idx, i)
    if idx < 0:
        head = content.strip().replace("\n", " ")
        return head[:_SNIPPET_WIDTH] + ("…" if len(head) > _SNIPPET_WIDTH else "")
    start = max(0, idx - 40)
    seg = content[start : start + _SNIPPET_WIDTH].replace("\n", " ").strip()
    return ("…" if start > 0 else "") + seg + "…"


def _resolver(note_slugs: set[str]):
    """link target → 실재 note slug. 정확 매칭 실패 시 basename(마지막 경로 조각) 유일 매칭.

    ADR-023 노트는 read_vault_notes에서 `papers/<slug>/<slug>`로 키잉되지만
    본문 wikilink는 `[[<slug>]]`로 쓰므로 basename 매칭으로 이어준다.
    """
    by_base: dict[str, list[str]] = {}
    for s in note_slugs:
        by_base.setdefault(s.split("/")[-1], []).append(s)

    def resolve(target: str) -> str | None:
        t = target.strip()
        if t in note_slugs:
            return t
        cands = by_base.get(t.split("/")[-1])
        if cands and len(cands) == 1:
            return cands[0]
        return None

    return resolve


def search(
    query: str,
    notes: dict[str, str],
    adjacency: dict[str, list[str]],
    *,
    top_k: int = 5,
    expand: bool = True,
    neighbor_weight: float = _NEIGHBOR_WEIGHT,
) -> list[SearchHit]:
    """query와 관련된 vault 노트를 점수순으로 반환.

    Args:
        query: 자연어 질의.
        notes: {slug: content} — vault 전체.
        adjacency: {slug: [link target]} — 각 노트의 `[[wikilink]]` target(본문 표기 그대로).
        top_k: 최대 결과 수.
        expand: True면 어휘 seed에서 1-hop 링크 이웃까지 확장.
        neighbor_weight: 이웃 점수 = seed 점수 × 이 값.
    """
    terms = tokenize(query)
    if not terms or not notes:
        return []

    hits: dict[str, SearchHit] = {}
    for slug, content in notes.items():
        score, matched = _score_note(terms, slug, content)
        if score > 0:
            hits[slug] = SearchHit(
                slug=slug,
                score=float(score),
                matched=matched,
                via="lexical",
                snippet=_snippet(content, matched),
            )

    if expand and hits:
        resolve = _resolver(set(notes))
        # 정방향(resolved) + 역방향(백링크) 인접.
        fwd: dict[str, set[str]] = {}
        back: dict[str, set[str]] = {}
        for slug, targets in adjacency.items():
            for raw in targets:
                r = resolve(raw)
                if r is None:
                    continue
                fwd.setdefault(slug, set()).add(r)
                back.setdefault(r, set()).add(slug)

        lexical_slugs = set(hits)
        bump: dict[str, float] = {}
        for seed in lexical_slugs:
            neighbors = fwd.get(seed, set()) | back.get(seed, set())
            for nb in neighbors:
                if nb in lexical_slugs or nb not in notes:
                    continue
                bump[nb] = bump.get(nb, 0.0) + hits[seed].score * neighbor_weight
        for nb, sc in bump.items():
            hits[nb] = SearchHit(
                slug=nb,
                score=sc,
                matched=[],
                via="neighbor",
                snippet=_snippet(notes[nb], []),
            )

    ranked = sorted(hits.values(), key=lambda h: (-h.score, h.slug))
    return ranked[:top_k]
