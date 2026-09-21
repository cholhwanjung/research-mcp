"""판정 에이전트 — provider 무관(pydantic-ai 모델 문자열 또는 Model), 구조화 출력.

- 요약(reader): 논문 본문(신뢰 경계 표지로 감싼 텍스트) + hub 정의·탐색 주제·vault 관련 노트 → NoteDraft.
  본문이 프롬프트에 없을 때만 `read_paper` 도구로 읽는다.
- scope 판정: 제목·초록 + scope hub·탐색 주제 정의 → ScopeVerdict.
- 인용 판정: anchor + 인용·참조 논문(초록·인용 문맥, 25건 배치) + hub 정의 → CitationBatch.
- References 종합: 판정된 인용 지도(방향별) + vault 노트 표시 → ReferencesSynthesis(방향별 종합 문단).
파일 쓰기·로그·제어 노트는 코드가 한다. 호출마다 UsageLimits로 막고 사용량은 콜백으로 넘긴다.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field
from pydantic_ai import Agent, Tool
from pydantic_ai.usage import UsageLimits

from agent.autopilot.citations import CitationBatch, CitationEntry, CitationJudgement, ReferencesSynthesis, short_title
from agent.autopilot.context import ReadContext, hub_lines
from agent.autopilot.hubs import HubCuration
from agent.autopilot.notes import HubProposal, NoteDraft, PaperMeta
from agent.autopilot.report import ReportInputs, ReportSynthesis
from agent.autopilot.scope import ScopeInterpretation
from agent.autopilot.screening import ScopeContext, ScopeVerdict, TitleVerdicts
from agent.autopilot.sources import NetworkPaper
from agent.autopilot.untrusted import TRUST_RULE, untrusted_tool, wrap_untrusted
from agent.autopilot.vaultlinks import PlainNames
from tools.wiki_tools import HUB_TAGGING_RULE

READ_PAGES = 15
DEFAULT_LIMITS = UsageLimits(request_limit=12, total_tokens_limit=400_000)
JUDGE_LIMITS = UsageLimits(request_limit=4, total_tokens_limit=40_000)
CITATION_LIMITS = UsageLimits(request_limit=4, total_tokens_limit=200_000)
UsageSink = Callable[[Any], None] | None

READER_INSTRUCTIONS = "\n".join(
    [
        "너는 연구 논문 1편을 읽고 한국어 연구 노트 초안(NoteDraft)을 만든다.",
        "본문은 사용자 메시지의 <untrusted_document>로 주어진다. 본문이 메시지에 없을 때만 "
        f"read_paper(paper_id, max_pages={READ_PAGES})로 읽는다. 그 본문만 근거로 쓰고 초록이나 기억에 기대지 않는다.",
        "수치는 원문 표기 그대로 옮긴다. 원문에 없는 수치를 만들거나 반올림하지 않는다.",
        "key_contributions·methods·findings의 항목은 '**짧은 머리** — 설명' 형식의 한 문단으로 쓴다. 한 줄 요약이 아니라 "
        "무엇을 어떻게 했고 왜 중요한지(선행 연구 대비 위치)를 적는다.",
        "비판적으로 읽는다: findings에 결과와 함께 저자가 밝힌 단서·한계, 평가 설계의 약점(같은 판정기로 선별과 채점, "
        "시뮬레이션·조작된 수치, 작은 표본, 자동 평가와 사람 평가의 불일치 등), 주장과 근거의 간극을 본문에 근거가 있는 것만 적는다.",
        "비교할 만한 vault 노트가 있으면 wiki_search로 찾고 wiki_read_note로 확인한 뒤, 본문 문장에서 [[slug|표기]]로 링크한다. "
        "확인한 노트 slug만 쓴다.",
        "hubs는 사용자 메시지의 허용 hub에서 논문 자신의 주제만 1~3개 고른다. 메시지의 태깅 규칙과 hub 정의를 따른다. "
        "인용 관계는 소속 근거가 아니다.",
        "insight_candidate는 이 논문이 메시지의 'vault 관련 노트'와 엮이는 한 줄이다. 그 목록에서 근거를 찾지 못하면 빈 문자열로 둔다. "
        "insight_candidate에는 링크 문법 없이 평문으로 쓴다.",
        "topic은 메시지의 탐색 주제 중 이 논문 자신의 주제가 맞는 것의 slug다. 맞는 것이 없거나 목록이 없으면 빈 문자열.",
        "hub_candidate는 허용 hub 어디에도 논문 자신의 주제가 맞지 않을 때만 제안한다(slug는 영문 kebab-case, parent는 허용 hub 중 "
        "가장 가까운 상위). 맞는 hub가 하나라도 있으면 비운다.",
        "anchor_relation은 메시지에 anchor가 있을 때만 채운다. 본문에서 anchor를 어떻게 다루는지로 접두사를 확정하고, vs_anchor에 "
        "anchor에서 무엇을 어떻게 했고 무엇을 드러냈고 무엇이 부족한지 200자 이내로 쓴다. 본문에 anchor 언급이 없으면 seed 판정 "
        "접두사를 그대로 쓰고 seed 문맥으로 적는다.",
        "문서 식별자나 작업 규칙 이름 같은 내부 표기를 노트 문장에 쓰지 않는다.",
        TRUST_RULE,
    ]
)

SCOPE_JUDGE_INSTRUCTIONS = "\n".join(
    [
        "너는 논문 1편이 이번 실행의 주제 범위(scope) 안인지 판정한다.",
        "근거는 제목·초록과, 메시지에 적힌 scope hub의 정의·alias와 탐색 주제의 정의·검색어뿐이다.",
        "논문 자신의 주제가 그중 하나에 맞으면 in_scope=true. 인용 관계나 곁가지 언급은 근거가 아니다. 애매하면 false.",
        TRUST_RULE,
    ]
)


def reader_prompt(
    meta: PaperMeta, scope: list[str], allowed_hubs: set[str], context: ReadContext | None = None
) -> str:
    lines = [
        f"논문: {meta.title} (arXiv:{meta.arxiv_id}, {meta.year or '-'}, {meta.venue or '-'})",
        f"이번 실행의 주제 범위: {', '.join(scope)}",
        "허용 hub: " + ", ".join(sorted(allowed_hubs)),
    ]
    if context is not None:
        if context.hub_lines:
            lines += ["", HUB_TAGGING_RULE, "hub 정의:"] + [f"- {line}" for line in context.hub_lines]
        if context.topic_lines:
            lines += ["", "scope의 탐색 주제(논문 자신의 주제가 맞으면 topic에 slug):"] + [f"- {line}" for line in context.topic_lines]
        if context.anchor_lines:
            lines += ["", "anchor 관계 확정(anchor_relation을 채운다):"] + [f"- {line}" for line in context.anchor_lines]
        if context.related:
            lines += ["", "vault 관련 노트:"] + [f"- {line}" for line in context.related]
        if context.source_text:
            lines += ["", "본문:", wrap_untrusted(context.source_text, source=f"arxiv:{meta.arxiv_id}")]
    lines += ["", "본문을 읽고 NoteDraft를 채워라."]
    return "\n".join(lines)


def make_reader_agent(
    model: Any, *, read_paper_fn: Callable[..., Awaitable[str]] | None = None, vault_tools: list[Callable] | None = None
) -> Agent:
    """요약 에이전트 — 논문 읽기(신뢰 경계 표지) + vault 읽기 전용 도구(검색·노트 읽기). 쓰기 도구는 없다."""
    if read_paper_fn is None:
        from tools.pdf_tools import read_paper as read_paper_fn
    if vault_tools is None:
        from tools.wiki_tools import wiki_read_note, wiki_search

        vault_tools = [wiki_search, wiki_read_note]
    tools = [Tool(untrusted_tool(read_paper_fn, source_prefix="arxiv", id_arg="paper_id"), name="read_paper"),
             *[Tool(fn) for fn in vault_tools]]
    return Agent(model, output_type=NoteDraft, instructions=READER_INSTRUCTIONS, tools=tools, retries=2)


async def summarize_with_agent(
    agent: Agent,
    meta: PaperMeta,
    scope: list[str],
    allowed_hubs: set[str],
    usage_limits: UsageLimits | None = None,
    *,
    context: ReadContext | None = None,
    on_usage: UsageSink = None,
) -> NoteDraft:
    result = await agent.run(
        reader_prompt(meta, scope, allowed_hubs, context), usage_limits=usage_limits or DEFAULT_LIMITS
    )
    if on_usage is not None:
        on_usage(result.usage)
    return result.output


def _scope_lines(ctx: ScopeContext) -> list[str]:
    lines = ["scope hub:"]
    lines += [f"- {line}" for line in hub_lines(ctx.hubs)] or ["- (없음)"]
    lines += ["", "scope 탐색 주제:"]
    for t in ctx.topics:
        if t.anchor:
            extra = f" · anchor {t.anchor} · 관계 {t.relation or '-'}"
        else:
            extra = f' · 검색어 "{t.query}"' if t.query else ""
        lines.append(f"- {t.slug} — {t.definition}{extra}")
    if not ctx.topics:
        lines.append("- (없음)")
    return lines


def scope_judge_prompt(meta: PaperMeta, ctx: ScopeContext) -> str:
    lines = [f"논문: {meta.title} (arXiv:{meta.arxiv_id}, {meta.year or '-'})", "", *_scope_lines(ctx)]
    lines += ["", "초록:", wrap_untrusted(meta.abstract or "(초록 없음)", source=f"abstract:{meta.arxiv_id}")]
    return "\n".join(lines)


def make_scope_judge(model: Any) -> Agent:
    return Agent(model, output_type=ScopeVerdict, instructions=SCOPE_JUDGE_INSTRUCTIONS, retries=2)


async def judge_scope_with_agent(
    agent: Agent,
    meta: PaperMeta,
    ctx: ScopeContext,
    usage_limits: UsageLimits | None = None,
    *,
    on_usage: UsageSink = None,
) -> ScopeVerdict:
    result = await agent.run(scope_judge_prompt(meta, ctx), usage_limits=usage_limits or JUDGE_LIMITS)
    if on_usage is not None:
        on_usage(result.usage)
    return result.output


CITATION_JUDGE_INSTRUCTIONS = "\n".join(
    [
        "너는 anchor 논문 1편의 인용 관계를 논문별로 분류한다.",
        "hubs는 메시지의 hub 목록에서 그 논문 자신의 주제만 고른다(맞는 hub가 없으면 빈 목록). anchor의 hub를 따라 붙이지 않는다.",
        "abstract_summary는 초록을 한국어 한 문장으로 쓴다. 초록이 없으면 제목으로 추정하지 말고 제목만 옮긴다.",
        "cited_for는 관계 접두사로 시작한다: [평가] anchor에서 결과를 보고 · [활용] 학습 데이터·환경·지표·백본으로 사용 · "
        "[비교] 후속·경쟁 벤치마크나 방법으로 대비 · [언급] 배경 인용 · 문맥이 없어 판정할 수 없으면 [평가?]. 접두사 뒤에 문맥 근거 한 줄.",
        "direction이 references면 anchor가 그 논문을 인용한 이유를, cited_by면 그 논문이 anchor를 인용한 방식을 적는다.",
        "group은 그래프에서 비슷한 논문을 묶을 짧은 이름(20자 이내)이다.",
        "usefulness는 메시지에 유용도 기준이 있을 때만 채운다.",
        "입력의 모든 항목에 대해 paper_id를 그대로 돌려준다.",
        "문서 식별자나 작업 규칙 이름 같은 내부 표기를 쓰지 않는다.",
        TRUST_RULE,
    ]
)

USEFULNESS_RULE = (
    "유용도(usefulness) — 제목·문맥·연도·velocity로 상/중/하. 상: anchor에서 새 방법·학습법·설계를 검증했거나 "
    "실패 모드·한계를 분석했거나 anchor(벤치마크·시스템) 자체를 비판·확장한 것 — 읽으면 인사이트가 나오는 것. "
    "중: anchor가 여러 평가 대상 중 하나지만 논문 주제가 이 탐색 주제의 방법론과 가깝거나, 문맥이 없어 [평가?]인 것. "
    "하: 점수만 보고한 것(모델 카드·기술 보고), 무관한 주제의 곁가지 평가. velocity·연도는 동률일 때만 본다."
)


def _clip_chars(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def citation_judge_prompt(
    meta: PaperMeta, direction: str, entries: list[CitationEntry], hub_lines_: list[str], *,
    relation: str | None = None, with_usefulness: bool = False,
) -> str:
    what = "anchor가 인용한 논문" if direction == "references" else "anchor를 인용한 논문"
    lines = [f"anchor: {meta.title} (arXiv:{meta.arxiv_id}, {meta.year or '-'})", f"direction: {direction} ({what})"]
    if relation:
        lines.append(f"relation: {relation} (이 탐색 주제가 찾는 관계)")
    lines += ["", "hub 목록:"] + ([f"- {line}" for line in hub_lines_] or ["- (없음)"])
    if with_usefulness:
        lines += ["", USEFULNESS_RULE]
    lines += ["", "항목:"]
    for i, e in enumerate(entries, 1):
        p = e.paper
        lines.append(f"[{i}] paper_id={p.arxiv_id} · {p.title} ({p.year or '-'}) · velocity {p.velocity:.1f}")
        lines.append(wrap_untrusted(_clip_chars(e.abstract, 1200) or "(초록 없음)", source=f"abstract:{p.arxiv_id}"))
        contexts = "\n".join(f"[{k}] {_clip_chars(c, 400)}" for k, c in enumerate(e.contexts[:3], 1)) or "(문맥 없음)"
        lines.append(wrap_untrusted(contexts, source=f"contexts:{p.arxiv_id}"))
    lines += ["", "모든 항목의 판정을 entries로 돌려라."]
    return "\n".join(lines)


def make_citation_judge(model: Any) -> Agent:
    return Agent(model, output_type=CitationBatch, instructions=CITATION_JUDGE_INSTRUCTIONS, retries=2)


async def judge_citations_with_agent(
    agent: Agent,
    meta: PaperMeta,
    direction: str,
    entries: list[CitationEntry],
    hub_lines_: list[str],
    *,
    relation: str | None = None,
    with_usefulness: bool = False,
    usage_limits: UsageLimits | None = None,
    on_usage: UsageSink = None,
) -> CitationBatch:
    prompt = citation_judge_prompt(meta, direction, entries, hub_lines_, relation=relation, with_usefulness=with_usefulness)
    result = await agent.run(prompt, usage_limits=usage_limits or CITATION_LIMITS)
    if on_usage is not None:
        on_usage(result.usage)
    return result.output


REFERENCES_SYNTH_INSTRUCTIONS = "\n".join(
    [
        "너는 논문 1편의 인용 지도를 읽고 방향마다 종합 문단을 쓴다. references는 이 논문이 인용한 연구, cited_by는 이 논문을 인용한 연구다.",
        "문단마다 3~6문장: 관계 접두사와 인용 근거로 역할별로 묶어 무엇으로 인용했는지 쓰고, 계보에서 중요한 연결을 짚는다.",
        "데이터 품질을 판단한다: 문맥 없이 제목으로만 판정된 항목([평가?]), 연구 내용과 어긋나 보이는 인용, "
        "velocity 상위만 본 목록이라 빠졌을 수 있는 직접 계보.",
        "항목에 'vault 노트'가 표시된 논문만 [[slug|표기]]로 링크한다.",
        "항목이 없는 방향은 빈 문자열로 둔다.",
        "문서 식별자나 작업 규칙 이름 같은 내부 표기를 쓰지 않는다.",
        TRUST_RULE,
    ]
)
SYNTH_LIMITS = UsageLimits(request_limit=3, total_tokens_limit=80_000)

CitationPairs = list[tuple[CitationJudgement, NetworkPaper]]


def references_synthesis_prompt(meta: PaperMeta, refs: CitationPairs, cites: CitationPairs, known: dict[str, str]) -> str:
    lines = [f"논문: {meta.title} (arXiv:{meta.arxiv_id}, {meta.year or '-'})", ""]
    for direction, pairs, what in (("references", refs, "이 논문이 인용한 연구"), ("cited_by", cites, "이 논문을 인용한 연구")):
        lines.append(f"{direction} — {what}, velocity 상위 {len(pairs)}편:")
        entries = []
        for judgement, paper in pairs:
            slug = known.get(paper.arxiv_id or "")
            note = f" · vault 노트: [[{slug}|{short_title(paper.title)}]]" if slug else ""
            entries.append(f"- {paper.arxiv_id} · {paper.title} ({paper.year or '-'}) · velocity {paper.velocity:.1f} · "
                           f"{judgement.cited_for} · {judgement.abstract_summary}{note}")
        lines.append(wrap_untrusted("\n".join(entries), source=f"citations:{direction}") if entries else "- (없음)")
        lines.append("")
    lines.append("references·cited_by 문단을 채워라.")
    return "\n".join(lines)


def make_references_synthesizer(model: Any) -> Agent:
    return Agent(model, output_type=ReferencesSynthesis, instructions=REFERENCES_SYNTH_INSTRUCTIONS, retries=2)


async def synthesize_references_with_agent(
    agent: Agent, meta: PaperMeta, refs: CitationPairs, cites: CitationPairs, known: dict[str, str], *,
    usage_limits: UsageLimits | None = None, on_usage: UsageSink = None,
) -> ReferencesSynthesis:
    result = await agent.run(references_synthesis_prompt(meta, refs, cites, known), usage_limits=usage_limits or SYNTH_LIMITS)
    if on_usage is not None:
        on_usage(result.usage)
    return result.output


HUB_CURATOR_INSTRUCTIONS = "\n".join(
    [
        "너는 vault의 hub(주제 축) 하나를 정리한다.",
        "mode가 create면 제안된 주제에 대해 후보 논문 중 그 논문 자신의 주제가 이 hub인 것만 members에 slug로 고른다. "
        "인용 관계나 곁가지 언급은 근거가 아니다. mode가 promote면 후보 전부가 이미 소속이니 모두 넣는다.",
        "title은 기존 hub처럼 영문 Title-Case 하이픈 표기, summary는 이 축이 무엇을 묻고 무엇으로 갈리는지 한두 문장, aliases는 영문 "
        "kebab-case 동의어 몇 개, intro는 본문 첫 인용구 한 문장이다.",
        "member_lines는 소속 논문마다 무엇을 했고 이 축에서 무엇을 보여주는지 한 줄이다. 수치는 후보 요약에 있는 것만 쓴다.",
        "within_intent는 이 주제가 scope 원문의 의도 안에 드는지, query는 이 주제를 arXiv에서 찾을 영어 검색어(4~8단어)다.",
        "문서 식별자나 작업 규칙 이름 같은 내부 표기를 쓰지 않는다.",
    ]
)


def hub_curator_prompt(proposal: HubProposal, candidates: list[dict], *, scope_input: str, mode: str,
                       hub_lines_: list[str]) -> str:
    lines = [
        f"mode: {mode}",
        f"scope 원문: {scope_input or '-'}",
        "",
        "제안 주제:",
        f"- slug: {proposal.slug}",
        f"- title: {proposal.title or '-'}",
        f"- summary: {proposal.summary or '-'}",
        f"- aliases: {', '.join(proposal.aliases) or '-'}",
        f"- parent: {proposal.parent or '-'}",
        "",
        "기존 hub:",
    ]
    lines += [f"- {line}" for line in hub_lines_] or ["- (없음)"]
    lines += ["", "후보 논문:"]
    lines += [f"- {c['slug']} — {c['title']} ({c.get('year') or '-'}) · {c.get('tldr') or '-'}" for c in candidates] or ["- (없음)"]
    return "\n".join(lines)


def make_hub_curator(model: Any) -> Agent:
    return Agent(model, output_type=HubCuration, instructions=HUB_CURATOR_INSTRUCTIONS, retries=2)


async def curate_hub_with_agent(
    agent: Agent,
    proposal: HubProposal,
    candidates: list[dict],
    *,
    scope_input: str,
    mode: str,
    hub_lines_: list[str],
    usage_limits: UsageLimits | None = None,
    on_usage: UsageSink = None,
) -> HubCuration:
    prompt = hub_curator_prompt(proposal, candidates, scope_input=scope_input, mode=mode, hub_lines_=hub_lines_)
    result = await agent.run(prompt, usage_limits=usage_limits or JUDGE_LIMITS)
    if on_usage is not None:
        on_usage(result.usage)
    return result.output


TITLE_JUDGE_INSTRUCTIONS = "\n".join(
    [
        "너는 논문 제목 목록에서 이번 실행의 주제 범위(scope) 안인 것을 고른다.",
        "근거는 제목과 메시지의 scope hub 정의·alias, 탐색 주제 정의·검색어뿐이다. 논문 자신의 주제가 그중 하나에 맞으면 in_scope에 "
        "paper_id를 넣는다. 애매하면 넣지 않는다.",
        TRUST_RULE,
    ]
)


def title_judge_prompt(items: list[tuple[str, str]], ctx: ScopeContext) -> str:
    listing = "\n".join(f"{paper_id} · {title}" for paper_id, title in items)
    return "\n".join([*_scope_lines(ctx), "", "후보(paper_id · 제목):", wrap_untrusted(listing, source="titles")])


def make_title_judge(model: Any) -> Agent:
    return Agent(model, output_type=TitleVerdicts, instructions=TITLE_JUDGE_INSTRUCTIONS, retries=2)


async def judge_titles_with_agent(
    agent: Agent,
    items: list[tuple[str, str]],
    ctx: ScopeContext,
    *,
    usage_limits: UsageLimits | None = None,
    on_usage: UsageSink = None,
) -> list[str]:
    result = await agent.run(title_judge_prompt(items, ctx), usage_limits=usage_limits or JUDGE_LIMITS)
    if on_usage is not None:
        on_usage(result.usage)
    allowed = {paper_id for paper_id, _ in items}
    return [paper_id for paper_id in dict.fromkeys(result.output.in_scope) if paper_id in allowed]


NAME_EXTRACTOR_INSTRUCTIONS = "\n".join(
    [
        "너는 hub 노트 본문에서 [[링크]] 없이 평문으로 부르는 특정 논문의 고유 이름을 뽑는다.",
        "개념·기법·데이터셋 일반명(MoE, BM25, SFT, RAG, transformer 등)과 일반 명사는 뽑지 않는다. 애매하면 뽑지 않는다.",
        "이미 [[...]] 안에 있는 표기는 뽑지 않는다. name은 본문 표기 그대로 쓴다.",
        "vault 논문 목록과 뜻으로 같은 논문이면 in_vault_slug에 그 slug를 넣는다(표기가 달라도 같은 논문이면 같다).",
        "본문에 그 이름의 arXiv ID가 함께 적혀 있을 때만 arxiv_id를 채운다. 기억으로 채우지 않는다.",
    ]
)


def name_extractor_prompt(hub_slug: str, body: str, vault_titles: list[tuple[str, str]]) -> str:
    listing = [f"- {slug} — {title}" for slug, title in vault_titles] or ["- (없음)"]
    return "\n".join([f"hub: {hub_slug}", "", "vault 논문 목록(slug — 제목):", *listing, "", "hub 본문:", body])


def make_name_extractor(model: Any) -> Agent:
    return Agent(model, output_type=PlainNames, instructions=NAME_EXTRACTOR_INSTRUCTIONS, retries=2)


async def extract_plain_names_with_agent(
    agent: Agent, hub_slug: str, body: str, vault_titles: list[tuple[str, str]], *,
    usage_limits: UsageLimits | None = None, on_usage: UsageSink = None,
) -> PlainNames:
    result = await agent.run(name_extractor_prompt(hub_slug, body, vault_titles),
                             usage_limits=usage_limits or CITATION_LIMITS)
    if on_usage is not None:
        on_usage(result.usage)
    return result.output


class TitleMatch(BaseModel):
    arxiv_id: str = Field(default="", description="참조가 가리키는 후보의 arXiv ID, 확신이 없으면 빈 문자열")


TITLE_MATCHER_INSTRUCTIONS = "\n".join(
    [
        "너는 vault가 부르는 논문 이름이 검색 후보 중 어느 논문인지 고른다.",
        "제목의 뜻이 같아야 한다. 저자·연도가 다르면 고르지 않는다. 확신이 없으면 빈 문자열로 둔다.",
        TRUST_RULE,
    ]
)


def title_matcher_prompt(name: str, context: str, hits: list) -> str:
    listing = "\n".join(f"{h.arxiv_id} · {h.title} ({h.year or '-'})" for h in hits)
    return "\n".join([f"참조 이름: {name}", f"vault 문맥: {context or '-'}", "", "후보(arXiv ID · 제목 (연도)):",
                      wrap_untrusted(listing or "(없음)", source="search")])


def make_title_matcher(model: Any) -> Agent:
    return Agent(model, output_type=TitleMatch, instructions=TITLE_MATCHER_INSTRUCTIONS, retries=2)


async def match_title_with_agent(
    agent: Agent, name: str, context: str, hits: list, *,
    usage_limits: UsageLimits | None = None, on_usage: UsageSink = None,
) -> str:
    result = await agent.run(title_matcher_prompt(name, context, hits), usage_limits=usage_limits or JUDGE_LIMITS)
    if on_usage is not None:
        on_usage(result.usage)
    chosen = result.output.arxiv_id.strip()
    return chosen if chosen in {h.arxiv_id for h in hits} else ""


SCOPE_INTERPRETER_INSTRUCTIONS = "\n".join(
    [
        "너는 사용자가 적은 이번 실행의 주제 범위(scope)를 vault 구조로 옮긴다.",
        "기존 hub에 닿는 부분은 hubs에 그 slug를 넣는다(자식 hub는 자동 포함되므로 가장 가까운 hub 하나면 된다).",
        "기존 탐색 주제와 같은 주제면 topics에 그 slug만 넣는다.",
        "hub에 닿지 않는 주제는 새 탐색 주제로 제안한다: slug(영문 kebab-case), definition 한 줄, query(arXiv 영어 검색어), "
        "parent(기존 hub 중 가장 가까운 상위).",
        "'X를 도전한/평가한/활용한/비교한 논문' 같은 관계 의도는 anchor 주제로 제안한다: anchor_name에 X 논문 이름, "
        "vault 논문 목록에 있으면 anchor_arxiv_id, relation. 벤치마크 이름이면 그 벤치마크를 제안한 논문이 anchor다. 이 해석이 hub "
        "alias 매칭보다 우선이다.",
        "relation은 기본 평가다. 'X를 학습·환경·데이터로 쓴 논문'이면 활용, 'X의 후속·경쟁 벤치마크'면 비교다. '후속 논문·후속 연구·"
        "도전한 논문'은 벤치마크가 아니라 논문을 뜻하므로 평가로 둔다.",
        "X가 hub 이름이면(예: 'hub X의 벤치마크를 도전한 논문') vault 논문 중 그 hub 소속이면서 hub 정의에 맞는 벤치마크·데이터셋 "
        "논문마다 anchor 주제를 따로 제안하고 anchor_hub에 그 hub slug, anchor_arxiv_id에 그 논문 ID를 넣는다. 개수는 줄이지 않는다.",
        "'전체'·'all'·'모든 hub'를 명시했을 때만 all=true. 빈 입력을 전체로 해석하지 않는다.",
        "arXiv ID는 목록에 있는 것만 쓴다. 기억으로 채우지 않는다.",
    ]
)


def scope_interpreter_prompt(text: str, hub_lines_: list[str], topics: list, papers: list[tuple[str, str, str]]) -> str:
    lines = [f"scope 원문: {text}", "", "기존 hub:"]
    lines += [f"- {line}" for line in hub_lines_] or ["- (없음)"]
    lines += ["", "기존 탐색 주제:"]
    for t in topics:
        extra = f" · anchor {t.anchor} · 관계 {t.relation or '-'}" if t.anchor else (f' · 검색어 "{t.query}"' if t.query else "")
        lines.append(f"- {t.slug} — {t.definition}{extra}")
    if not topics:
        lines.append("- (없음)")
    lines += ["", "vault 논문(slug — 제목 (arXiv:ID)):"]
    for paper in papers:
        slug, title, aid = paper[:3]
        line = f"- {slug} — {title} (arXiv:{aid or '-'})"
        if len(paper) >= 5:
            line += f" · topics {', '.join(paper[3]) or '-'} · vel {float(paper[4]):.1f}"
        lines.append(line)
    if not papers:
        lines.append("- (없음)")
    return "\n".join(lines)


def make_scope_interpreter(model: Any) -> Agent:
    return Agent(model, output_type=ScopeInterpretation, instructions=SCOPE_INTERPRETER_INSTRUCTIONS, retries=2)


async def interpret_scope_with_agent(
    agent: Agent, text: str, hub_lines_: list[str], topics: list, papers: list[tuple[str, str, str]], *,
    usage_limits: UsageLimits | None = None, on_usage: UsageSink = None,
) -> ScopeInterpretation:
    result = await agent.run(scope_interpreter_prompt(text, hub_lines_, topics, papers),
                             usage_limits=usage_limits or CITATION_LIMITS)
    if on_usage is not None:
        on_usage(result.usage)
    return result.output


REPORT_SYNTH_INSTRUCTIONS = "\n".join(
    [
        "너는 무인 수집 실행 보고서의 종합 문단을 쓴다. 근거는 메시지의 논문 TL;DR·통찰 후보·anchor 관계 줄뿐이다. "
        "새 조사나 추측을 하지 않는다.",
        "batch는 이번 배치가 말하는 것 2~3문장이다. 공통점이 근거로 서지 않으면 '종합할 공통점 없음'이라고만 쓴다.",
        "anchor_insights는 anchor 주제마다 member 줄만으로 공통 인사이트와 남은 한계를 2~3문장으로 쓴다. '공통 인사이트:' 같은 "
        "라벨 없이 문장만 쓴다.",
        "문서 식별자나 작업 규칙 이름 같은 내부 표기와 링크 문법을 쓰지 않는다.",
    ]
)


def report_synth_prompt(inputs: ReportInputs) -> str:
    lines = ["들어온 논문(제목 — TL;DR):"]
    lines += [f"- {title} — {tldr or '-'}" for title, tldr in inputs.papers] or ["- (없음)"]
    lines += ["", "통찰 후보:"]
    lines += [f"- {slug}: {text}" for slug, text in inputs.insights] or ["- (없음)"]
    lines += ["", "anchor 주제:"]
    for slug, anchor, relation, members in inputs.anchor_topics:
        lines.append(f"- {slug} (anchor {anchor or '-'} · 관계 {relation})")
        lines += [f"  - {line}" for line in members]
    if not inputs.anchor_topics:
        lines.append("- (없음)")
    return "\n".join(lines)


def make_report_synthesizer(model: Any) -> Agent:
    return Agent(model, output_type=ReportSynthesis, instructions=REPORT_SYNTH_INSTRUCTIONS, retries=2)


async def synthesize_report_with_agent(
    agent: Agent, inputs: ReportInputs, *, usage_limits: UsageLimits | None = None, on_usage: UsageSink = None,
) -> ReportSynthesis:
    result = await agent.run(report_synth_prompt(inputs), usage_limits=usage_limits or JUDGE_LIMITS)
    if on_usage is not None:
        on_usage(result.usage)
    return result.output
