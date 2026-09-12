"""실행용 의존성 — SS 메타(디스크 캐시 경유), PDF 텍스트, 요약 에이전트를 잇는다."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from pydantic_ai.usage import UsageLimits

from agent.autopilot.agents import READ_PAGES, make_reader_agent, summarize_with_agent
from agent.autopilot.notes import NoteDraft, PaperMeta
from agent.autopilot.queue import Candidate
from analysis.ranking import citation_velocity
from sources.semantic_scholar import SS_BASE, lookup_error_message, resolve_id, ss_get
from tools.pdf_tools import read_paper

_PAGES = re.compile(r"\((\d+)/(\d+) 페이지\)")
_FIELDS = "paperId,title,authors,year,venue,citationCount,influentialCitationCount,externalIds"


class MetaUnavailable(RuntimeError):
    """SS가 거절했거나 논문을 찾지 못했다. 메시지의 ⏳/❌가 재시도 여부를 말한다."""


class StandaloneDeps:
    def __init__(self, model: Any, *, current_year: int | None = None, usage_limits: UsageLimits | None = None):
        self.model = model
        self.current_year = current_year or datetime.now(timezone.utc).year
        self.usage_limits = usage_limits
        self._agent = None

    @property
    def agent(self):
        if self._agent is None:
            self._agent = make_reader_agent(self.model)
        return self._agent

    async def fetch_meta(self, arxiv_id: str) -> PaperMeta:
        data = await ss_get(f"{SS_BASE}/{resolve_id(arxiv_id)}", {"fields": _FIELDS})
        err = lookup_error_message(arxiv_id, data)
        if err:
            raise MetaUnavailable(err)
        header = await read_paper(arxiv_id, max_pages=1)
        pages = _PAGES.search(header or "")
        return PaperMeta(
            arxiv_id=arxiv_id,
            ss_paper_id=str(data.get("paperId") or ""),
            title=str(data.get("title") or arxiv_id),
            authors=[a["name"] for a in data.get("authors") or [] if a.get("name")],
            year=data.get("year"),
            venue=str(data.get("venue") or ""),
            citation_count=int(data.get("citationCount") or 0),
            influential_citation_count=int(data.get("influentialCitationCount") or 0),
            citation_velocity=round(citation_velocity(data, self.current_year), 1),
            page_count=int(pages.group(2)) if pages else None,
        )

    async def source_text(self, arxiv_id: str) -> str:
        return await read_paper(arxiv_id, max_pages=READ_PAGES)

    async def summarize(
        self, candidate: Candidate, meta: PaperMeta, scope: list[str], allowed_hubs: set[str]
    ) -> NoteDraft:
        return await summarize_with_agent(self.agent, meta, scope, allowed_hubs, self.usage_limits)
