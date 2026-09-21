"""`python -m agent.autopilot` — Claude Code 없이 autopilot 루프를 돈다.

    uv run python -m agent.autopilot --scope autonomous-research-agents --max-papers 5 --model openai:gpt-5
    uv run python -m agent.autopilot stop       # 사용자 정지 + 실행 보고서 저장
    uv run python -m agent.autopilot report     # 실행 보고서 출력(저장 없음)
    uv run python -m agent.autopilot config --scope "…"   # scope만 기록

한 vault에 루프 하나(잠금 파일). scope 인자는 첫 반복에만 쓰고 이후는 제어 노트를 따른다 — 실행 중
제어 노트에 `stop: true`를 쓰거나 `stop` 명령을 주면 다음 반복이 사용자 정지로 끝낸다. Ctrl+C도 사용자 정지.
정지(max_papers·queue_exhausted·연속 실패·사용자)나 대기(scope 없음·해석 필요) 결과가 나오면 끝난다.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from datetime import datetime
from typing import Awaitable, Callable

from agent.autopilot.lock import LockHeld, acquire, holder, release
from agent.autopilot.report import run_report
from agent.autopilot.runner import (
    AutopilotDeps,
    IterationOutcome,
    configure,
    lock_path,
    request_stop,
    run_iteration,
    stop_run,
)

_TERMINAL = {"stop", "idle", "wait_scope", "needs_scope"}
_COMMANDS = ("run", "stop", "config", "report")


def format_outcome(out: IterationOutcome) -> str:
    parts = [f"🤖 autopilot iter {out.iter} — {out.action}"]
    if out.arxiv_id:
        parts.append(f"arXiv:{out.arxiv_id}" + (f" → {out.slug}" if out.slug else ""))
    if out.status:
        parts.append(out.status)
    if out.skipped or out.held:
        parts.append(f"건너뜀 {out.skipped} · 보류 {out.held}")
    if out.unverified_numbers:
        parts.append("원문에 없는 수치: " + ", ".join(out.unverified_numbers))
    if out.stop_reason:
        parts.append(f"⏹ 정지: {out.stop_reason}")
    if out.message:
        parts.append(out.message)
    return " · ".join(parts)


async def run_loop(
    deps: AutopilotDeps,
    *,
    scope: str | None,
    max_papers: int | None,
    interval: float,
    once: bool,
    clock: Callable[[], datetime] = datetime.now,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    echo: Callable[[str], None] = print,
) -> IterationOutcome:
    scope_arg = scope  # 첫 반복에만 — 이후 반복은 제어 노트의 scope·stop을 따른다
    while True:
        out = await run_iteration(deps, scope_arg=scope_arg, max_papers_arg=max_papers, now=clock())
        scope_arg = None
        echo(format_outcome(out))
        if once or out.action in _TERMINAL or out.stop_reason:
            return out
        await sleep(interval)


def _default_deps(model: str) -> AutopilotDeps:
    from agent.autopilot.deps import StandaloneDeps

    return StandaloneDeps(model)


def _print_report(deps, *, save: bool) -> None:
    try:
        text, path = asyncio.run(run_report(deps, datetime.now(), save=save))
    except Exception as e:  # 보고서 실패가 정지·종료 코드를 바꾸지 않는다
        print(f"⚠️ 실행 보고서를 만들지 못했다: {type(e).__name__}: {e}")
        return
    print(text)
    if path is not None:
        print(f"💾 보고서 저장: {path}")


def _make_deps(deps_factory, model: str | None):
    try:
        from agent.runtime import resolve_model_name

        return (deps_factory or _default_deps)(resolve_model_name(model))
    except Exception:
        return None


def _stop_command(deps_factory, model: str | None) -> int:
    pid = holder(lock_path())
    if pid is not None and pid != os.getpid():  # 루프가 이번 반복을 마치고 정지·보고한다
        if request_stop():
            print(f"⏹ 정지 요청을 기록했다 — 실행 중인 루프(pid {pid})가 이번 반복을 마치고 정지한다")
        else:
            print("정지 상태이거나 이미 정지를 요청했다")
        return 0
    out = stop_run(datetime.now())
    print(format_outcome(out))
    if out.action == "stop":
        _print_report(_make_deps(deps_factory, model), save=True)
    return 0


def main(argv: list[str] | None = None, deps_factory: Callable[[str], AutopilotDeps] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent.autopilot", description="독립 autopilot 런타임")
    parser.add_argument("command", nargs="?", default="run", choices=_COMMANDS, help="run(기본) · stop(사용자 정지) · config(scope만 기록) · report(보고서 출력)")
    parser.add_argument("--scope", default=None, help="hub·탐색 주제 slug(쉼표로 여러 개) 또는 all")
    parser.add_argument("--max-papers", type=int, default=None, help="이번 실행의 최대 편수 (0=무제한)")
    parser.add_argument("--interval", type=float, default=60.0, help="반복 사이 대기 초 (기본 60)")
    parser.add_argument("--once", action="store_true", help="한 반복만 돌고 끝낸다")
    parser.add_argument("--model", default=None, help="provider:model (기본 RESEARCH_MODEL)")
    args = parser.parse_args(argv)

    if args.command == "stop":
        return _stop_command(deps_factory, args.model)
    if args.command == "report":
        _print_report(_make_deps(deps_factory, args.model), save=False)
        return 0

    from agent.runtime import resolve_model_name

    deps = (deps_factory or _default_deps)(resolve_model_name(args.model))
    if args.command == "config":
        out = asyncio.run(configure(deps, scope_arg=args.scope, max_papers_arg=args.max_papers, now=datetime.now()))
        print(format_outcome(out))
        return 0 if out.action == "config" else 2
    path = lock_path()
    try:
        acquire(path)
    except LockHeld as e:
        print(f"⛔ autopilot 이미 실행 중 (pid {e.pid}) — 한 vault에 루프 하나. 정지는 `python -m agent.autopilot stop`")
        return 1
    try:
        out = asyncio.run(
            run_loop(deps, scope=args.scope, max_papers=args.max_papers, interval=args.interval, once=args.once)
        )
    except KeyboardInterrupt:
        stopped = stop_run(datetime.now())
        print(format_outcome(stopped))
        if stopped.action == "stop":
            _print_report(deps, save=True)
        return 130
    finally:
        release(path)
    if out.stop_reason:  # 반복 결과로 정지했다(max_papers 등) — 보고서
        _print_report(deps, save=True)
    if out.action == "needs_scope":
        return 2
    return 1 if out.status == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
