"""한 반복(논문 1편)을 코드가 조율한다 — 스킬 모드 워커 절차의 독립 런타임판.

게이트·대기열·로그·제어 노트 갱신·노트 쓰기·수치 대조는 코드, 메타 조회·요약은 주입된
의존성이 맡는다. 이 판이 아직 하지 않는 것: 인용 분석(references·cited_by), hub 본문의
평문 논문명·깨진 링크 후보, seed·리필, 탐색 주제 소속·hub 승격 — 로그의
`runtime=standalone` 논문은 스킬 모드의 백필이 이어받는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from agent.autopilot.control import ControlNote, ControlParseError, item_key, parse_control, render_control
from agent.autopilot.gate import decide
from agent.autopilot.notes import (
    NoteDraft,
    PaperMeta,
    VaultIsolationError,
    draft_text,
    render_paper_note,
    write_rendered_note,
)
from agent.autopilot.queue import Candidate, ordered_queue
from agent.autopilot.runlog import append_entry, format_header, format_kv, open_start, read_tail_headers
from agent.autopilot.verifier import unsupported, verify_numbers
from wiki.vault import list_hubs, read_paper_frontmatters, resolve_paper_by_arxiv_id, vault_root

RUNTIME = "standalone"
_FAILURE_LIMIT = 3
_TEXT_LIMIT = 200
_CONTROL_TEMPLATE = """---
stop: true
max_papers: 0
min_velocity: 10
scope: []
scope_input: ''
run_started: ''
processed: 0
consecutive_failures: 0
frontier_anchors: []
deleted_jobs: []
explore: false
max_topics: 3
---
# Autopilot 제어

## 우선 큐
사용자 지정. 한 줄 = 한 항목. 대기열보다 먼저, 처리되면 줄 삭제. scope 필터 없음.

## 건너뜀
autopilot이 풀지 못한 항목. 줄을 지우면 재시도.

## 보류
중요도 미달. 재평가일 지나면 다시 후보.

## frontier
대기열이 비었을 때 리필된 후보와 탐색 주제 seed. velocity 순. 처리되면 줄 삭제.

