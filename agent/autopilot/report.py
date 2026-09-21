"""실행 보고서 — 재료는 로그뿐(노트를 다시 읽지 않는다).

마지막 정지 기록의 run_started 이후(진행 중이면 제어 노트의 run_started 이후) 항목을 모아 처리·source·건너뜀·보류·끊김·
새 hub·hub 후보, 들어온 논문, 탐색 주제(query seed 수·들어옴·승격 / anchor 회차·유용도·member별 vs_anchor), 통찰 후보를
집계한다. 종합 문단은 판정 에이전트가 TL;DR·통찰 후보·vs_anchor 줄만으로 쓴다. 파일은 `research-autopilot/<날짜>.md`
(같은 날 둘째면 `-2`), 논문은 `papers/<slug>` 평문 경로 — wikilink를 쓰지 않는다.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from agent.autopilot.citations import short_title
from agent.autopilot.control import ControlParseError, parse_control
from agent.autopilot.runlog import parse_entries
from agent.autopilot.topics import Topic, topics_by_slug
from wiki.frontmatter import dump_note, parse_note
from wiki.vault import resolve_paper_by_arxiv_id, vault_root, write_note

RUNNING = "진행 중"
NO_SYNTHESIS = "종합할 공통점 없음"
_ALIAS_LINK = re.compile(r"\[\[([^\]|]+)\|([^\]]+)\]\]")
_LINK = re.compile(r"\[\[([^\]]+)\]\]")


def plain(text: str | None) -> str:
    """wikilink를 표기만 남긴 평문으로."""
    return _LINK.sub(r"\1", _ALIAS_LINK.sub(r"\2", str(text or "")))


def _int(value: str | None) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _split(value: str | None) -> list[str]:
    return [x for x in str(value or "").split(",") if x and x != "-"]


@dataclass
class ReportPaper:
    title: str
    arxiv_id: str
    slug: str
    status: str
    source: str
    rank: str
    gate: str
    hubs: list[str]
    velocity: str
    tldr: str
    insight: str
    vs_anchor: str
    topic: str


@dataclass
class TopicReport:
    slug: str
    seeds_added: int = 0
    members_in: list[ReportPaper] = field(default_factory=list)
    anchor: str | None = None
    judged: int | None = None
    useful: tuple[int, int, int] | None = None


@dataclass
class RunReport:
    run_started: str
    stopped: str
    reason: str
    scope: list[str]
    ok: int = 0
    partial: int = 0
    failed: int = 0
    interrupted: int = 0
    skipped: int = 0
    scope_out: int = 0
    held: int = 0
    links_fixed: int = 0
    sources: Counter = field(default_factory=Counter)
    new_hubs: list[str] = field(default_factory=list)
    hub_candidates: list[str] = field(default_factory=list)
    papers: list[ReportPaper] = field(default_factory=list)
    topics: dict[str, TopicReport] = field(default_factory=dict)

    def topic(self, slug: str) -> TopicReport:
        return self.topics.setdefault(slug, TopicReport(slug))


def build_report(log_text: str, *, now: datetime | None = None, control_fm: dict | None = None) -> RunReport | None:
    entries = parse_entries(log_text)
    if control_fm and control_fm.get("stop") is False and control_fm.get("run_started"):
        report = RunReport(str(control_fm["run_started"]), now.strftime("%Y-%m-%d %H:%M") if now else "-", RUNNING,
                           [str(s) for s in control_fm.get("scope") or []])
        end = len(entries)
    else:
        stops = [i for i, e in enumerate(entries)
                 if e.header.action == "stop" and e.kv.get("run_started") not in (None, "", "-")]
        if not stops:
            return None
        stop = entries[stops[-1]]
        report = RunReport(stop.kv["run_started"], stop.header.ts, stop.header.fields.get("reason", "-"),
                           _split(stop.kv.get("scope")))
        end = stops[-1]
    since = report.run_started.replace("T", " ")
    for entry in entries[:end]:
        header, kv = entry.header, entry.kv
        if header.ts < since:
            continue
        if header.action == "ingest":
            status = header.fields.get("status")
            if kv.get("interrupted") not in (None, "", "-"):
                report.interrupted += 1
            if status == "fail":
                report.failed += 1
                continue
            if status not in ("ok", "partial"):
                continue
            report.ok += status == "ok"
            report.partial += status == "partial"
            paper = ReportPaper(
                title=kv.get("title") or header.fields.get("id", "-"), arxiv_id=header.fields.get("id", "-"),
                slug=header.fields.get("slug", "-"), status=status, source=kv.get("source", "-"),
                rank=kv.get("rank", "-"), gate=kv.get("gate", "-"), hubs=_split(kv.get("hubs")),
                velocity=kv.get("velocity", "-"), tldr=kv.get("tldr", ""), insight=kv.get("insight_candidate", ""),
                vs_anchor=kv.get("vs_anchor", ""), topic=kv.get("topic", "-"),
            )
            report.papers.append(paper)
            report.sources[paper.source] += 1
            report.held += _int(kv.get("held"))
            report.scope_out += _int(kv.get("scope_out"))
            report.links_fixed += _int(kv.get("links_fixed"))
            report.new_hubs += [h for h in _split(kv.get("new_hub")) if h not in report.new_hubs]
            report.hub_candidates += [h for h in _split(kv.get("hub_candidate")) if h not in report.hub_candidates]
            if paper.topic not in ("", "-"):
                report.topic(paper.topic).members_in.append(paper)
        elif header.action == "skip":
            report.skipped += _int(kv.get("skipped"))
            report.held += _int(kv.get("held"))
            report.scope_out += _int(kv.get("scope_out"))
        elif header.action == "refill" and header.fields.get("source") == "S0" and header.fields.get("topic"):
            topic = report.topic(header.fields["topic"])
            topic.seeds_added += _int(header.fields.get("added"))
            if header.fields.get("anchor"):
                topic.anchor = header.fields["anchor"]
                topic.judged = _int(header.fields.get("judged"))
                useful = [_int(x) for x in header.fields.get("useful", "").split("/")]
                topic.useful = tuple(useful) if len(useful) == 3 else None
    return report


def _split_prefix(text: str) -> tuple[str, str]:
    text = plain(text).strip()
    if text.startswith("[") and "]" in text:
        end = text.index("]") + 1
        return text[:end], text[end:].strip()
    return "", text


def render_report(report: RunReport, *, synthesis: str, anchor_insights: dict[str, str], topics: dict[str, Topic],
                  anchor_titles: dict[str, str]) -> str:
    tail = RUNNING if report.reason == RUNNING else f"정지: {report.reason}"
    src = report.sources
    lines = [
        f"# autopilot 실행 보고 — {report.run_started.replace('T', ' ')} → {report.stopped} · {tail}",
        "",
        f"처리 {report.ok + report.partial}편 (ok {report.ok} · partial {report.partial}) · source: 우선 큐 {src['P0']} "
        f"· 깨진 링크 {src['S1']} · hub 평문 {src['S2']} · seed {src['S0']} · 백필 {src['PA']} · frontier {src['F']} "
        f"· 건너뜀 {report.skipped}(scope 밖 {report.scope_out}) · 보류 {report.held} · 끊김 {report.interrupted} "
        f"· 새 hub: {', '.join(report.new_hubs) or '-'} · hub 후보: {', '.join(report.hub_candidates) or '-'}",
    ]
    if report.papers and all(p.source == "PA" for p in report.papers):
        lines.append("⚠️ 신규 유입 없음 — scope 안 새 후보가 고갈되어 백필만 돌았다. scope를 넓히거나 우선 큐를 채울 때")

    lines += ["", "## 들어온 논문"]
    for i, p in enumerate(report.papers, 1):
        parts = [f"{i}. {plain(p.title)} (arXiv:{p.arxiv_id}) — papers/{p.slug}", f"{p.rank}/{p.source}", p.gate]
        if p.hubs:
            parts.append(", ".join(p.hubs))
        parts.append(f"vel {p.velocity}")
        if p.status == "partial":
            parts.append("partial")
        line = " · ".join(parts)
        if p.tldr and p.tldr != "-":
            line += f" / {plain(p.tldr)}"
        lines.append(line)
    if not report.papers:
        lines.append("- (없음)")

    if report.topics:
        lines += ["", "## 탐색 주제"]
        for slug, tr in report.topics.items():
            ctl = topics.get(slug)
            anchor = tr.anchor or (ctl.anchor if ctl else None)
            if anchor:
                judged = tr.judged if tr.judged is not None else (ctl.judged if ctl and ctl.judged is not None else "-")
                relation = ctl.relation if ctl and ctl.relation else "-"
                useful = "유용 상 {}/중 {}/하 {}".format(*tr.useful) if tr.useful else "이번 실행 회차 없음"
                lines.append(f"- {slug} (anchor {anchor_titles.get(anchor, anchor)} · {relation} · judged {judged} "
                             f"· {useful}): 들어옴 {len(tr.members_in)}편")
                for p in tr.members_in:
                    prefix, rest = _split_prefix(p.vs_anchor)
                    head = f"{prefix} {short_title(plain(p.title))}".strip()
                    lines.append(f"  - {head} — {rest}" if rest else f"  - {head}")
                insight = plain(anchor_insights.get(slug)).strip()
                if insight:
                    labelled = insight.startswith(("공통 인사이트", "남은 한계"))
                    lines.append(f"  - {insight}" if labelled else f"  - 공통 인사이트 / 남은 한계: {insight}")
            else:
                promoted = slug if slug in report.new_hubs else "-"
                lines.append(f"- {slug}: seed {tr.seeds_added}건 · 들어옴 {len(tr.members_in)}편 · 승격 {promoted}")

    insights = [(p.slug, plain(p.insight)) for p in report.papers if p.insight and p.insight != "-"]
    lines += ["", "## 통찰 후보 — 저장되지 않았다. 고르면 insight-capture 초안 모드로"]
    lines += [f"- {slug}: {text}" for slug, text in insights] or ["- (없음)"]
    lines += ["", "## 이번 배치가 말하는 것", plain(synthesis).strip() or NO_SYNTHESIS]

    todo = []
    if report.papers:
        todo.append(f"- figure/table on-demand 후보 {len(report.papers)}편 — 필요한 논문만 추출")
    if report.hub_candidates:
        todo.append(f"- hub 후보 검토: {', '.join(report.hub_candidates)}")
    if report.new_hubs:
        todo.append(f"- 새 hub 확인: {', '.join(report.new_hubs)}")
    for label, marker in (("query 수정(seed 0건)", "(0건)"), ("seed 실패 확인", "(실패)"), ("소진", "(소진)")):
        hit = [t.slug for t in topics.values() if t.seeded.endswith(marker)]
        if hit:
            todo.append(f"- 탐색 주제 {label}: {', '.join(hit)}")
    todo.append(f"- 보류 {report.held}건 · scope 밖 {report.scope_out}건")
    touched = sorted({h for p in report.papers for h in p.hubs})
    if touched:
        todo.append(f"- hub 요약 점검(wiki-lint): {', '.join(touched)}")
    lines += ["", "## 아침 할 일", *todo]
    return "\n".join(lines) + "\n"


def write_report_file(text: str, report: RunReport) -> Path:
    day = report.stopped[:10] if report.stopped[:4].isdigit() else date.today().isoformat()
    base = vault_root() / "research-autopilot"
    base.mkdir(parents=True, exist_ok=True)
    path, n = base / f"{day}.md", 2
    while path.exists():
        path, n = base / f"{day}-{n}.md", n + 1
    fm = {"type": "autopilot-report", "date": day, "run_started": report.run_started,
          "stopped": report.stopped.replace(" ", "T"), "scope": report.scope, "reason": report.reason,
          "processed": report.ok + report.partial}
    write_note(path, dump_note(fm, text))
    return path


@dataclass
class ReportInputs:
    papers: list[tuple[str, str]] = field(default_factory=list)
    insights: list[tuple[str, str]] = field(default_factory=list)
    anchor_topics: list[tuple[str, str, str, list[str]]] = field(default_factory=list)


class AnchorInsight(BaseModel):
    slug: str
    text: str = Field(description="member 줄만으로 공통 인사이트와 남은 한계 2~3문장")


class ReportSynthesis(BaseModel):
    batch: str = Field(description="이번 배치가 말하는 것 2~3문장. 근거가 서지 않으면 '종합할 공통점 없음'")
    anchor_insights: list[AnchorInsight] = Field(default_factory=list)


def _anchor_title(anchor: str) -> str:
    path = resolve_paper_by_arxiv_id(anchor)
    if path is None:
        return anchor
    fm, _ = parse_note(path.read_text(encoding="utf-8"))
    return short_title(str((fm or {}).get("title") or anchor))


async def run_report(deps, now: datetime, *, save: bool) -> tuple[str, Path | None]:
    log_path = vault_root() / "_meta" / "autopilot-log.md"
    log_text = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
    try:
        control = parse_control((vault_root() / "_meta" / "autopilot.md").read_text(encoding="utf-8"))
    except (FileNotFoundError, ControlParseError):
        control = None
    report = build_report(log_text, now=now, control_fm=control.frontmatter if control else None)
    if report is None:
        return "보고할 실행 기록이 없다 — 정지 기록도 진행 중인 실행도 없다", None
    topics = topics_by_slug(control) if control else {}
    anchors = {t.anchor for t in topics.values() if t.anchor} | {t.anchor for t in report.topics.values() if t.anchor}
    anchor_titles = {a: _anchor_title(a) for a in anchors}

    synthesis, anchor_insights = NO_SYNTHESIS, {}
    synthesize = getattr(deps, "synthesize_report", None)
    if synthesize is not None and report.papers:  # 종합할 논문이 없으면 모델을 부르지 않는다
        inputs = ReportInputs(
            papers=[(plain(p.title), plain(p.tldr)) for p in report.papers],
            insights=[(p.slug, plain(p.insight)) for p in report.papers if p.insight and p.insight != "-"],
            anchor_topics=[
                (slug, anchor_titles.get(tr.anchor or topics[slug].anchor, ""), topics[slug].relation or "-" if slug in topics else "-",
                 [f"{_split_prefix(p.vs_anchor)[0]} {short_title(plain(p.title))} — {_split_prefix(p.vs_anchor)[1]}".strip()
                  for p in tr.members_in])
                for slug, tr in report.topics.items()
                if tr.members_in and (tr.anchor or (slug in topics and topics[slug].anchor))
            ],
        )
        try:
            out = await synthesize(inputs)
            synthesis = out.batch.strip() or NO_SYNTHESIS
            anchor_insights = {a.slug: a.text for a in out.anchor_insights}
        except Exception as e:
            synthesis = f"{NO_SYNTHESIS} (종합 판정 실패: {type(e).__name__})"
    text = render_report(report, synthesis=synthesis, anchor_insights=anchor_insights, topics=topics,
                         anchor_titles=anchor_titles)
    return text, write_report_file(text, report) if save else None
