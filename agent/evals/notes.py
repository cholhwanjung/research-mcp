"""노트 품질 지표 — 같은 논문의 스킬 모드 노트와 독립 런타임 노트를 결정론 지표로 나란히 본다(ADR-064).

실행은 원본을 건드리지 않는 vault 복사본에서 한다: 기준 노트를 복사본에서 빼고, 그 논문만 우선 큐에 넣어
독립 런타임 한 반복을 돌린다.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from agent.autopilot.control import parse_control, render_control
from agent.autopilot.runner import IterationOutcome, run_iteration
from agent.evals.intents import prepare_vault, vault_env

ANALYSIS_SECTIONS = ("TL;DR", "Key Contributions", "Methods", "Findings", "Related")
_ITEM_SECTIONS = ("Key Contributions", "Methods", "Findings")
_HEADER = re.compile(r"^## (.+?)[ \t]*$", re.MULTILINE)
_LINK = re.compile(r"\[\[([^\]|#]+)")


@dataclass
class NoteMetrics:
    analysis_chars: int = 0
    references_chars: int = 0
    linked_vault_papers: int = 0
    paper_links_in_analysis: int = 0
    bold_items: int = 0


@dataclass
class NoteComparison:
    outcome: IterationOutcome
    reference: NoteMetrics
    candidate: NoteMetrics
    candidate_text: str


def note_sections(text: str) -> dict[str, str]:
    body = text.split("\n# ", 1)[1] if "\n# " in text else text
    headers = list(_HEADER.finditer(body))
    sections: dict[str, str] = {}
    for i, m in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(body)
        sections[m.group(1)] = body[m.end():end].strip()
    return sections


def note_metrics(text: str, vault_papers: set[str]) -> NoteMetrics:
    sections = note_sections(text)
    links = {t.strip() for t in _LINK.findall("\n".join(sections.values()))}
    in_analysis = [
        t for name in ANALYSIS_SECTIONS[:4] for t in _LINK.findall(sections.get(name, "")) if t.strip() in vault_papers
    ]
    bold = sum(
        1 for name in _ITEM_SECTIONS for line in sections.get(name, "").splitlines() if line.startswith("- **")
    )
    return NoteMetrics(
        analysis_chars=sum(len(sections.get(name, "")) for name in ANALYSIS_SECTIONS),
        references_chars=len(sections.get("References", "")),
        linked_vault_papers=len(links & vault_papers),
        paper_links_in_analysis=len(in_analysis),
        bold_items=bold,
    )


def prepare_note_vault(source: Path, workdir: Path, *, arxiv_id: str, reference_slug: str) -> tuple[Path, str]:
    """복사본을 만들고 기준 노트를 빼낸 뒤, 그 논문 하나만 우선 큐에 둔다. (복사본 경로, 기준 노트 원문)."""
    source, workdir = Path(source), Path(workdir)
    vault = prepare_vault(source, workdir / "vault")
    pdf = source / "pdfs" / f"{arxiv_id}.pdf"
    if pdf.is_file():
        shutil.copy2(pdf, vault / "pdfs" / pdf.name)
    ref_dir = vault / "papers" / reference_slug
    reference = (ref_dir / f"{reference_slug}.md").read_text(encoding="utf-8")
    shutil.rmtree(ref_dir)

    control = vault / "_meta" / "autopilot.md"
    note = parse_control(control.read_text(encoding="utf-8"))
    for section in ("우선 큐", "건너뜀", "보류", "frontier"):
        for item in note.items(section):
            if section == "우선 큐" or arxiv_id in item:
                note.remove_exact(section, item)
    note.add_item("우선 큐", arxiv_id)
    control.write_text(render_control(note), encoding="utf-8")
    return vault, reference


async def run_note_eval(
    deps, *, vault: Path, reference_text: str, reference_slug: str, now: datetime | None = None
) -> NoteComparison:
    vault = Path(vault)
    with vault_env(vault):
        outcome = await run_iteration(deps, scope_arg="all", max_papers_arg=1, now=now or datetime.now())
    candidate_text = ""
    if outcome.slug:
        path = vault / "papers" / outcome.slug / f"{outcome.slug}.md"
        if path.is_file():
            candidate_text = path.read_text(encoding="utf-8")
    papers = {p.name for p in (vault / "papers").iterdir() if p.is_dir()} | {reference_slug}
    return NoteComparison(outcome, note_metrics(reference_text, papers), note_metrics(candidate_text, papers), candidate_text)


def comparison_lines(cmp: NoteComparison) -> list[str]:
    def line(name: str, m: NoteMetrics) -> str:
        return (
            f"note={name} analysis_chars={m.analysis_chars} references_chars={m.references_chars} "
            f"linked_vault_papers={m.linked_vault_papers} paper_links_in_analysis={m.paper_links_in_analysis} "
            f"bold_items={m.bold_items}"
        )

    o = cmp.outcome
    return [
        line("reference", cmp.reference),
        line("candidate", cmp.candidate),
        f"action={o.action} status={o.status or '-'} slug={o.slug or '-'} unverified_numbers={len(o.unverified_numbers)}",
    ]
