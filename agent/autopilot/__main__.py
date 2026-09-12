"""`python -m agent.autopilot` — Claude Code 없이 autopilot 루프를 돈다.

    uv run python -m agent.autopilot --scope autonomous-research-agents --max-papers 5 --model openai:gpt-5

정지(max_papers·queue_exhausted·연속 실패)나 대기(scope 없음·해석 필요) 결과가 나오면 끝난다.
자연어 scope는 추측하지 않는다 — hub·탐색 주제 slug로 준다.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from typing import Awaitable, Callable

from agent.autopilot.runner import AutopilotDeps, IterationOutcome, run_iteration

_TERMINAL = {"stop", "idle", "wait_scope", "needs_scope"}


def format_outcome(out: IterationOutcome) -> str:
    parts = [f"🤖 autopilot iter {out.iter} — {out.action}"]
    if out.arxiv_id:
        parts.append(f"arXiv:{out.arxiv_id}" + (f" → {out.slug}" if out.slug else ""))
    if out.status:
        parts.append(out.status)
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
    while True:
        out = await run_iteration(deps, scope_arg=scope, max_papers_arg=max_papers, now=clock())
        echo(format_outcome(out))
        if once or out.action in _TERMINAL or out.stop_reason:
            return out
        await sleep(interval)


def _default_deps(model: str) -> AutopilotDeps:
    from agent.autopilot.deps import StandaloneDeps

    return StandaloneDeps(model)


def main(argv: list[str] | None = None, deps_factory: Callable[[str], AutopilotDeps] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent.autopilot", description="독립 autopilot 런타임")
    parser.add_argument("--scope", default=None, help="hub·탐색 주제 slug(쉼표로 여러 개) 또는 all")
    parser.add_argument("--max-papers", type=int, default=None, help="이번 실행의 최대 편수 (0=무제한)")
    parser.add_argument("--interval", type=float, default=60.0, help="반복 사이 대기 초 (기본 60)")
    parser.add_argument("--once", action="store_true", help="한 반복만 돌고 끝낸다")
    parser.add_argument("--model", default=None, help="provider:model (기본 RESEARCH_MODEL)")
    args = parser.parse_args(argv)

    from agent.runtime import resolve_model_name

    deps = (deps_factory or _default_deps)(resolve_model_name(args.model))
    out = asyncio.run(
        run_loop(deps, scope=args.scope, max_papers=args.max_papers, interval=args.interval, once=args.once)
    )
    if out.action == "needs_scope":
        return 2
    return 1 if out.status == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
