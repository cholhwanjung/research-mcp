"""autopilot 작업 도구 — 채팅에서 독립 런타임 루프를 시작·정지·보고·설정한다(ADR-063).

루프는 `agent.autopilot`의 러너를 그대로 쓴다. 한 vault에 루프 하나(잠금 파일), 시작한 서버 프로세스의
백그라운드 작업으로 돌고, 끝나면 잠금을 풀고 정지 사유가 있으면 보고서를 저장한다. 반복 사이에 vault 경로가
바뀌면 멈춘다.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from pydantic_ai import RunContext

from agent.autopilot.__main__ import format_outcome, run_loop
from agent.autopilot.control import ControlParseError, parse_control
from agent.autopilot.lock import LockHeld, acquire, holder, release
from agent.autopilot.report import run_report
from agent.autopilot.runlog import read_tail_headers
from agent.autopilot.runner import configure, lock_path, request_stop, stop_run
from wiki.vault import vault_root

_RECENT = 20


class VaultChanged(RuntimeError):
    """백그라운드 루프가 도는 사이 vault 경로가 바뀌었다."""


def _default_deps(model: str):
    from agent.autopilot.deps import StandaloneDeps

    return StandaloneDeps(model)


class AutopilotJobs:
    def __init__(self, *, deps_factory: Callable[[str], Any] | None = None, loop: Callable | None = None,
                 interval: float = 60.0) -> None:
        self.deps_factory = deps_factory or _default_deps
        self.loop = loop or run_loop
        self.interval = interval
        self._tasks: dict[str, asyncio.Task] = {}
        self._lines: dict[str, list[str]] = {}
        self._last = ""

    def running(self) -> bool:
        task = self._tasks.get(str(vault_root()))
        return task is not None and not task.done()

    def recent(self) -> list[str]:
        return list(self._lines.get(self._last, []))

    async def wait(self) -> None:
        task = self._tasks.get(self._last)
        if task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def cancel(self) -> None:
        task = self._tasks.get(self._last)
        if task is not None and not task.done():
            task.cancel()
        await self.wait()

    def _echo(self, key: str) -> Callable[[str], None]:
        def echo(line: str) -> None:
            lines = self._lines.setdefault(key, [])
            lines.append(line)
            del lines[:-_RECENT]

        return echo

    def _sleep(self, vault: Path) -> Callable:
        async def sleep(seconds: float) -> None:
            if vault_root() != vault:
                raise VaultChanged(f"vault 경로가 바뀌어 멈췄다: {vault} → {vault_root()}")
            await asyncio.sleep(seconds)

        return sleep

    async def start(self, model: str, scope: str | None, max_papers: int | None) -> str:
        path = lock_path()
        pid = holder(path)
        if self.running() or pid is not None:
            return f"⛔ autopilot 이미 실행 중{f' (pid {pid})' if pid else ''} — 한 vault에 루프 하나. 멈추려면 autopilot_stop"
        try:
            deps = self.deps_factory(model)
        except Exception as e:  # provider 키 미설정 등 — 잠금을 잡기 전에 실패
            return f"❌ autopilot 실행 준비 실패: {type(e).__name__}: {e}"
        try:
            acquire(path)
        except LockHeld as e:
            return f"⛔ autopilot 이미 실행 중 (pid {e.pid})"
        vault = vault_root()
        self._last = str(vault)
        self._lines[self._last] = []
        self._tasks[self._last] = asyncio.create_task(self._run(deps, vault, path, scope, max_papers))
        return (f"▶️ autopilot 시작 — scope={scope or '(제어 노트 값)'} · max_papers={max_papers or '(제어 노트 값)'} · "
                "진행은 autopilot_status, 멈춤은 autopilot_stop")

    async def _run(self, deps, vault: Path, lock: Path, scope: str | None, max_papers: int | None) -> None:
        echo = self._echo(str(vault))
        try:
            out = await self.loop(deps, scope=scope, max_papers=max_papers, interval=self.interval, once=False,
                                  sleep=self._sleep(vault), echo=echo)
            if getattr(out, "stop_reason", None) and vault_root() == vault:
                text, saved = await run_report(deps, datetime.now(), save=True)
                echo(f"💾 보고서 저장: {saved}" if saved else text.splitlines()[0])
        except Exception as e:  # 백그라운드 작업의 실패는 진행 줄로 남긴다
            echo(f"⚠️ autopilot 중단: {type(e).__name__}: {e}")
        finally:
            release(lock)

    async def stop(self, model: str) -> str:
        pid = holder(lock_path())
        if self.running() or (pid is not None and pid != os.getpid()):
            if request_stop():
                return "⏹ 정지 요청을 기록했다 — 실행 중인 루프가 이번 반복을 마치고 정지·보고한다"
            return "이미 정지를 요청했거나 정지 상태다"
        out = stop_run(datetime.now())
        if out.action != "stop":
            return "정지 상태다 — 멈출 실행이 없다"
        lines = [format_outcome(out)]
        try:
            text, saved = await run_report(self.deps_factory(model), datetime.now(), save=True)
            if saved:
                lines.append(f"💾 보고서 저장: {saved}")
            lines.append(text)
        except Exception as e:  # 보고서 실패가 정지를 되돌리지 않는다
            lines.append(f"⚠️ 실행 보고서를 만들지 못했다: {type(e).__name__}: {e}")
        return "\n".join(lines)

    def status(self) -> str:
        root = vault_root()
        try:
            fm = parse_control((root / "_meta" / "autopilot.md").read_text(encoding="utf-8")).frontmatter
        except (FileNotFoundError, ControlParseError) as e:
            return f"❌ 제어 노트를 읽지 못했다: {e}"
        scope = ",".join(str(s) for s in fm.get("scope") or []) or "-"
        lines = [f"stop={str(fm.get('stop')).lower()} scope={scope} processed={fm.get('processed', 0)} "
                 f"max_papers={fm.get('max_papers', '-')} run_started={fm.get('run_started') or '-'}"]
        headers = read_tail_headers(root / "_meta" / "autopilot-log.md", n=3)
        if headers:
            lines.append("최근 로그:")
            for h in headers:
                fields = " ".join(f"{k}={v}" for k, v in h.fields.items())
                lines.append(f"  [{h.ts}] iter={h.iter} action={h.action} {fields}".rstrip())
        pid = holder(lock_path())
        if self.running():
            job = "이 서버에서 실행 중"
        elif pid is not None:
            job = f"다른 프로세스에서 실행 중 (pid {pid})"
        else:
            job = "실행 중인 루프 없음"
        lines.append(f"job={job}")
        if recent := self.recent():
            lines += ["최근 진행:"] + [f"  {line}" for line in recent[-5:]]
        return "\n".join(lines)

    async def report(self, model: str) -> str:
        text, _ = await run_report(self.deps_factory(model), datetime.now(), save=False)
        return text

    async def config(self, model: str, scope: str, max_papers: int | None = None) -> str:
        out = await configure(self.deps_factory(model), scope_arg=scope, max_papers_arg=max_papers, now=datetime.now())
        return format_outcome(out)


DEFAULT_JOBS = AutopilotJobs()


def _jobs(ctx: RunContext) -> AutopilotJobs:
    return getattr(ctx.deps, "jobs", None) or DEFAULT_JOBS


def _model(ctx: RunContext) -> str:
    from agent.runtime import resolve_model_name

    return getattr(ctx.deps, "model_name", "") or resolve_model_name()


async def autopilot_start(ctx: RunContext, scope: str = "", max_papers: int | None = None) -> str:
    """독립 autopilot 루프를 백그라운드로 시작한다(논문을 자동으로 찾아 vault에 넣는다). 모델 호출 비용이 든다.

    Args:
        scope: hub·탐색 주제 slug(쉼표로 여러 개), "all", 또는 자연어 주제. 비우면 제어 노트 값.
        max_papers: 이번 실행의 최대 편수. 비우면 제어 노트 값.
    """
    return await _jobs(ctx).start(_model(ctx), scope or None, max_papers)


async def autopilot_stop(ctx: RunContext) -> str:
    """autopilot을 멈춘다. 루프가 돌고 있으면 이번 반복을 마치고 정지·보고하고, 아니면 바로 정지 처리하고 보고서를 저장한다."""
    return await _jobs(ctx).stop(_model(ctx))


def autopilot_status(ctx: RunContext) -> str:
    """autopilot 상태 — 제어 노트(정지 여부·scope·진행 편수), 최근 로그, 실행 중인 루프."""
    return _jobs(ctx).status()


async def autopilot_report(ctx: RunContext) -> str:
    """autopilot 실행 보고서(진행 중이면 현재 실행, 아니면 마지막 실행). 저장하지 않는다."""
    return await _jobs(ctx).report(_model(ctx))


async def autopilot_config(ctx: RunContext, scope: str, max_papers: int | None = None) -> str:
    """autopilot 설정만 기록한다(scope·max_papers). 반복은 시작하지 않는다 — "오늘은 X로" 같은 발화.

    Args:
        scope: hub·탐색 주제 slug(쉼표), "all", 또는 자연어 주제.
        max_papers: 최대 편수(선택).
    """
    return await _jobs(ctx).config(_model(ctx), scope, max_papers)


AUTOPILOT_TOOLS = [autopilot_start, autopilot_stop, autopilot_status, autopilot_report, autopilot_config]
