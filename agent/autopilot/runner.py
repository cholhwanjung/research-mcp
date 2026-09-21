"""한 반복(논문 1편)을 코드가 조율한다 — 스킬 모드 워커 절차의 독립 런타임판.

게이트·대기열·스크리닝(scope·중요도)·로그·제어 노트 갱신·노트 쓰기·수치 대조·인용 병합은 코드, 메타·
인용 조회와 판정·요약은 주입된 의존성이 맡는다. 의존성에 판정 메서드(`judge_scope` 등)가 없으면 그 단계는
건너뛴다. 제어 노트는 저장할 때 디스크 최신본에 변경분만 얹어, 반복 도중 사용자가 적은 정지
요청·항목을 덮어쓰지 않는다.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from agent.autopilot.context import ReadContext, hub_lines, related_notes, topic_lines
from agent.autopilot.citations import analyze_citations
from agent.autopilot.control import (
    ControlNote,
    ControlParseError,
    merge_changes,
    parse_control,
    render_control,
    snapshot,
)
from agent.autopilot.citations import short_title
from agent.autopilot.failures import ToolFailure, VaultWriteError, classify_failure
from agent.autopilot.hubs import add_hub_to_paper, create_hub, hub_member_candidates, paper_brief
from agent.autopilot.gate import Decision, decide, resolve_scope
from agent.autopilot.notes import (
    HubProposal,
    NoteDraft,
    PaperMeta,
    RenderedNote,
    VaultIsolationError,
    draft_text,
    note_slug,
    known_note_slugs,
    render_paper_note,
    write_rendered_note,
)
from agent.autopilot.queue import Candidate, excluded_keys, expand_scope, ordered_queue
from agent.autopilot.resolve import resolve_name, vault_arxiv_by_name
from agent.autopilot.scope import apply_interpretation, scope_request_message
from agent.autopilot.seeding import refill, seed_anchor_topic, seed_query_topic, seedable_topics
from agent.autopilot.runlog import (
    Header,
    append_entry,
    format_header,
    format_kv,
    last_iter,
    next_iter,
    open_start,
    read_tail_headers,
)
from agent.autopilot.screening import (
    expired_hold_candidates,
    filter_seeds_by_scope,
    hold_line,
    needs_scope_gate,
    scope_context,
    scope_members,
    seed_topic,
    velocity_gate,
)
from agent.autopilot.topics import Topic, save_topic, topics_by_slug
from agent.autopilot.vaultlinks import (
    fix_links_to,
    link_plain_names,
    plain_surfaces,
    s1_candidates,
    s2_candidates,
    scope_hub_slugs,
    update_cited_by_entry,
)
from agent.autopilot.verifier import unsupported, verify_numbers
from core.slug import slugify_title
from tools.wiki_tools import wiki_link
from wiki.frontmatter import parse_note
from wiki.vault import list_hubs, paper_note_path, read_paper_frontmatters, resolve_paper_by_arxiv_id, vault_root

RUNTIME = "standalone"
_FAILURE_LIMIT = 3
_SKIP_LIMIT = 3  # scope 밖으로 거른 후보가 이만큼이면 반복을 skip으로 닫는다 — 판정 호출 상한
_SCREEN_LIMIT = 20  # 보류를 포함해 한 반복에서 살펴보는 후보 상한
_TEXT_LIMIT = 200
_INTERRUPTED = {"user": "user_stop", "consecutive_failures": "consecutive_failures"}
_TLDR = re.compile(r"^## TL;DR\s*\n+(.+)$", re.MULTILINE)
_SEED_PREFIX = re.compile(r"·\s*(\[[^\]]+\])\s*(?:·|$)")
_MEMBERS_TO_PROMOTE = 3
_MEMBERS_TO_CREATE = 3
_RANK_ORDER = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}
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

    async def source_text(self, arxiv_id: str) -> str: ...

    async def summarize(
        self,
        candidate: Candidate,
        meta: PaperMeta,
        scope: list[str],
        allowed_hubs: set[str],
        context: ReadContext | None = None,
    ) -> NoteDraft: ...


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
    skipped: int = 0
    held: int = 0


def _control_path():
    return vault_root() / "_meta" / "autopilot.md"


def _log_path():
    return vault_root() / "_meta" / "autopilot-log.md"


def lock_path():
    return vault_root() / "_meta" / "autopilot.lock"


def _clip(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= _TEXT_LIMIT else text[: _TEXT_LIMIT - 1] + "…"


def _log(now: datetime, iter_: int, action: str, lines: list[str] | None = None, **fields: object) -> None:
    append_entry(_log_path(), format_header(now.strftime("%Y-%m-%d %H:%M"), iter_, action, **fields), lines)


_monotonic = time.monotonic


class _Store:
    """제어 노트 한 반복분. 저장은 디스크 최신본에 이번 변경만 얹는다."""

    def __init__(self) -> None:
        self.note: ControlNote | None = None
        self._before = None
        self.t0 = _monotonic()

    def load(self) -> ControlNote:
        path = _control_path()
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_CONTROL_TEMPLATE, encoding="utf-8")
        self.note = parse_control(path.read_text(encoding="utf-8"))
        self._before = snapshot(self.note)
        return self.note

    def save(self) -> None:
        path = _control_path()
        try:
            merged = merge_changes(parse_control(path.read_text(encoding="utf-8")), self._before, self.note)
        except (FileNotFoundError, ControlParseError):
            merged = self.note
        path.write_text(render_control(merged), encoding="utf-8")
        if merged is not self.note:  # 참조를 쥔 호출측이 계속 쓰도록 제자리 갱신
            self.note.frontmatter.clear()
            self.note.frontmatter.update(merged.frontmatter)
            self.note.head[:] = merged.head
            self.note.sections[:] = merged.sections
        self._before = snapshot(self.note)


def _when(now: datetime, store: _Store) -> datetime:
    """반복 시작 시각 + 반복 안에서 흐른 시간 — 결과·정지 기록이 실제 끝난 시각을 갖게."""
    return now + timedelta(seconds=max(0.0, _monotonic() - store.t0))


def _usage_fields(deps) -> dict:
    take = getattr(deps, "take_usage", None)
    usage = take() if take else None
    return {"tokens": (usage or {}).get("tokens"), "requests": (usage or {}).get("requests")}


def _citations_capable(deps) -> bool:
    return hasattr(deps, "judge_citations")


def _lacks_citations(fm: dict) -> bool:
    return "references" not in fm and "cited_by" not in fm


def _note_fm(path) -> tuple[dict, str]:
    fm, body = parse_note(path.read_text(encoding="utf-8"))
    return (fm if isinstance(fm, dict) else {}), body


def _awaits_citations(fm: dict, c: Candidate, scope: list[str], hubs: list[dict]) -> bool:
    """노트는 있고 인용 지도가 없으며 이번 실행이 채울 논문인가(우선 큐·백필은 scope 무관)."""
    if not _lacks_citations(fm):
        return False
    if c.source in ("P0", "PA") or scope == ["all"]:
        return True
    topics = {str(t).strip().strip("[]") for t in fm.get("topics") or []}
    return bool(topics & expand_scope(scope, hubs))


def _drop(note: ControlNote, c: Candidate) -> None:
    """처리·건너뜀·보류가 결정된 후보를 출처 절에서 지운다. 같은 논문의 보류 줄도 함께."""
    if c.source == "P0":
        note.remove_item("우선 큐", c.key)
    elif not note.remove_item("frontier", c.key) and c.arxiv_id:
        note.remove_item("frontier", c.arxiv_id)
    if c.arxiv_id:
        note.remove_item("보류", c.arxiv_id)


def _with_expired_holds(queue: list[Candidate], note: ControlNote, now: datetime) -> list[Candidate]:
    holds = expired_hold_candidates(note, now.date())
    if not holds:
        return queue
    seen = {c.arxiv_id or c.key for c in queue}
    head = [c for c in queue if c.source != "F"]
    tail = [c for c in queue if c.source == "F"] + [h for h in holds if h.arxiv_id not in seen]
    tail.sort(key=lambda c: -(c.velocity or 0.0))
    return head + tail


def _with_vault_sources(queue: list[Candidate], extra: list[Candidate]) -> list[Candidate]:
    """깨진 링크(S1)·hub 평문(S2)을 우선 큐 뒤, seed 앞에 등급(P1~P4)·참조 수 순으로 넣는다."""
    head = [c for c in queue if c.source == "P0"]
    tail = [c for c in queue if c.source != "P0"]
    ranked = sorted(extra, key=lambda c: (_RANK_ORDER.get(c.rank, 9), -c.refs))
    out: list[Candidate] = []
    seen: set[str] = set()
    for c in head + ranked + tail:
        ident = c.arxiv_id or c.key
        if ident in seen:
            continue
        seen.add(ident)
        out.append(c)
    return out


async def _pick(deps, note: ControlNote, scope: list[str], hubs: list[dict], now: datetime,
                deferred: set[str]) -> Candidate | None:
    """등급 순 대기열의 첫 후보. 제목만 있는 후보도 그대로 돌려준다 — 해석·중복 판정은 호출측."""
    today = now.date()
    excluded = excluded_keys(note, today)
    extra = [c for c in s1_candidates(scope, hubs) + await s2_candidates(deps, scope, hubs)
             if c.key not in excluded and not (c.arxiv_id and c.arxiv_id in excluded)]
    queue = _with_vault_sources(ordered_queue(note, read_paper_frontmatters(), scope, hubs, today), extra)
    queue = filter_seeds_by_scope(_with_expired_holds(queue, note, now), scope, hubs)
    capable = _citations_capable(deps)
    for c in queue:
        if c.key in deferred or (c.arxiv_id and c.arxiv_id in deferred):
            continue
        if c.source == "PA" and not capable:  # 인용 분석을 못 하면 백필은 할 일이 없다
            continue
        return c
    return None


async def _resolve_title(deps, c: Candidate) -> str | None:
    """이름 → arXiv ID. 검색 일시 장애는 ToolFailure로 올린다."""
    resolver = getattr(deps, "resolve_title", None)
    if resolver is not None:
        return await resolver(c.key)
    return vault_arxiv_by_name(c.key) or await resolve_name(deps, c.key, c.line)


def _fix_links(c: Candidate, slug: str, title: str, aid: str, scope: list[str], hubs: list[dict]) -> int:
    """링크 정정 — 이 논문을 가리키던 깨진 링크와 scope hub 본문의 평문 이름."""
    fixed = fix_links_to(slug, title, aid, extra=[c.key] if c.source == "S1" else [])
    surfaces = {title, short_title(title)} | plain_surfaces(aid) | ({c.key} if c.source == "S2" else set())
    return fixed + link_plain_names(scope_hub_slugs(scope, hubs), slug, surfaces)


def _record_failure(deps, store: _Store, iter_: int, target: Candidate, exc: BaseException, now: datetime, *,
                    gate: str, interrupted: str, held: int = 0) -> IterationOutcome:
    permanent, error = classify_failure(exc)
    note = store.note
    fm = note.frontmatter
    aid = target.arxiv_id or target.key
    fm["consecutive_failures"] = int(fm.get("consecutive_failures") or 0) + 1
    if permanent and not isinstance(exc, VaultWriteError):  # 다시 집어도 똑같이 실패한다 — 건너뜀으로 옮겨 대기열을 막지 않게
        _drop(note, target)
        note.add_item("건너뜀", f"{aid} — {_clip(error)} ({now.date().isoformat()})")
    store.save()
    _log(_when(now, store), iter_, "ingest", [format_kv({
        "source": target.source, "rank": target.rank, "gate": gate, "held": held, "interrupted": interrupted,
        **_usage_fields(deps), "runtime": RUNTIME, "error": _clip(error),
    })], id=aid, slug="-", status="fail")
    outcome = IterationOutcome("ingest", iter=iter_, arxiv_id=aid, status="fail", message=error, held=held)
    if isinstance(exc, VaultWriteError):  # 실행 환경 문제 — 다음 논문도 못 쓴다
        outcome.stop_reason = "write_error"
    return outcome


@dataclass
class _Screened:
    target: Candidate | None = None
    gate: str = "-"
    held: int = 0
    skipped: int = 0
    scope_out: int = 0
    links_fixed: int = 0
    exhausted: bool = False
    outcome: IterationOutcome | None = None
    deferred: set[str] = field(default_factory=set)


def _log_start(now: datetime, iter_: int, c: Candidate, scope: list[str]) -> None:
    _log(now, iter_, "start", id=c.arxiv_id, source=c.source, rank=c.rank,
         velocity_est=c.velocity if c.velocity is not None else "-", scope=",".join(scope))


async def _screen(deps, store: _Store, scope: list[str], hubs: list[dict], topics: dict[str, Topic],
                  iter_: int, now: datetime) -> _Screened:
    note = store.note
    today = now.date()
    min_velocity = float(note.frontmatter.get("min_velocity") or 10)
    judge = getattr(deps, "judge_scope", None)
    info = getattr(deps, "paper_info", None) or deps.fetch_meta
    s = _Screened()
    refilled = False
    for _ in range(_SCREEN_LIMIT):
        c = await _pick(deps, note, scope, hubs, now, s.deferred)
        if c is None and not refilled and _refill_capable(deps, scope):  # 대기열이 비면 인용 이웃으로 한 번 채운다
            refilled = True
            out = await refill(deps, note, scope, hubs, topics, today=today, min_velocity=min_velocity)
            store.save()
            _log(_when(now, store), iter_, "refill", anchors=",".join(out.anchors) or "-", added=out.added, scope=",".join(scope))
            c = await _pick(deps, note, scope, hubs, now, s.deferred) if out.added else None
        if c is None:
            s.exhausted = True
            return s
        if c.arxiv_id is None:  # 이름 → arXiv ID
            try:
                resolved = await _resolve_title(deps, c)
            except ToolFailure:  # 검색 일시 장애 — 이번 반복에서만 미룬다
                s.deferred.add(c.key)
                s.skipped += 1
                if s.skipped >= _SKIP_LIMIT:
                    return s
                continue
            if not resolved:
                _drop(note, c)
                note.add_item("건너뜀", f"{c.key} — arXiv 미해석 ({today.isoformat()})")
                store.save()
                s.skipped += 1
                if s.skipped >= _SKIP_LIMIT:
                    return s
                continue
            c.arxiv_id = resolved
        path = resolve_paper_by_arxiv_id(c.arxiv_id)
        if path is not None:
            fm_note = _note_fm(path)[0]
            if _citations_capable(deps) and _awaits_citations(fm_note, c, scope, hubs):  # 이미 읽었다 — 인용 분석만
                c.mode = "citations"
                s.target, s.gate = c, f"exempt({c.rank if c.rank != '-' else c.source})"
                return s
            s.links_fixed += _fix_links(c, path.parent.name, str(fm_note.get("title") or c.key), c.arxiv_id, scope, hubs)
            _drop(note, c)  # 이미 있는 논문 — 링크만 정정하고 다음 후보
            store.save()
            s.deferred.update({c.key, c.arxiv_id})
            continue
        if c.source == "PA":
            s.deferred.add(c.key)
            continue
        scope_gate = judge is not None and needs_scope_gate(c, scope, topics)
        gate = velocity_gate(c, 0.0, min_velocity, topics, refs=c.refs)
        meta = None
        verdict = None
        if scope_gate or not gate.label.startswith("exempt"):
            try:
                meta = await info(c.arxiv_id)
                if scope_gate:
                    verdict = await judge(meta, scope_context(scope, hubs, topics))
            except Exception as e:  # 판정 불가 — 이 후보로 반복을 열고 실패로 닫는다
                _log_start(_when(now, store), iter_, c, scope)
                s.outcome = _record_failure(deps, store, iter_, c, e, now, gate="-", interrupted="-", held=s.held)
                return s
        if verdict is not None and not verdict.in_scope:
            _drop(note, c)
            note.add_item("건너뜀", f"{c.arxiv_id} — scope 밖 ({','.join(scope)}) ({today.isoformat()})")
            store.save()
            s.skipped += 1
            s.scope_out += 1
            if s.skipped >= _SKIP_LIMIT:
                return s
            continue
        if meta is not None:
            gate = velocity_gate(c, meta.citation_velocity, min_velocity, topics, refs=c.refs)
        if not gate.passed:
            _drop(note, c)
            note.add_item("보류", hold_line(c.arxiv_id, meta.title, meta.citation_velocity, today))
            store.save()
            s.held += 1
            continue
        s.target, s.gate = c, gate.label
        return s
    return s


def _scope_echo(scope: list[str], registered: list[str], not_expanded: list[str], hubs: list[dict],
                topics: dict[str, Topic], scope_input: str) -> str:
    """새로 해석했을 때의 확인 한 줄 — 확정 slug(+자식 hub) · 신규 탐색 주제(parent) · 펼치지 않은 anchor ← 원문."""
    hub_slugs = {h["slug"] for h in hubs}
    covered = expand_scope([s for s in scope if s in hub_slugs], hubs)
    children = [h["slug"] for h in hubs if h["slug"] in covered and h["slug"] not in scope]
    echo = f"scope 확정: {', '.join(scope)}"
    if children:
        echo += f" (+{', '.join(children)})"
    if registered:
        echo += " · 탐색(신규): " + ", ".join(f"{s} (parent {topics[s].parent or '-'})" for s in registered if s in topics)
    if not_expanded:
        echo += f" · 펼치지 않음: {', '.join(not_expanded)}"
    return f'{echo} ← "{scope_input}"'


def _refill_capable(deps, scope: list[str]) -> bool:
    return (hasattr(deps, "citations") and hasattr(deps, "references")
            and (scope == ["all"] or hasattr(deps, "judge_titles")))


async def _seed(deps, store: _Store, scope: list[str], hubs: list[dict], topics: dict[str, Topic], iter_: int,
                now: datetime) -> None:
    """seed가 필요한 탐색 주제 하나를 이번 반복에 seed한다 — 결과는 frontier의 `via seed:<주제>` 항목."""
    note = store.note
    min_velocity = float(note.frontmatter.get("min_velocity") or 10)
    for topic in seedable_topics(note, scope, hubs, topics):
        if topic.kind == "query" and hasattr(deps, "search") and hasattr(deps, "paper_info"):
            out = await seed_query_topic(deps, note, topic, today=now.date(), min_velocity=min_velocity)
        elif topic.kind == "anchor" and hasattr(deps, "citations") and hasattr(deps, "judge_citations"):
            out = await seed_anchor_topic(deps, note, topic, hubs, today=now.date())
        else:
            continue
        store.save()
        _log(_when(now, store), iter_, "refill", **out.log_fields())
        return


def _close_open_start(headers: list[Header], interrupted: str, now: datetime) -> None:
    """결과 없는 start를 닫는다 — 노트가 있으면 partial, 없으면 fail. 항목·processed는 건드리지 않는다."""
    opened = open_start(headers)
    if opened is None:
        return
    aid = opened.fields.get("id", "-")
    path = resolve_paper_by_arxiv_id(aid) if aid and aid != "-" else None
    slug, status = (path.parent.name, "partial") if path is not None else ("-", "fail")
    _log(now, opened.iter, "ingest", [format_kv({
        "source": opened.fields.get("source", "-"), "rank": opened.fields.get("rank", "-"),
        "interrupted": interrupted, "runtime": RUNTIME,
    })], id=aid, slug=slug, status=status)


def _finish_stop(store: _Store, iter_: int, reason: str, now: datetime, *, diagnosis: str | None = None) -> None:
    fm = store.note.frontmatter
    values = {
        "processed": fm.get("processed", 0),
        "run_started": fm.get("run_started"),
        "scope": ",".join(fm.get("scope") or []),
        "scope_input": fm.get("scope_input"),
        "runtime": RUNTIME,
    }
    if diagnosis:
        values["diagnosis"] = _clip(diagnosis)
    _log(_when(now, store), iter_, "stop", [format_kv(values)], reason=reason)
    store.note.reset_on_stop()
    store.save()


def _after(store: _Store, d: Decision, outcome: IterationOutcome, now: datetime) -> IterationOutcome:
    fm = store.note.frontmatter
    if outcome.stop_reason == "write_error":
        _finish_stop(store, d.iter, "write_error", now, diagnosis=outcome.message)
    elif outcome.status in ("ok", "partial") and d.max_papers > 0 and int(fm.get("processed") or 0) >= d.max_papers:
        _finish_stop(store, d.iter, "max_papers", now)
        outcome.stop_reason = "max_papers"
    elif outcome.status == "fail" and int(fm.get("consecutive_failures") or 0) >= _FAILURE_LIMIT:
        _finish_stop(store, d.iter, "consecutive_failures", now, diagnosis=outcome.message)
        outcome.stop_reason = "consecutive_failures"
    return outcome


async def run_iteration(
    deps: AutopilotDeps,
    *,
    scope_arg: str | None,
    max_papers_arg: int | None,
    now: datetime,
) -> IterationOutcome:
    headers = read_tail_headers(_log_path(), n=3)
    store = _Store()
    try:
        note = store.load()
    except ControlParseError as e:  # 덮어쓰지 않고 정지 기록만
        _log(_when(now, store), next_iter(headers), "stop", [format_kv({"error": _clip(str(e)), "runtime": RUNTIME})],
             reason="control_parse_error")
        return IterationOutcome("stop", stop_reason="control_parse_error", message=str(e))

    hubs = list_hubs()
    topics = topics_by_slug(note)
    d = decide(note, headers, scope_arg=scope_arg, max_papers_arg=max_papers_arg,
               hub_slugs={h["slug"] for h in hubs}, topic_slugs=set(topics))

    if d.action == "idle":
        return IterationOutcome("idle", message="정지 상태 — scope를 주면 새 실행을 시작한다")
    if d.action == "wait_scope":  # 정지가 아니라 대기 — 첫 회만 기록
        last = headers[-1] if headers else None
        if last is None or not (last.action == "stop" and last.fields.get("reason") == "scope_missing"):
            _log(_when(now, store), next_iter(headers), "stop", reason="scope_missing")
        return IterationOutcome("wait_scope", message=scope_request_message(hubs))
    if d.action == "stop":
        _close_open_start(headers, _INTERRUPTED.get(d.reason or "", d.reason or "-"), now)
        _finish_stop(store, d.iter, d.reason or "-", now)
        return IterationOutcome("stop", iter=d.iter, stop_reason=d.reason)
    echo = ""
    if d.needs_interpretation:
        interpret = getattr(deps, "interpret_scope", None)
        interpretation = await interpret(d.scope_input, hubs, list(topics.values())) if interpret else None
        not_expanded: list[str] = []
        scope_list, registered = (await apply_interpretation(
            deps, note, interpretation, hubs, topics, max_topics=int(note.frontmatter.get("max_topics") or 3),
            not_expanded=not_expanded) if interpretation is not None else ([], []))
        if not scope_list:
            return IterationOutcome(
                "needs_scope",
                message=f"scope '{d.scope_input}'를 hub·탐색 주제로 옮기지 못했다 — hub slug로 주거나 표현을 바꾼다",
            )
        d.scope, d.needs_interpretation = scope_list, False
        echo = _scope_echo(scope_list, registered, not_expanded, hubs, topics, d.scope_input)

    outcome = await _proceed(deps, store, d, headers, hubs, topics, now)
    if echo:
        outcome.message = f"{echo} · {outcome.message}" if outcome.message else echo
    return outcome


async def _proceed(deps, store: _Store, d: Decision, headers: list[Header], hubs: list[dict], topics: dict[str, Topic],
                   now: datetime) -> IterationOutcome:
    note = store.note
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
    store.save()

    if d.action == "resume":
        opened = open_start(headers)
        fields = opened.fields if opened else {}
        target = Candidate(d.resume_id or "", d.resume_id, fields.get("source", "P0"), fields.get("rank", "P0"))
        gate = f"exempt({target.rank if target.rank != '-' else target.source})"
        path = resolve_paper_by_arxiv_id(target.arxiv_id) if target.arxiv_id else None
        if path is None:  # 노트 전에 끊겼다 — 처음부터
            outcome = await _ingest(deps, store, d.iter, target, scope, hubs, topics, now,
                                    interrupted="unknown", gate=gate, held=0)
        elif _citations_capable(deps) and _lacks_citations(_note_fm(path)[0]):  # 노트 뒤 인용 분석 전에 끊겼다
            target.mode = "citations"
            outcome = await _backfill(deps, store, d.iter, target, hubs, now, interrupted="unknown", gate=gate, held=0,
                                      scope=scope)
        else:  # 쓸 것은 다 썼다 — 결과만 닫는다
            outcome = _close_resumed(deps, store, d.iter, target, path, now)
        return _after(store, d, outcome, now)

    await _seed(deps, store, scope, hubs, topics, d.iter, now)
    screened = await _screen(deps, store, scope, hubs, topics, d.iter, now)
    if screened.outcome is not None:
        return _after(store, d, screened.outcome, now)
    if screened.exhausted:
        _finish_stop(store, d.iter, "queue_exhausted", now)
        return IterationOutcome("stop", iter=d.iter, stop_reason="queue_exhausted",
                                skipped=screened.skipped, held=screened.held)
    if screened.target is None:
        _log(_when(now, store), d.iter, "skip", [format_kv({
            "skipped": screened.skipped, "held": screened.held, "scope_out": screened.scope_out, **_usage_fields(deps),
            "runtime": RUNTIME,
        })], reason="screened_out")
        return IterationOutcome("skip", iter=d.iter, skipped=screened.skipped, held=screened.held)

    _log_start(_when(now, store), d.iter, screened.target, scope)
    if screened.target.mode == "citations":
        outcome = await _backfill(deps, store, d.iter, screened.target, hubs, now, interrupted="-", gate=screened.gate,
                                  held=screened.held, scope=scope, links_fixed=screened.links_fixed)
    else:
        outcome = await _ingest(deps, store, d.iter, screened.target, scope, hubs, topics, now, interrupted="-",
                                gate=screened.gate, held=screened.held, links_fixed=screened.links_fixed,
                                scope_out=screened.scope_out)
    return _after(store, d, outcome, now)


async def _ingest(
    deps: AutopilotDeps,
    store: _Store,
    iter_: int,
    target: Candidate,
    scope: list[str],
    hubs: list[dict],
    topics: dict[str, Topic],
    now: datetime,
    *,
    interrupted: str,
    gate: str,
    held: int,
    links_fixed: int = 0,
    scope_out: int = 0,
) -> IterationOutcome:
    note = store.note
    fm = note.frontmatter
    aid = target.arxiv_id or target.key
    hub_slugs = {h["slug"] for h in hubs}
    try:
        meta = await deps.fetch_meta(aid)
        text = await deps.source_text(aid)  # 본문을 못 읽으면 모델을 부르지 않는다
        context = ReadContext(
            source_text=text,
            hub_lines=hub_lines(hubs),
            topic_lines=topic_lines([t for t in scope_context(scope, hubs, topics).topics
                                     if t.kind == "query" and not t.promoted]),
            related=related_notes(f"{meta.title} {meta.abstract}", exclude={note_slug(meta)}),
            anchor_lines=_anchor_lines(target, topics),
        )
        draft = await deps.summarize(target, meta, scope, hub_slugs, context=context)
        rendered = render_paper_note(meta, draft, hub_slugs, now.date(), vault_notes=known_note_slugs())
        checks = verify_numbers(draft_text(draft), text)
        try:
            write_rendered_note(rendered)
        except FileExistsError:
            raise
        except OSError as e:
            raise VaultWriteError(str(e)) from e
    except Exception as e:  # 반복 안의 실패는 그 논문만
        return _record_failure(deps, store, iter_, target, e, now, gate=gate, interrupted=interrupted, held=held)

    bad = [c.number for c in unsupported(checks)]
    status, refs, cites, citation_error, synthesis = "ok", "-", "-", None, "-"
    if _citations_capable(deps):
        try:
            result = await analyze_citations(deps, meta, paper_note_path(rendered.slug), hubs, now=now)
            refs, cites, synthesis = result.refs, result.cites, result.synthesis
        except Exception as e:  # 노트는 남기고 인용 분석만 다음 반복으로
            status, citation_error = "partial", classify_failure(e)[1]
    try:
        attached = await _attach(deps, store, target, draft, rendered, scope, hubs, topics, now)
    except Exception as e:  # 소속 정리 실패는 노트를 무르지 않는다 — 로그만
        attached = {"topic": "-", "new_hub": "-", "hub_candidate": ",".join(rendered.dropped_hubs) or "-",
                    "vs_anchor": "-", "attach_error": _clip(classify_failure(e)[1])}
    try:
        links_fixed += _fix_links(target, rendered.slug, meta.title, aid, scope, hubs)
    except Exception as e:  # 링크 정정은 노트를 무르지 않는다
        attached["link_error"] = _clip(classify_failure(e)[1])
    usage = _usage_fields(deps)
    _drop(note, target)
    if status == "partial":
        note.add_item("우선 큐", f"{aid} — citation_pending")
    fm["processed"] = int(fm.get("processed") or 0) + 1
    fm["consecutive_failures"] = 0
    store.save()
    kv1 = {"source": target.source, "rank": target.rank,
           "hub_of_origin": target.via if target.source == "S2" and target.via else "-", "velocity": meta.citation_velocity,
           "gate": gate, "pages": meta.page_count, "figures": "skipped", "refs": refs, "cites": cites,
           "references_synthesis": synthesis,
           "resumed": "false", "interrupted": interrupted, "runtime": RUNTIME, **usage}
    if citation_error:
        kv1["citation_error"] = _clip(citation_error)
    for key in ("attach_error", "link_error"):
        if attached.get(key):
            kv1[key] = attached[key]
    _log(_when(now, store), iter_, "ingest", [
        format_kv(kv1),
        format_kv({"hubs": ",".join(_paper_topics(rendered.slug)), "topic": attached["topic"],
                   "new_hub": attached["new_hub"], "hub_candidate": attached["hub_candidate"], "links_fixed": links_fixed,
                   "held": held, "scope_out": scope_out, "unverified_numbers": len(bad), "warnings": len(draft.warnings),
                   **({"warning_notes": _clip(" / ".join(w.strip() for w in draft.warnings if w.strip()))}
                      if any(w.strip() for w in draft.warnings) else {}),
                   "insight_candidate": _clip(draft.insight_candidate)}),
        format_kv({"title": _clip(meta.title), "tldr": _clip(draft.tldr), "vs_anchor": attached["vs_anchor"]}),
    ], id=aid, slug=rendered.slug, status=status)
    return IterationOutcome("ingest", iter=iter_, arxiv_id=aid, slug=rendered.slug, status=status,
                            unverified_numbers=bad, held=held)


def _paper_topics(slug: str) -> list[str]:
    path = paper_note_path(slug)
    return [str(x) for x in (_note_fm(path)[0].get("topics") or [])] if path.is_file() else []


def _anchor_lines(target: Candidate, topics: dict[str, Topic]) -> list[str]:
    """anchor seed 논문이면 anchor 이름·seed 판정·탐색 주제를 요약 에이전트에 준다."""
    seed = seed_topic(target)
    topic = topics.get(seed) if seed else None
    if topic is None or topic.kind != "anchor":
        return []
    path = resolve_paper_by_arxiv_id(topic.anchor)
    fm = _note_fm(path)[0] if path is not None else {}
    m = _SEED_PREFIX.search(target.line)
    lines = [
        f"anchor: {fm.get('title') or topic.anchor} (arXiv:{topic.anchor}) · seed 판정 {m.group(1) if m else '[평가?]'}",
        f"탐색 주제: {topic.slug} — {topic.definition} · 찾는 관계 {topic.relation or '-'}",
    ]
    entry = next((e for e in fm.get("cited_by") or [] if isinstance(e, dict) and str(e.get("paper_id")) == str(target.arxiv_id)), None)
    if entry and entry.get("cited_for"):
        lines.append(f"seed 문맥: {entry['cited_for']}")
    return lines


def _add_member(note: ControlNote, topic: Topic, slug: str) -> None:
    if slug not in topic.members:
        topic.members.append(slug)
    save_topic(note, topic)


async def _attach(deps, store: _Store, target: Candidate, draft: NoteDraft, rendered: RenderedNote, scope: list[str],
                  hubs: list[dict], topics: dict[str, Topic], now: datetime) -> dict:
    """ingest 뒤 소속 정리 — anchor 관계 확정, 탐색 주제 소속·승격, 신규 hub·explore 등록."""
    note = store.note
    slug, aid, today = rendered.slug, str(rendered.frontmatter["arxiv_id"]), now.date()
    members_scope = scope_members(scope, hubs)
    out = {"topic": "-", "new_hub": "-", "vs_anchor": "-"}
    candidates = list(rendered.dropped_hubs)

    seed = seed_topic(target)
    anchor_topic = topics.get(seed) if seed else None
    if anchor_topic is not None and anchor_topic.kind == "anchor":
        m = _SEED_PREFIX.search(target.line)
        prefix, vs = (m.group(1) if m else "[평가?]"), ""
        if draft.anchor_relation is not None:
            prefix, vs = draft.anchor_relation.prefix, _clip(draft.anchor_relation.vs_anchor) if draft.anchor_relation.vs_anchor.strip() else ""
        cited_for = f"{prefix} {vs}".strip()
        anchor_slug = update_cited_by_entry(anchor_topic.anchor, aid, hubs=_paper_topics(slug),
                                            abstract_summary=_clip(draft.tldr), cited_for=cited_for)
        if anchor_slug:
            wiki_link(slug, anchor_slug, note=cited_for)
        out["vs_anchor"] = cited_for
        if prefix != "[언급]":  # 관계가 확정된 논문만 도전자 명단에
            _add_member(note, anchor_topic, slug)
            out["topic"] = anchor_topic.slug
    elif draft.topic and draft.topic in topics:
        topic = topics[draft.topic]
        if topic.kind == "query" and not topic.promoted and (members_scope is None or topic.slug in members_scope):
            _add_member(note, topic, slug)
            out["topic"] = topic.slug
            if len(topic.members) >= _MEMBERS_TO_PROMOTE and hasattr(deps, "curate_hub"):
                if await _promote(deps, note, topic, hubs, today):
                    out["new_hub"] = topic.slug

    if draft.hub_candidate is not None:
        created, candidate = await _propose_hub(deps, note, draft.hub_candidate, slug, scope, hubs, topics, today)
        if created:
            out["new_hub"] = created
        elif candidate:
            candidates.append(candidate)
    out["hub_candidate"] = ",".join(dict.fromkeys(candidates)) or "-"
    return out


async def _promote(deps, note: ControlNote, topic: Topic, hubs: list[dict], today) -> bool:
    """members가 찬 query 주제를 hub로 — slug는 그대로라 scope 집합이 변하지 않는다."""
    briefs = [b for b in (paper_brief(m) for m in topic.members) if b]
    proposal = HubProposal(slug=topic.slug, title=topic.slug, summary=topic.definition, parent=topic.parent or "")
    curation = await deps.curate_hub(proposal, briefs, scope_input=str(note.frontmatter.get("scope_input") or ""),
                                     mode="promote")
    parent = topic.parent if topic.parent and any(h["slug"] == topic.parent for h in hubs) else None
    try:
        created = create_hub(topic.slug, curation, parent=parent, members=list(topic.members), today=today) is not None
    except VaultIsolationError:
        return False
    topic.promoted = today.isoformat()
    save_topic(note, topic)
    return created


async def _propose_hub(deps, note: ControlNote, proposal: HubProposal, slug: str, scope: list[str], hubs: list[dict],
                       topics: dict[str, Topic], today) -> tuple[str | None, str | None]:
    """(만든 hub slug, 만들지 못한 후보 slug). 조건: 자기 주제로 묶일 논문 ≥3편, scope 실행이면 parent가 scope 안."""
    fm = note.frontmatter
    hub_slugs = {h["slug"] for h in hubs}
    candidate = slugify_title(proposal.slug)
    if not candidate or candidate == "untitled" or candidate in hub_slugs or candidate in topics:
        return None, None
    if not hasattr(deps, "curate_hub"):
        return None, candidate
    members_scope = scope_members(scope, hubs)
    parent = proposal.parent if proposal.parent in hub_slugs else None
    parent_ok = members_scope is None or (parent is not None and parent in members_scope)
    pool = hub_member_candidates(" ".join([proposal.title, proposal.summary, *proposal.aliases]), exclude={slug})
    curation = await deps.curate_hub(proposal, pool, scope_input=str(fm.get("scope_input") or ""), mode="create")
    allowed = {c["slug"] for c in pool}
    members = [slug] + [m for m in dict.fromkeys(curation.members) if m in allowed and m != slug]
    if parent_ok and len(members) >= _MEMBERS_TO_CREATE:
        try:
            path = create_hub(candidate, curation, parent=parent, members=members, today=today)
        except VaultIsolationError:
            path = None
        if path is not None:
            add_hub_to_paper(slug, candidate)
            return candidate, None
    added = int(fm.get("topics_added") or 0)
    if (fm.get("explore") is True and curation.within_intent and curation.query.strip()
            and added < int(fm.get("max_topics") or 3)):
        save_topic(note, Topic(slug=candidate, definition=" ".join((curation.summary or proposal.summary).split()),
                               query=" ".join(curation.query.split()), parent=parent, members=[slug]))
        fm["topics_added"] = added + 1
    return None, candidate


def _meta_from_note(aid: str, fm: dict) -> PaperMeta:
    return PaperMeta(
        arxiv_id=aid, ss_paper_id=str(fm.get("ss_paper_id") or ""), title=str(fm.get("title") or aid),
        authors=list(fm.get("authors") or []), year=fm.get("year"), venue=str(fm.get("venue") or ""),
        citation_count=int(fm.get("citation_count") or 0),
        influential_citation_count=int(fm.get("influential_citation_count") or 0),
        citation_velocity=float(fm.get("citation_velocity") or 0.0), page_count=fm.get("page_count"),
    )


def _note_tldr(body: str) -> str:
    m = _TLDR.search(body)
    return m.group(1) if m else ""


def _log_existing(deps, now: datetime, iter_: int, target: Candidate, path, fm: dict, body: str, *,
                  gate: str, interrupted: str, held: int, refs, cites, links_fixed: int = 0) -> None:
    _log(now, iter_, "ingest", [
        format_kv({"source": target.source, "rank": target.rank, "hub_of_origin": "-",
                   "velocity": fm.get("citation_velocity"), "gate": gate, "pages": "-", "figures": "-",
                   "refs": refs, "cites": cites, "resumed": "true", "interrupted": interrupted,
                   "runtime": RUNTIME, **_usage_fields(deps)}),
        format_kv({"hubs": ",".join(str(t) for t in fm.get("topics") or []), "topic": "-", "new_hub": "-",
                   "hub_candidate": "-", "links_fixed": links_fixed, "held": held, "insight_candidate": "-"}),
        format_kv({"title": _clip(fm.get("title") or target.key), "tldr": _clip(_note_tldr(body)), "vs_anchor": "-"}),
    ], id=target.arxiv_id, slug=path.parent.name, status="ok")


async def _backfill(deps, store: _Store, iter_: int, target: Candidate, hubs: list[dict], now: datetime, *,
                    interrupted: str, gate: str, held: int, scope: list[str] | None = None,
                    links_fixed: int = 0) -> IterationOutcome:
    """이미 읽은 논문에 인용 분석만 한다(백필·citation_pending·노트 뒤에 끊긴 반복)."""
    note = store.note
    path = resolve_paper_by_arxiv_id(target.arxiv_id)
    try:
        fm_note, _ = _note_fm(path)
        result = await analyze_citations(deps, _meta_from_note(target.arxiv_id, fm_note), path, hubs, now=now)
    except Exception as e:
        return _record_failure(deps, store, iter_, target, e, now, gate=gate, interrupted=interrupted, held=held)
    fm_note, body = _note_fm(path)
    try:
        links_fixed += _fix_links(target, path.parent.name, str(fm_note.get("title") or target.key), target.arxiv_id,
                                  scope or [], hubs)
    except Exception:
        pass
    _drop(note, target)
    note.frontmatter["processed"] = int(note.frontmatter.get("processed") or 0) + 1
    note.frontmatter["consecutive_failures"] = 0
    store.save()
    _log_existing(deps, _when(now, store), iter_, target, path, fm_note, body, gate=gate, interrupted=interrupted, held=held,
                  refs=result.refs, cites=result.cites, links_fixed=links_fixed)
    return IterationOutcome("ingest", iter=iter_, arxiv_id=target.arxiv_id, slug=path.parent.name, status="ok", held=held)


def _close_resumed(deps, store: _Store, iter_: int, target: Candidate, path, now: datetime) -> IterationOutcome:
    """끊긴 반복이 노트·인용 지도까지 썼다 — 결과 로그로만 닫는다."""
    fm_note, body = _note_fm(path)
    _drop(store.note, target)
    store.note.frontmatter["processed"] = int(store.note.frontmatter.get("processed") or 0) + 1
    store.note.frontmatter["consecutive_failures"] = 0
    store.save()
    _log_existing(deps, _when(now, store), iter_, target, path, fm_note, body, gate=f"exempt({target.rank})", interrupted="unknown",
                  held=0, refs=len(fm_note.get("references") or []), cites=len(fm_note.get("cited_by") or []))
    return IterationOutcome("ingest", iter=iter_, arxiv_id=target.arxiv_id, slug=path.parent.name, status="ok")


def stop_run(now: datetime, *, reason: str = "user", interrupted: str = "user_stop") -> IterationOutcome:
    """정지 처리 ⓪①② — 열린 start 닫기, stop 로그, 제어 노트 리셋. 이미 정지 상태면 아무것도 쓰지 않는다."""
    headers = read_tail_headers(_log_path(), n=3)
    store = _Store()
    fm = store.load().frontmatter
    opened = open_start(headers)
    if fm.get("stop") is True and not fm.get("scope") and opened is None:
        return IterationOutcome("idle", message="이미 정지 상태")
    iter_ = opened.iter if opened else last_iter(headers)
    _close_open_start(headers, interrupted, now)
    _finish_stop(store, iter_, reason, now)
    return IterationOutcome("stop", iter=iter_, stop_reason=reason)


def request_stop() -> bool:
    """실행 중인 루프에 정지를 요청한다 — stop: true만 쓴다. 루프가 다음 반복에서 사용자 정지로 처리한다."""
    store = _Store()
    fm = store.load().frontmatter
    if fm.get("stop") is True:
        return False
    fm["stop"] = True
    store.save()
    return True


async def configure(deps, *, scope_arg: str | None, max_papers_arg: int | None, now: datetime) -> IterationOutcome:
    """설정만 한다 — scope(자연어면 해석·등록)와 max_papers를 제어 노트에 쓰고 반복은 시작하지 않는다."""
    store = _Store()
    note = store.load()
    hubs = list_hubs()
    topics = topics_by_slug(note)
    text = (scope_arg or "").strip()
    if not text:
        return IterationOutcome("wait_scope", message=scope_request_message(hubs))
    scope = resolve_scope(text, {h["slug"] for h in hubs}, set(topics))
    registered: list[str] = []
    if scope is None:
        interpret = getattr(deps, "interpret_scope", None)
        interpretation = await interpret(text, hubs, list(topics.values())) if interpret else None
        not_expanded: list[str] = []
        scope, registered = (await apply_interpretation(
            deps, note, interpretation, hubs, topics, max_topics=int(note.frontmatter.get("max_topics") or 3),
            not_expanded=not_expanded) if interpretation is not None else ([], []))
        if not scope:
            return IterationOutcome("needs_scope", message=f"scope '{text}'를 hub·탐색 주제로 옮기지 못했다")
    fm = note.frontmatter
    fm.update(stop=False, scope=scope, scope_input=text)
    if max_papers_arg is not None:
        fm["max_papers"] = max_papers_arg
    store.save()
    message = f"scope 기록: {', '.join(scope)} — 다음 run부터 적용"
    if registered or scope != [text]:
        message += " · " + _scope_echo(scope, registered, [], hubs, topics, text)
    return IterationOutcome("config", message=message)