## 탐색 주제
scope의 자연어 중 hub에 없는 주제.
"""


class AutopilotDeps(Protocol):
    async def fetch_meta(self, arxiv_id: str) -> PaperMeta: ...

    async def summarize(
        self, candidate: Candidate, meta: PaperMeta, scope: list[str], allowed_hubs: set[str]
    ) -> NoteDraft: ...

    async def source_text(self, arxiv_id: str) -> str: ...


@dataclass
class IterationOutcome:
    action: str
    iter: int = 0
    arxiv_id: str | None = None
    slug: str | None = None
    status: str | None = None
    stop_reason: str | None = None
    unverified_numbers: list[str] = field(default_factory=list)
    message: str = ""


def _control_path():
    return vault_root() / "_meta" / "autopilot.md"


def _log_path():
    return vault_root() / "_meta" / "autopilot-log.md"


def _load_control() -> ControlNote:
    path = _control_path()
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_CONTROL_TEMPLATE, encoding="utf-8")
    return parse_control(path.read_text(encoding="utf-8"))


def _save(note: ControlNote) -> None:
    _control_path().write_text(render_control(note), encoding="utf-8")


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _TEXT_LIMIT else text[: _TEXT_LIMIT - 1] + "…"


def _drop(note: ControlNote, c: Candidate) -> None:
    note.remove_item("우선 큐" if c.source == "P0" else "frontier", c.key)


def _stop(note: ControlNote, iter_: int, reason: str, ts: str) -> None:
    fm = note.frontmatter
    append_entry(
        _log_path(),
        format_header(ts, iter_, "stop", reason=reason),
        [format_kv({
            "processed": fm.get("processed", 0),
            "run_started": fm.get("run_started"),
            "scope": ",".join(fm.get("scope") or []),
            "scope_input": fm.get("scope_input"),
            "runtime": RUNTIME,
        })],
    )
    note.reset_on_stop()
    _save(note)


async def _pick(deps: AutopilotDeps, note: ControlNote, scope: list[str], hubs: list[dict], now: datetime) -> Candidate | None:
    today = now.date()
    queue = ordered_queue(note, read_paper_frontmatters(), scope, hubs, today)
    for c in queue:
        if c.source == "PA":  # 인용 분석이 필요한 백필은 이 판이 하지 않는다
            continue
        if c.arxiv_id is None:
            resolver = getattr(deps, "resolve_title", None)
            resolved = await resolver(c.key) if resolver else None
            if not resolved:
                _drop(note, c)
                note.add_item("건너뜀", f"{c.key} — arXiv 미해석 ({today.isoformat()})")
                continue
            c.arxiv_id = resolved
        if resolve_paper_by_arxiv_id(c.arxiv_id) is not None:
            _drop(note, c)
            continue
        return c
    return None


async def run_iteration(
    deps: AutopilotDeps,
    *,
    scope_arg: str | None,
    max_papers_arg: int | None,
    now: datetime,
) -> IterationOutcome:
    ts = now.strftime("%Y-%m-%d %H:%M")
    try:
        note = _load_control()
    except ControlParseError as e:
        return IterationOutcome("stop", stop_reason="control_parse_error", message=str(e))

    headers = read_tail_headers(_log_path(), n=3)
    hubs = list_hubs()
    hub_slugs = {h["slug"] for h in hubs}
    topic_slugs = {item_key(i) for i in note.items("탐색 주제")}
    d = decide(note, headers, scope_arg=scope_arg, max_papers_arg=max_papers_arg,
               hub_slugs=hub_slugs, topic_slugs=topic_slugs)

    if d.action == "idle":
        return IterationOutcome("idle", message="정지 상태 — scope를 주면 새 실행을 시작한다")
    if d.action == "wait_scope":
        return IterationOutcome("wait_scope", message="scope가 없다 — hub 또는 탐색 주제 slug를 준다")
    if d.action == "stop":
        opened = open_start(headers)
        if opened is not None:
            append_entry(
                _log_path(),
                format_header(ts, opened.iter, "ingest", id=opened.fields.get("id", "-"), slug="-", status="fail"),
                [format_kv({"interrupted": d.reason, "runtime": RUNTIME})],
            )
        _stop(note, d.iter, d.reason or "-", ts)
        return IterationOutcome("stop", iter=d.iter, stop_reason=d.reason)
    if d.needs_interpretation:
        return IterationOutcome(
            "needs_scope",
            message=f"scope '{d.scope_input}'는 hub·탐색 주제 slug가 아니다 — slug로 주거나 스킬 모드에서 해석한다",
        )

    fm = note.frontmatter
    scope = d.scope or list(fm.get("scope") or [])
    fm["stop"] = False
    if d.new_run:
        fm["processed"] = 0
        fm["run_started"] = now.strftime("%Y-%m-%dT%H:%M")
    elif not fm.get("run_started"):
        fm["run_started"] = now.strftime("%Y-%m-%dT%H:%M")
    fm["scope"] = scope
    fm["scope_input"] = d.scope_input
    fm["max_papers"] = d.max_papers
    fm["consecutive_failures"] = d.consecutive_failures

    interrupted = "-"
    if d.action == "resume":
        opened = open_start(headers)
        fields = opened.fields if opened else {}
        target = Candidate(d.resume_id or "", d.resume_id, fields.get("source", "P0"), fields.get("rank", "P0"))
        interrupted = "unknown"
    else:
        target = await _pick(deps, note, scope, hubs, now)
        if target is None:
            _save(note)
            _stop(note, d.iter, "queue_exhausted", ts)
            return IterationOutcome("stop", iter=d.iter, stop_reason="queue_exhausted")
        _save(note)
        append_entry(_log_path(), format_header(
            ts, d.iter, "start", id=target.arxiv_id, source=target.source, rank=target.rank,
            velocity_est=target.velocity if target.velocity is not None else "-", scope=",".join(scope),
        ))

    outcome = await _ingest(deps, note, d.iter, target, scope, hub_slugs, now, interrupted)
    if outcome.status == "ok" and d.max_papers > 0 and int(fm.get("processed") or 0) >= d.max_papers:
        _stop(note, d.iter, "max_papers", now.strftime("%Y-%m-%d %H:%M"))
        outcome.stop_reason = "max_papers"
    elif outcome.status == "fail" and int(fm.get("consecutive_failures") or 0) >= _FAILURE_LIMIT:
        _stop(note, d.iter, "consecutive_failures", now.strftime("%Y-%m-%d %H:%M"))
        outcome.stop_reason = "consecutive_failures"
    return outcome


async def _ingest(
    deps: AutopilotDeps,
    note: ControlNote,
    iter_: int,
    target: Candidate,
    scope: list[str],
    hub_slugs: set[str],
    now: datetime,
    interrupted: str,
) -> IterationOutcome:
    fm = note.frontmatter
    ts = now.strftime("%Y-%m-%d %H:%M")
    aid = target.arxiv_id or target.key
    gate = f"exempt({target.rank})" if target.rank in ("P0", "P5") else "pass"
    try:
        meta = await deps.fetch_meta(aid)
        draft = await deps.summarize(target, meta, scope, hub_slugs)
        rendered = render_paper_note(meta, draft, hub_slugs, now.date())
        checks = verify_numbers(draft_text(draft), await deps.source_text(aid))
        write_rendered_note(rendered)
    except Exception as e:  # 반복 안의 실패는 그 논문만 — 항목은 남기고 다음 반복이 재시도
        error = "vault_isolation" if isinstance(e, VaultIsolationError) else f"{type(e).__name__}: {e}"
        fm["consecutive_failures"] = int(fm.get("consecutive_failures") or 0) + 1
        _save(note)
        append_entry(
            _log_path(),
            format_header(ts, iter_, "ingest", id=aid, slug="-", status="fail"),
            [format_kv({"source": target.source, "rank": target.rank, "gate": gate,
                        "interrupted": interrupted, "runtime": RUNTIME, "error": _clip(error)})],
        )
        return IterationOutcome("ingest", iter=iter_, arxiv_id=aid, status="fail", message=error)

    bad = [c.number for c in unsupported(checks)]
    _drop(note, target)
    fm["processed"] = int(fm.get("processed") or 0) + 1
    fm["consecutive_failures"] = 0
    _save(note)
    append_entry(
        _log_path(),
        format_header(ts, iter_, "ingest", id=aid, slug=rendered.slug, status="ok"),
        [
            format_kv({"source": target.source, "rank": target.rank, "velocity": meta.citation_velocity,
                       "gate": gate, "pages": meta.page_count, "figures": "skipped",
                       "resumed": "false", "interrupted": interrupted, "runtime": RUNTIME}),
            format_kv({"hubs": ",".join(rendered.frontmatter["topics"]), "topic": "-", "new_hub": "-",
                       "hub_candidate": ",".join(rendered.dropped_hubs), "unverified_numbers": len(bad),
                       "warnings": len(draft.warnings), "insight_candidate": _clip(draft.insight_candidate)}),
            format_kv({"title": _clip(meta.title), "tldr": _clip(draft.tldr), "vs_anchor": "-"}),
        ],
    )
    return IterationOutcome("ingest", iter=iter_, arxiv_id=aid, slug=rendered.slug, status="ok",
                            unverified_numbers=bad)
