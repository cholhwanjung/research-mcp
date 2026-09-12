"""반복을 시작할지 결정하는 순수 함수 — 스킬 모드 디스패처 D0의 코드판.

입력은 제어 노트·로그 헤더·실행 인자뿐이고 부작용이 없다. 결정 결과를 제어 노트에
반영하는 것은 호출측(runner) 몫이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agent.autopilot.control import ControlNote
from agent.autopilot.runlog import Header, next_iter, open_start

Action = Literal["run", "resume", "stop", "idle", "wait_scope"]
_FAILURE_LIMIT = 3
_ALL = {"all", "전체"}


@dataclass
class Decision:
    action: Action
    reason: str | None = None
    iter: int = 0
    resume_id: str | None = None
    scope: list[str] | None = None
    scope_input: str = ""
    needs_interpretation: bool = False
    new_run: bool = False
    consecutive_failures: int = 0
    max_papers: int = 0


def resolve_scope(scope_input: str, hub_slugs: set[str], topic_slugs: set[str]) -> list[str] | None:
    """쉼표로 나눈 토큰이 전부 알려진 slug면 그 목록, `all`이면 ["all"], 아니면 None(해석 필요)."""
    tokens = [t.strip() for t in scope_input.split(",") if t.strip()]
    if not tokens:
        return None
    if len(tokens) == 1 and tokens[0].lower() in _ALL:
        return ["all"]
    known = hub_slugs | topic_slugs
    return tokens if all(t in known for t in tokens) else None


def decide(
    note: ControlNote,
    headers: list[Header],
    *,
    scope_arg: str | None,
    max_papers_arg: int | None,
    hub_slugs: set[str],
    topic_slugs: set[str],
) -> Decision:
    fm = note.frontmatter
    failures = int(fm.get("consecutive_failures") or 0)
    max_papers = int(max_papers_arg if max_papers_arg is not None else fm.get("max_papers") or 0)
    processed = int(fm.get("processed") or 0)
    saved_scope = list(fm.get("scope") or [])
    saved_input = str(fm.get("scope_input") or "")
    scope_arg = (scope_arg or "").strip() or None

    opened = open_start(headers)
    if opened is not None:
        failures += 1
        if failures >= _FAILURE_LIMIT:
            return Decision("stop", reason="consecutive_failures", iter=opened.iter,
                            consecutive_failures=failures, max_papers=max_papers)
        return Decision("resume", iter=opened.iter, resume_id=opened.fields.get("id"),
                        scope=saved_scope or None, scope_input=saved_input,
                        consecutive_failures=failures, max_papers=max_papers)

    new_run = fm.get("stop") is True
    if new_run and scope_arg is None:
        return Decision("idle", reason="stopped", max_papers=max_papers)
    if new_run:
        processed = 0

    if scope_arg is None:
        if not saved_scope:
            return Decision("wait_scope", max_papers=max_papers)
        scope, scope_input = saved_scope, saved_input
    elif scope_arg == saved_input and saved_scope and not new_run:
        scope, scope_input = saved_scope, saved_input
    else:
        scope, scope_input = resolve_scope(scope_arg, hub_slugs, topic_slugs), scope_arg

    if max_papers > 0 and processed >= max_papers:
        return Decision("stop", reason="max_papers", iter=next_iter(headers),
                        consecutive_failures=failures, max_papers=max_papers)

    return Decision("run", iter=next_iter(headers), scope=scope, scope_input=scope_input,
                    needs_interpretation=scope is None, new_run=new_run,
                    consecutive_failures=failures, max_papers=max_papers)
