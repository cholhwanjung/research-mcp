"""실행용 의존성 — SS 메타(디스크 캐시 경유), PDF 텍스트, 판정 에이전트를 잇는다.

도구 함수의 상태 표지(❌·⚠️·⏳)는 여기서 ToolFailure로 바꾼다 — 오류 문구가 본문으로 요약되지 않게.
에이전트 호출의 사용량은 반복 단위로 모았다가 `take_usage()`로 넘긴다.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from pydantic_ai.usage import UsageLimits

from agent.autopilot.agents import (
    READ_PAGES,
    curate_hub_with_agent,
    extract_plain_names_with_agent,
    interpret_scope_with_agent,
    judge_citations_with_agent,
    judge_scope_with_agent,
    judge_titles_with_agent,
    make_citation_judge,
    make_hub_curator,
    make_name_extractor,
    make_report_synthesizer,
    make_scope_interpreter,
    make_title_judge,
    make_title_matcher,
    match_title_with_agent,
    synthesize_references_with_agent,
    synthesize_report_with_agent,
    make_reader_agent,
    make_references_synthesizer,
    make_scope_judge,
    summarize_with_agent,
)
from agent.autopilot.citations import CitationBatch, CitationEntry, ReferencesSynthesis
from agent.autopilot.context import ReadContext, hub_lines
from agent.autopilot.failures import MetaUnavailable, check_tool_output
from agent.autopilot.hubs import HubCuration
from agent.autopilot.notes import HubProposal, NoteDraft, PaperMeta
from agent.autopilot.queue import Candidate
from agent.autopilot.screening import ScopeContext, ScopeVerdict
from agent.autopilot.report import ReportInputs, ReportSynthesis
from agent.autopilot.scope import ScopeInterpretation
from agent.autopilot.vaultlinks import PlainNames, vault_paper_details
from agent.autopilot.sources import ArxivHit, NetworkPaper, fetch_citations, fetch_contexts, fetch_references, search_arxiv
from analysis.ranking import citation_velocity
from sources.semantic_scholar import SS_BASE, lookup_error_message, resolve_id, ss_get
from tools.pdf_tools import read_paper

_PAGES = re.compile(r"\((\d+)/(\d+) 페이지\)")
_FIELDS = "paperId,title,authors,year,venue,citationCount,influentialCitationCount,externalIds,abstract"


class StandaloneDeps:
    def __init__(self, model: Any, *, current_year: int | None = None, usage_limits: UsageLimits | None = None):
        self.model = model
        self.current_year = current_year or datetime.now(timezone.utc).year
        self.usage_limits = usage_limits
        self._agent = None
        self._scope_judge = None
        self._citation_judge = None
        self._hub_curator = None
        self._title_judge = None
        self._name_extractor = None
        self._title_matcher = None
        self._scope_interpreter = None
        self._report_synthesizer = None
        self._references_synthesizer = None
        self._tokens = 0
        self._requests = 0
        self._used = False

    @property
    def agent(self):
        if self._agent is None:
            self._agent = make_reader_agent(self.model)
        return self._agent

    @property
    def scope_judge(self):
        if self._scope_judge is None:
            self._scope_judge = make_scope_judge(self.model)
        return self._scope_judge

    @property
    def citation_judge(self):
        if self._citation_judge is None:
            self._citation_judge = make_citation_judge(self.model)
        return self._citation_judge

    def _add_usage(self, usage: Any) -> None:
        self._tokens += int(getattr(usage, "input_tokens", 0) or 0) + int(getattr(usage, "output_tokens", 0) or 0)
        self._requests += int(getattr(usage, "requests", 0) or 0)
        self._used = True

    def take_usage(self) -> dict | None:
        if not self._used:
            return None
        out = {"tokens": self._tokens, "requests": self._requests}
        self._tokens, self._requests, self._used = 0, 0, False
        return out

    async def paper_info(self, arxiv_id: str) -> PaperMeta:
        """SS 메타·초록만 — PDF를 건드리지 않는다(스크리닝용)."""
        data = await ss_get(f"{SS_BASE}/{resolve_id(arxiv_id)}", {"fields": _FIELDS})
        err = lookup_error_message(arxiv_id, data)
        if err:
            raise MetaUnavailable(err)
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
            page_count=None,
            abstract=str(data.get("abstract") or ""),
        )

    async def fetch_meta(self, arxiv_id: str) -> PaperMeta:
        meta = await self.paper_info(arxiv_id)
        header = check_tool_output(await read_paper(arxiv_id, max_pages=1))
        pages = _PAGES.search(header)
        meta.page_count = int(pages.group(2)) if pages else None
        return meta

    async def source_text(self, arxiv_id: str) -> str:
        """본문 텍스트 — 도구 머리줄(📄 쪽수·🔗 URL·⚠️ 쪽 제한 안내)은 뺀다. 쪽 제한은 정상 동작이라 경고가 아니다."""
        text = check_tool_output(await read_paper(arxiv_id, max_pages=READ_PAGES))
        at = text.find("--- Page ")
        head = text[:at] if at > 0 else ""
        if head and all(not line.strip() or line.lstrip().startswith(("📄", "🔗", "⚠")) for line in head.splitlines()):
            return text[at:]
        return text

    async def summarize(
        self,
        candidate: Candidate,
        meta: PaperMeta,
        scope: list[str],
        allowed_hubs: set[str],
        context: ReadContext | None = None,
    ) -> NoteDraft:
        return await summarize_with_agent(
            self.agent, meta, scope, allowed_hubs, self.usage_limits, context=context, on_usage=self._add_usage
        )

    async def judge_scope(self, meta: PaperMeta, ctx: ScopeContext) -> ScopeVerdict:
        return await judge_scope_with_agent(self.scope_judge, meta, ctx, on_usage=self._add_usage)


    async def references(self, arxiv_id: str, *, top_k: int, min_velocity: float) -> list[NetworkPaper]:
        return await fetch_references(arxiv_id, top_k=top_k, min_velocity=min_velocity, current_year=self.current_year)

    async def citations(
        self, arxiv_id: str, *, top_k: int, min_velocity: float, exclude_recent_year: bool, max_fetch: int = 1000
    ) -> list[NetworkPaper]:
        return await fetch_citations(arxiv_id, top_k=top_k, min_velocity=min_velocity,
                                     exclude_recent_year=exclude_recent_year, current_year=self.current_year,
                                     max_fetch=max_fetch)

    async def contexts(self, citing_id: str, cited_id: str) -> list[str]:
        return await fetch_contexts(citing_id, cited_id)

    async def search(self, query: str, max_results: int = 20) -> list[ArxivHit]:
        return await search_arxiv(query, max_results)

    async def judge_citations(
        self, meta: PaperMeta, direction: str, entries: list[CitationEntry], hubs: list[dict], *,
        relation: str | None = None, with_usefulness: bool = False,
    ) -> CitationBatch:
        return await judge_citations_with_agent(
            self.citation_judge, meta, direction, entries, hub_lines(hubs),
            relation=relation, with_usefulness=with_usefulness, on_usage=self._add_usage,
        )

    async def curate_hub(self, proposal: HubProposal, candidates: list[dict], *, scope_input: str, mode: str) -> HubCuration:
        from wiki.vault import list_hubs

        if self._hub_curator is None:
            self._hub_curator = make_hub_curator(self.model)
        return await curate_hub_with_agent(
            self._hub_curator, proposal, candidates, scope_input=scope_input, mode=mode,
            hub_lines_=hub_lines(list_hubs()), on_usage=self._add_usage,
        )

    async def judge_titles(self, items: list[tuple[str, str]], ctx: ScopeContext) -> list[str]:
        if self._title_judge is None:
            self._title_judge = make_title_judge(self.model)
        return await judge_titles_with_agent(self._title_judge, items, ctx, on_usage=self._add_usage)

    async def extract_plain_names(self, hub_slug: str, body: str, vault_titles: list[tuple[str, str]]) -> PlainNames:
        if self._name_extractor is None:
            self._name_extractor = make_name_extractor(self.model)
        return await extract_plain_names_with_agent(self._name_extractor, hub_slug, body, vault_titles,
                                                    on_usage=self._add_usage)

    async def match_title(self, name: str, context: str, hits: list[ArxivHit]) -> str:
        if self._title_matcher is None:
            self._title_matcher = make_title_matcher(self.model)
        return await match_title_with_agent(self._title_matcher, name, context, hits, on_usage=self._add_usage)

    async def interpret_scope(self, text: str, hubs: list[dict], topics: list) -> ScopeInterpretation:
        if self._scope_interpreter is None:
            self._scope_interpreter = make_scope_interpreter(self.model)
        return await interpret_scope_with_agent(self._scope_interpreter, text, hub_lines(hubs), topics,
                                                vault_paper_details(), on_usage=self._add_usage)

    async def synthesize_report(self, inputs: ReportInputs) -> ReportSynthesis:
        if self._report_synthesizer is None:
            self._report_synthesizer = make_report_synthesizer(self.model)
        return await synthesize_report_with_agent(self._report_synthesizer, inputs, on_usage=self._add_usage)

    async def synthesize_references(self, meta: PaperMeta, refs: list, cites: list, known: dict[str, str]) -> ReferencesSynthesis:
        if self._references_synthesizer is None:
            self._references_synthesizer = make_references_synthesizer(self.model)
        return await synthesize_references_with_agent(self._references_synthesizer, meta, refs, cites, known,
                                                      on_usage=self._add_usage)
