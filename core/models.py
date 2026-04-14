"""도메인 모델 (D-1, ADR-009/010).

`Paper.from_frontmatter` ↔ `to_frontmatter`로 vault 노트와 무손실 변환.
- `references` / `cited_by`는 `CitationEdge` (ADR-009 동적 토픽 edge)
- `figures`는 `FigureRef` (ADR-010)

`to_frontmatter`는 default(None / 빈 list) 필드를 생략 — frontmatter가 깔끔.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields


@dataclass
class CitationEdge:
    """ADR-009: 인용 edge — 자유 문자열 토픽 + 인용된 논문 초록 요약 + 본 논문 입장에서의 인용 이유."""

    paper_id: str = ""
    topic: str = ""
    abstract_summary: str = ""
    cited_for: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "CitationEdge":
        return cls(
            paper_id=d.get("paper_id", ""),
            topic=d.get("topic", ""),
            abstract_summary=d.get("abstract_summary", ""),
            cited_for=d.get("cited_for", ""),
        )

    def to_dict(self) -> dict:
        return {
            "paper_id": self.paper_id,
            "topic": self.topic,
            "abstract_summary": self.abstract_summary,
            "cited_for": self.cited_for,
        }


@dataclass
class FigureRef:
    """ADR-010: vault 내 figure 자산 ref."""

    file: str = ""
    caption: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "FigureRef":
        return cls(file=d.get("file", ""), caption=d.get("caption", ""))

    def to_dict(self) -> dict:
        return {"file": self.file, "caption": self.caption}


@dataclass
class Paper:
    """ARCHITECTURE §5.1 frontmatter ↔ in-memory."""

    arxiv_id: str | None = None
    ss_paper_id: str | None = None
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    citation_count: int = 0
    influential_citation_count: int = 0
    citation_velocity: float | None = None
    topics: list[str] = field(default_factory=list)
    references: list[CitationEdge] = field(default_factory=list)
    cited_by: list[CitationEdge] = field(default_factory=list)
    figures: list[FigureRef] = field(default_factory=list)
    ingested_at: str | None = None
    pdf_path: str | None = None
    status: str | None = None

    @classmethod
    def from_frontmatter(cls, fm: dict) -> "Paper":
        return cls(
            arxiv_id=fm.get("arxiv_id"),
            ss_paper_id=fm.get("ss_paper_id"),
            title=fm.get("title"),
            authors=list(fm.get("authors") or []),
            year=fm.get("year"),
            venue=fm.get("venue"),
            citation_count=fm.get("citation_count", 0) or 0,
            influential_citation_count=fm.get("influential_citation_count", 0) or 0,
            citation_velocity=fm.get("citation_velocity"),
            topics=list(fm.get("topics") or []),
            references=[CitationEdge.from_dict(d) for d in (fm.get("references") or [])],
            cited_by=[CitationEdge.from_dict(d) for d in (fm.get("cited_by") or [])],
            figures=[FigureRef.from_dict(d) for d in (fm.get("figures") or [])],
            ingested_at=fm.get("ingested_at"),
            pdf_path=fm.get("pdf_path"),
            status=fm.get("status"),
        )

    def to_frontmatter(self) -> dict:
        """default(None / 빈 list / 0)인 필드는 생략 — frontmatter가 깔끔."""
        out: dict = {}
        # 키 순서는 ARCHITECTURE §5.1을 따른다 — 노트 가독성.
        if self.arxiv_id is not None:
            out["arxiv_id"] = self.arxiv_id
        if self.ss_paper_id is not None:
            out["ss_paper_id"] = self.ss_paper_id
        if self.title is not None:
            out["title"] = self.title
        if self.authors:
            out["authors"] = list(self.authors)
        if self.year is not None:
            out["year"] = self.year
        if self.venue is not None:
            out["venue"] = self.venue
        if self.citation_count:
            out["citation_count"] = self.citation_count
        if self.influential_citation_count:
            out["influential_citation_count"] = self.influential_citation_count
        if self.citation_velocity is not None:
            out["citation_velocity"] = self.citation_velocity
        if self.topics:
            out["topics"] = list(self.topics)
        if self.references:
            out["references"] = [e.to_dict() for e in self.references]
        if self.cited_by:
            out["cited_by"] = [e.to_dict() for e in self.cited_by]
        if self.figures:
            out["figures"] = [f.to_dict() for f in self.figures]
        if self.ingested_at is not None:
            out["ingested_at"] = self.ingested_at
        if self.pdf_path is not None:
            out["pdf_path"] = self.pdf_path
        if self.status is not None:
            out["status"] = self.status
        return out


__all__ = ["CitationEdge", "FigureRef", "Paper", "fields"]
