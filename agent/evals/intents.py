"""의도 이해 평가 — 실제 발화 사례를 에이전트에 넣고 도구 궤적·승인 요청·확인 질문·최종 응답을 채점한다.

사례의 기대값은 Claude Code가 같은 요청을 처리하는 방식에서 뽑았다. 채점은 결정론 규칙뿐이고, 사례마다
원본을 건드리지 않는 vault 복사본(PDF 캐시 제외)에서 돈다. 승인 요청은 승인하지 않는다 — 쓰기 전에 묻는지를 본다.
실행기는 주입한다(독립 하네스 이벤트 스트림·헤드리스 Claude Code). 교차 비교(ADR-065)는 두 시스템 모두
거부 뒤 계속하게 하고(`deny_approvals`) 능력 단위로 채점한다(`capabilities.py`).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable

from pydantic import BaseModel, Field

from core import config

DEFAULT_CASES = Path(__file__).with_name("intent_cases.json")
HOLDOUT_CASES = Path(__file__).with_name("intent_cases_holdout.json")
DENIED = "사용자가 이 도구 실행을 승인하지 않았다."
_QUESTION = re.compile(r"\?|까요")

EventStream = Callable[[str], AsyncIterator[dict]]
Runner = Callable[[str, Path], Awaitable["Trajectory"]]


class Expect(BaseModel):
    tools_all: list[str] = Field(default_factory=list, description="모두 호출해야 하는 도구")
    tools_any: list[list[str]] = Field(default_factory=list, description="묶음마다 하나 이상 호출")
    tools_none: list[str] = Field(default_factory=list, description="호출하면 안 되는 도구")
    approval_for: list[list[str]] = Field(default_factory=list, description="묶음마다 하나 이상 승인 요청")
    asks_user: bool | None = Field(default=None, description="확인 질문으로 턴을 끝내야 하는가")
    final_matches: list[str] = Field(default_factory=list, description="최종 응답이 맞아야 하는 정규식")
    final_excludes: list[str] = Field(default_factory=list, description="최종 응답에 없어야 하는 문자열")
    unchanged: list[str] = Field(default_factory=list, description="끝났을 때 그대로여야 하는 vault 상대경로")
    outside_unchanged: list[str] = Field(default_factory=list,
                                         description="끝났을 때 그대로여야 하는 vault 밖(사례 폴더) 상대경로")


class IntentCase(BaseModel):
    id: str
    utterance: str
    files: dict[str, str] = Field(default_factory=dict, description="vault 복사본에 미리 쓸 파일")
    outside_files: dict[str, str] = Field(default_factory=dict, description="vault 복사본 옆(vault 밖)에 쓸 파일")
    expect: Expect


@dataclass
class Trajectory:
    calls: list[str] = field(default_factory=list)
    approvals: list[str] = field(default_factory=list)
    final: str = ""
    tokens: int = 0
    requests: int = 0
    error: str = ""
    raw_calls: list[tuple[str, dict]] = field(default_factory=list)
    raw_approvals: list[tuple[str, dict]] = field(default_factory=list)
    input_tokens: int = 0  # 캐시 읽기·쓰기를 포함한 전체 입력
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    duration_s: float = 0.0


@dataclass
class CaseResult:
    id: str
    checks: dict[str, bool]
    trajectory: Trajectory

    @property
    def passed(self) -> bool:
        return all(self.checks.values())

    @property
    def failed(self) -> list[str]:
        return [name for name, ok in self.checks.items() if not ok]


def load_cases(path: Path = DEFAULT_CASES) -> list[IntentCase]:
    cases = [IntentCase.model_validate(c) for c in json.loads(Path(path).read_text(encoding="utf-8"))]
    ids = [c.id for c in cases]
    if len(set(ids)) != len(ids):
        raise ValueError(f"사례 id가 중복된다: {path}")
    return cases


def grade(case: IntentCase, traj: Trajectory, *, before: dict, after: dict,
          outside_before: dict | None = None, outside_after: dict | None = None) -> CaseResult:
    e = case.expect
    checks: dict[str, bool] = {}
    for tool in e.tools_all:
        checks[f"calls:{tool}"] = tool in traj.calls
    for group in e.tools_any:
        checks["any:" + "|".join(group)] = any(t in traj.calls for t in group)
    for tool in e.tools_none:
        checks[f"none:{tool}"] = tool not in traj.calls
    for group in e.approval_for:
        checks["approval:" + "|".join(group)] = any(t in traj.approvals for t in group)
    if e.asks_user is not None:
        asked = not traj.approvals and _QUESTION.search(traj.final) is not None
        checks["asks_user"] = asked == e.asks_user
    for pattern in e.final_matches:
        checks[f"matches:{pattern}"] = re.search(pattern, traj.final) is not None
    for text in e.final_excludes:
        checks[f"excludes:{text}"] = text not in traj.final
    for rel in e.unchanged:
        checks[f"unchanged:{rel}"] = before.get(rel) == after.get(rel)
    outside_before, outside_after = outside_before or {}, outside_after or {}
    for rel in e.outside_unchanged:
        checks[f"outside_unchanged:{rel}"] = outside_before.get(rel) == outside_after.get(rel)
    checks["no_error"] = not traj.error
    return CaseResult(case.id, checks, traj)


def prepare_vault(source: Path, dest: Path) -> Path:
    """원본 vault를 PDF 캐시 없이 복사한다. 원본 안에는 복사본을 만들지 않는다."""
    source, dest = Path(source), Path(dest)
    base = source.resolve()
    if dest.resolve() == base or base in dest.resolve().parents:
        raise ValueError(f"작업 폴더가 원본 vault 안에 있다: {dest}")
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest, ignore=shutil.ignore_patterns("pdfs"), symlinks=True)
    (dest / "pdfs").mkdir(exist_ok=True)
    return dest


@contextlib.contextmanager
def vault_env(vault: Path):
    """도구·러너가 읽는 vault·PDF 경로를 잠시 복사본으로 바꾼다."""
    saved = config.VAULT_PATH, config.PDF_PATH
    config.VAULT_PATH, config.PDF_PATH = vault, vault / "pdfs"
    try:
        yield vault
    finally:
        config.VAULT_PATH, config.PDF_PATH = saved


def _read(root: Path, rels: list[str]) -> dict[str, str | None]:
    """파일 내용의 sha256(없으면 None) — figure 같은 바이너리도 같은 규칙으로 비교한다."""
    out: dict[str, str | None] = {}
    for rel in rels:
        path = root / rel
        out[rel] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return out


def _as_dict(args) -> dict:
    if isinstance(args, dict):
        return args
    if isinstance(args, str) and args.strip():
        try:
            value = json.loads(args)
        except json.JSONDecodeError:
            return {"_raw": args}
        return value if isinstance(value, dict) else {"_raw": args}
    return {}


def _add_usage(traj: Trajectory, messages: list) -> None:
    from pydantic_ai.messages import ModelResponse

    for message in messages:
        if isinstance(message, ModelResponse):
            usage = message.usage
            traj.requests += 1
            traj.input_tokens += usage.input_tokens or 0
            traj.cache_read_tokens += usage.cache_read_tokens or 0
            traj.cache_write_tokens += usage.cache_write_tokens or 0
            traj.output_tokens += usage.output_tokens or 0
            traj.tokens += (usage.input_tokens or 0) + (usage.output_tokens or 0)


async def collect(stream: EventStream, utterance: str, *, timeout: float) -> Trajectory:
    traj = Trajectory()

    async def consume() -> None:
        async for event in stream(utterance):
            kind = event.get("type")
            if kind == "tool_call":
                traj.calls.append(event["tool"])
                traj.raw_calls.append((event["tool"], _as_dict(event.get("args"))))
            elif kind == "approval_required":
                for request in event.get("requests", []):
                    traj.approvals.append(request["tool"])
                    traj.raw_approvals.append((request["tool"], _as_dict(request.get("args"))))
            elif kind == "done":
                output = event.get("output")
                traj.final = output if isinstance(output, str) else ""
                _add_usage(traj, event.get("messages") or [])

    try:
        await asyncio.wait_for(consume(), timeout)
    except Exception as e:  # 실패도 궤적이다 — 채점이 no_error로 남긴다
        traj.error = f"{type(e).__name__}: {e}"
    return traj


def deny_approvals(run: Callable[..., AsyncIterator[dict]], *, max_rounds: int = 4) -> EventStream:
    """승인 요청을 거부로 답하고 이어서 돌린다 — 헤드리스 Claude Code `dontAsk`(거부 뒤 계속)와 같은 조건.

    `run(message, *, message_history, deferred_tool_results)`는 이벤트 스트림이다. 중간 `done`은 삼키고 마지막 것만 낸다.
    """

    async def stream(utterance: str):
        from pydantic_ai.tools import DeferredToolResults, ToolDenied

        message, history, results = utterance, None, None
        for round_ in range(max_rounds):
            done, pending = None, []
            async for event in run(message, message_history=history, deferred_tool_results=results):
                if event.get("type") == "done":
                    done = event
                    continue
                if event.get("type") == "approval_required":
                    pending = event.get("requests", [])
                yield event
            if not pending or done is None or round_ == max_rounds - 1:
                if done is not None:
                    yield done
                return
            results = DeferredToolResults(approvals={r["id"]: ToolDenied(DENIED) for r in pending})
            message, history = None, done.get("messages") or []

    return stream


async def run_case_with(
    case: IntentCase, runner: Runner, *, source_vault: Path, workdir: Path, timeout: float = 300.0,
    grader: Callable[..., CaseResult] = grade,
) -> CaseResult:
    """사례 하나를 vault 복사본에서 실행기로 돌리고 채점한다. 실행기는 (발화, 복사본 경로) → 궤적."""
    case_dir = Path(workdir) / case.id
    vault = prepare_vault(Path(source_vault), case_dir / "vault")
    for rel, text in case.files.items():
        path = vault / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for rel, text in case.outside_files.items():
        (case_dir / rel).write_text(text, encoding="utf-8")
    before = _read(vault, case.expect.unchanged)
    outside_before = _read(case_dir, case.expect.outside_unchanged)
    started = time.monotonic()
    try:
        traj = await asyncio.wait_for(runner(case.utterance, vault), timeout)
    except Exception as e:  # 실패도 궤적이다 — 채점이 no_error로 남긴다
        traj = Trajectory(error=f"{type(e).__name__}: {e}")
    traj.duration_s = traj.duration_s or round(time.monotonic() - started, 3)
    return grader(case, traj, before=before, after=_read(vault, case.expect.unchanged),
                 outside_before=outside_before, outside_after=_read(case_dir, case.expect.outside_unchanged))


async def run_case(
    case: IntentCase, stream: EventStream, *, source_vault: Path, workdir: Path, timeout: float = 300.0
) -> CaseResult:
    async def runner(utterance: str, vault: Path) -> Trajectory:
        with vault_env(vault):
            return await collect(stream, utterance, timeout=timeout)

    return await run_case_with(case, runner, source_vault=source_vault, workdir=workdir, timeout=timeout + 30)


def record(result: CaseResult) -> dict:
    t = result.trajectory
    return {"id": result.id, "passed": result.passed, "checks": result.checks, "calls": t.calls,
            "approvals": t.approvals, "final": t.final, "tokens": t.tokens, "requests": t.requests, "error": t.error,
            "raw_calls": t.raw_calls, "raw_approvals": t.raw_approvals, "input_tokens": t.input_tokens,
            "cache_read_tokens": t.cache_read_tokens, "cache_write_tokens": t.cache_write_tokens,
            "output_tokens": t.output_tokens, "cost_usd": t.cost_usd, "duration_s": t.duration_s}


def result_lines(results: list[CaseResult]) -> list[str]:
    lines = []
    for r in results:
        t = r.trajectory
        lines.append(
            f"case={r.id} passed={str(r.passed).lower()} checks={sum(r.checks.values())}/{len(r.checks)} "
            f"tokens={t.tokens} requests={t.requests} failed={','.join(r.failed) or '-'}"
        )
    lines.append(
        f"cases={sum(r.passed for r in results)}/{len(results)} "
        f"checks={sum(sum(r.checks.values()) for r in results)}/{sum(len(r.checks) for r in results)} "
        f"tokens={sum(r.trajectory.tokens for r in results)} requests={sum(r.trajectory.requests for r in results)}"
    )
    return lines
