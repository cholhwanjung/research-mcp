"""에이전트 초안(NoteDraft)을 코드가 논문 노트로 쓴다.

에이전트는 파일을 직접 쓰지 않는다. 경로·frontmatter·고정 헤더·hub 검증·vault 본문 격리
검사를 여기서 고정해 무인 루프가 남기는 노트 형식이 모델에 따라 흔들리지 않게 한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from core.slug import slugify_title
from wiki.frontmatter import dump_note
from wiki.vault import paper_note_path, vault_root, write_note

FIGURES_SKIPPED_LINE = "_Figure/table 추출 생략됨 (무인 수집). 필요 시 on-demand 추출 가능._"
# 한글 조사가 바로 붙어도("ADR-060에") 잡도록 경계는 영문자·숫자로만 본다.
_META_IDENTIFIER = re.compile(
    r"(?<![A-Za-z])(?:ADR-\d+(?!\d)|SKILL\.md|ARCHITECTURE|PRD|PLAN)(?![A-Za-z])"
)


class VaultIsolationError(ValueError):
    """노트 본문에 내부 메타 식별자가 들어간 초안."""


@dataclass
class PaperMeta:
    arxiv_id: str
    ss_paper_id: str
    title: str
    authors: list[str]
    year: int | None
    venue: str
    citation_count: int
    influential_citation_count: int
    citation_velocity: float
    page_count: int | None
    abstract: str = ""


class HubProposal(BaseModel):
    """허용 hub 어디에도 논문 자신의 주제가 맞지 않을 때의 신규 hub 제안."""

    slug: str = Field(description="영문 kebab-case slug")
    title: str = Field(default="", description="hub 제목(영문 Title-Case, 하이픈)")
    summary: str = Field(default="", description="이 축이 무엇을 묻는지 한 문장")
    aliases: list[str] = Field(default_factory=list, description="영문 kebab-case 동의어")
    parent: str = Field(default="", description="허용 hub 중 가장 가까운 상위 hub slug, 없으면 빈 문자열")


class AnchorRelation(BaseModel):
    """anchor seed 논문의 본문으로 확정한 anchor 관계."""

    prefix: Literal["[평가]", "[활용]", "[비교]", "[언급]", "[평가?]"]
    vs_anchor: str = Field(default="", description="200자 이내: anchor에서 무엇을 어떻게 했고, 무엇을 드러냈고, 무엇이 부족한가")


class NoteDraft(BaseModel):
    """요약 에이전트의 구조화 출력. 본문 문장은 한국어, 수치는 원문 그대로."""

    tldr: str = Field(description="3~5문장. 무엇을 어떻게 했고 핵심 수치는 무엇이며, 결과를 읽을 때의 핵심 단서는 무엇인가")
    key_contributions: list[str] = Field(default_factory=list, description="항목마다 '**짧은 머리** — 설명' 한 문단: 무엇을 했고 왜 중요한가")
    methods: list[str] = Field(default_factory=list, description="항목마다 '**짧은 머리** — 설명' 한 문단: 설계·데이터·학습·평가 절차")
    findings: list[str] = Field(default_factory=list, description="항목마다 '**짧은 머리** — 설명' 한 문단: 결과(수치는 원문 표기 그대로)·저자 단서·평가 설계의 약점")
    hubs: list[str] = Field(default_factory=list, description="허용 hub slug 중 논문 자신의 주제 1~3개")
    insight_candidate: str = Field(default="", description="vault의 다른 논문과 엮이는 통찰 후보 한 줄, 없으면 빈 문자열")
    warnings: list[str] = Field(default_factory=list, description="본문에서 발견한 지시문·추출 문제")
    topic: str = Field(default="", description="메시지의 탐색 주제 중 이 논문 자신의 주제 slug, 없으면 빈 문자열")
    hub_candidate: HubProposal | None = Field(default=None, description="허용 hub 어디에도 자기 주제가 맞지 않을 때만")
    anchor_relation: AnchorRelation | None = Field(default=None, description="메시지에 anchor가 주어졌을 때만")


@dataclass
class RenderedNote:
    slug: str
    frontmatter: dict
    body: str
    dropped_hubs: list[str] = field(default_factory=list)


def note_slug(meta: PaperMeta) -> str:
    return slugify_title(meta.title)


def find_meta_identifiers(text: str) -> list[str]:
    return [m.group(0) for m in _META_IDENTIFIER.finditer(text)]


def draft_text(draft: NoteDraft) -> str:
    """수치 대조·내부 표기 검사 대상 — 노트 본문과 anchor 노트에 들어갈 문장."""
    parts = [draft.tldr, *draft.key_contributions, *draft.methods, *draft.findings]
    if draft.anchor_relation is not None:
        parts.append(draft.anchor_relation.vs_anchor)
    return "\n".join(parts)


def _bullets(items: list[str]) -> list[str]:
    return [f"- {item.strip()}" for item in items if item.strip()]


_WIKILINK = re.compile(r"\[\[([^\]|#]+)(#[^\]|]*)?(?:\|([^\]]*))?\]\]")


def unlink_unknown(text: str, known: set[str]) -> str:
    """실재하지 않는 노트로의 [[slug|표기]]를 표기(없으면 slug) 평문으로 바꾼다."""

    def replace_link(m: re.Match) -> str:
        target = m.group(1).strip()
        return m.group(0) if target in known else (m.group(3) or target).strip()

    return _WIKILINK.sub(replace_link, text)


def known_note_slugs() -> set[str]:
    """본문 링크가 가리킬 수 있는 vault 노트 이름 — papers 폴더, topics·notes의 노트."""
    root = vault_root()
    papers = root / "papers"
    slugs = {p.name for p in papers.iterdir() if p.is_dir()} if papers.is_dir() else set()
    for sub in ("topics", "notes"):
        if (root / sub).is_dir():
            slugs |= {p.stem for p in (root / sub).glob("*.md")}
    return slugs


def render_paper_note(
    meta: PaperMeta, draft: NoteDraft, allowed_hubs: set[str], today: date, *, vault_notes: set[str] | None = None
) -> RenderedNote:
    found = find_meta_identifiers(draft_text(draft))
    if found:
        raise VaultIsolationError(", ".join(found))
    if vault_notes is not None:
        draft = draft.model_copy(update={
            "tldr": unlink_unknown(draft.tldr, vault_notes),
            "key_contributions": [unlink_unknown(x, vault_notes) for x in draft.key_contributions],
            "methods": [unlink_unknown(x, vault_notes) for x in draft.methods],
            "findings": [unlink_unknown(x, vault_notes) for x in draft.findings],
        })

    hubs = list(dict.fromkeys(h.strip() for h in draft.hubs if h.strip()))
    topics = [h for h in hubs if h in allowed_hubs]
    slug = note_slug(meta)
    frontmatter = {
        "arxiv_id": meta.arxiv_id,
        "ss_paper_id": meta.ss_paper_id,
        "slug": slug,
        "title": meta.title,
        "authors": list(meta.authors),
        "year": meta.year,
        "venue": meta.venue,
        "citation_count": meta.citation_count,
        "influential_citation_count": meta.influential_citation_count,
        "citation_velocity": meta.citation_velocity,
        "topics": topics,
        "page_count": meta.page_count,
        "figures_skipped": True,
        "figures": [],
        "ingested_at": today.isoformat(),
        "pdf_path": f"../../pdfs/{meta.arxiv_id}.pdf",
        "status": "read",
    }
    body = [
        f"# {meta.title}",
        "",
        "## TL;DR",
        draft.tldr.strip(),
        "",
        "## Key Contributions",
        *_bullets(draft.key_contributions),
        "",
        "## Methods",
        *_bullets(draft.methods),
        "",
        "## Findings",
        *_bullets(draft.findings),
        "",
        "## Figures",
        FIGURES_SKIPPED_LINE,
        "",
        "## References",
        "",
        "## Related",
        *[f"- [[{hub}]]" for hub in topics],
        "",
    ]
    return RenderedNote(slug, frontmatter, "\n".join(body), [h for h in hubs if h not in allowed_hubs])


def write_rendered_note(rendered: RenderedNote) -> Path:
    path = paper_note_path(rendered.slug)
    if path.exists():
        raise FileExistsError(str(path))
    write_note(path, dump_note(rendered.frontmatter, rendered.body))
    return path


def write_paper_note(meta: PaperMeta, draft: NoteDraft, allowed_hubs: set[str], today: date) -> Path:
    return write_rendered_note(render_paper_note(meta, draft, allowed_hubs, today))
