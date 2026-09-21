"""노트 교차 비교 — ingest 직전 vault 되돌리기, 결정론 정확도 지표, 블라인드 쌍대 판정(순서 교차)·주장 감사(ADR-065).

판정 입력에는 작성 시스템을 드러내는 말을 넣지 않는다. 쌍대 판정은 두 노트의 순서를 바꿔 두 번 묻고,
두 답이 같은 노트를 가리킬 때만 승으로 친다(위치 편향 제거). 수치 대조는 분석 절(TL;DR~Related)만 본다 —
frontmatter·References의 인용 수·velocity는 원문이 아니라 메타데이터에서 온다.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agent.autopilot.verifier import unsupported, verify_numbers
from agent.evals.notes import ANALYSIS_SECTIONS, note_sections

CRITERIA = ("faithfulness", "critical_analysis", "specificity", "connection", "overall")
_INGEST = re.compile(r"^## \[[^\]]+\] autopilot \| iter=(\d+) \| action=ingest \| id=[^|]+\| slug=([\w.-]+)", re.M)
_INGEST_ID = re.compile(r"^## \[[^\]]+\] autopilot \| iter=\d+ \| action=ingest \| id=([^|\s]+)\s*\| slug=([\w.-]+)", re.M)
_LINK = re.compile(r"\[\[([^\]|#]+)")

Winner = Literal["1", "2", "tie"]

JUDGE_INSTRUCTIONS = (
    "너는 연구 노트 평가자다. 논문 원문 발췌와, 같은 논문을 읽고 쓴 연구 노트 두 개(노트 1·노트 2)를 받는다. "
    "기준마다 더 나은 노트를 '1' 또는 '2'로 고르고, 차이가 없으면 'tie'로 답한다. 길이·형식이 아니라 내용으로 판단한다. "
    "원문 발췌로 확인할 수 없는 주장·수치는 충실성에서 감점한다. 노트를 누가 어떻게 썼는지는 추측하지 않는다."
)
AUDIT_INSTRUCTIONS = (
    "너는 사실 검증자다. 논문 원문 발췌와 연구 노트 하나를 받는다. 노트의 사실 주장(수치·방법·실험 설정·결과·저자의 주장)을 "
    "원문과 하나씩 대조해, 원문과 어긋나거나 발췌에서 확인할 수 없는 주장만 나열한다. 해석·평가 의견은 사실 주장이 아니다."
)


class Winners(BaseModel):
    faithfulness: Winner = Field(description="원문 충실성 — 논문에 없는 주장·수치를 만들지 않았는가")
    critical_analysis: Winner = Field(description="비판적 분석 — 한계·평가 설계의 약점·주장과 근거의 간극을 짚는가")
    specificity: Winner = Field(description="구체성 — 방법·설정·수치를 구체적으로 전하는가")
    connection: Winner = Field(description="연결 — 다른 연구와의 관계를 유용하게 짓는가")
    overall: Winner = Field(description="연구 노트로서 종합")


class PairJudgement(BaseModel):
    winners: Winners
    reasons: str = Field(default="", description="판단 근거 요약")


class UnsupportedClaim(BaseModel):
    claim: str = Field(description="노트의 주장(짧게 인용)")
    why: str = Field(description="원문과 어긋나거나 확인할 수 없는 이유")


class ClaimAudit(BaseModel):
    claims_checked: int = Field(description="대조한 사실 주장 수")
    unsupported: list[UnsupportedClaim] = Field(default_factory=list)


@dataclass
class NoteAccuracy:
    analysis_chars: int
    numbers_checked: int
    numbers_unsupported: int
    unsupported_numbers: list[str]
    dangling_links: int
    linked_vault_papers: int


def ingest_iters(log_text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for iteration, slug in _INGEST.findall(log_text):
        out.setdefault(slug, int(iteration))
    return out


def ingest_arxiv_ids(log_text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for arxiv_id, slug in _INGEST_ID.findall(log_text):
        out.setdefault(slug, arxiv_id)
    return out


def rollback_vault(vault: Path, log_text: str, *, before_iter: int) -> list[str]:
    """그 반복부터 ingest된 논문 폴더를 지운다 — 그 논문이 들어가기 직전의 논문 집합으로 되돌린다."""
    removed = []
    for slug, iteration in sorted(ingest_iters(log_text).items(), key=lambda kv: (kv[1], kv[0])):
        folder = Path(vault) / "papers" / slug
        if iteration >= before_iter and folder.is_dir():
            shutil.rmtree(folder)
            removed.append(slug)
    return removed


def _analysis(note_text: str) -> dict[str, str]:
    sections = note_sections(note_text)
    return {name: sections[name] for name in ANALYSIS_SECTIONS if sections.get(name)}


def note_accuracy(note_text: str, source_text: str, *, paper_slugs: set[str], known_slugs: set[str]) -> NoteAccuracy:
    analysis = _analysis(note_text)
    body = "\n\n".join(analysis.values())
    checks = verify_numbers(body, source_text)
    bad = unsupported(checks)
    links = {target.strip() for target in _LINK.findall(body)}
    return NoteAccuracy(
        analysis_chars=sum(len(text) for text in analysis.values()),
        numbers_checked=len(checks),
        numbers_unsupported=len(bad),
        unsupported_numbers=[c.number for c in bad],
        dangling_links=len(links - known_slugs),
        linked_vault_papers=len(links & paper_slugs),
    )


def judge_text(note_text: str) -> str:
    return "\n\n".join(f"## {name}\n{text}" for name, text in _analysis(note_text).items())


def reconcile(first: str, swapped: str) -> str:
    """첫 순서(a=노트 1)와 뒤집은 순서(b=노트 1)의 답을 노트로 되돌린다. 둘이 다르면 inconsistent."""
    a = {"1": "a", "2": "b", "tie": "tie"}[first]
    b = {"1": "b", "2": "a", "tie": "tie"}[swapped]
    return a if a == b else "inconsistent"


def _pair_prompt(paper_text: str, first: str, second: str) -> str:
    return f"# 논문 원문 발췌\n{paper_text}\n\n# 노트 1\n{first}\n\n# 노트 2\n{second}"


async def judge_pair(model, paper_text: str, note_a: str, note_b: str) -> dict[str, str]:
    agent = Agent(model, instructions=JUDGE_INSTRUCTIONS, output_type=PairJudgement)
    first = (await agent.run(_pair_prompt(paper_text, note_a, note_b))).output.winners
    swapped = (await agent.run(_pair_prompt(paper_text, note_b, note_a))).output.winners
    return {c: reconcile(getattr(first, c), getattr(swapped, c)) for c in CRITERIA}


async def audit_claims(model, paper_text: str, note: str) -> ClaimAudit:
    agent = Agent(model, instructions=AUDIT_INSTRUCTIONS, output_type=ClaimAudit)
    return (await agent.run(f"# 논문 원문 발췌\n{paper_text}\n\n# 노트\n{note}")).output
