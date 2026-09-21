"""`python -m agent.evals` — 의도 이해 평가·노트 품질 비교를 실모델로 돈다(ADR-063·064·065·066).

    uv run python -m agent.evals intents --model openai:gpt-5 --workdir /tmp/intent-evals [--only a,b]
    uv run python -m agent.evals intents --cross --split holdout --repeat 3 --model openai:gpt-5 --arm C --workdir W
    uv run python -m agent.evals intents --system claude-code --split holdout --model claude-opus-5 --arm A --workdir W
    uv run python -m agent.evals summary W1/results.jsonl W2/results.jsonl
    uv run python -m agent.evals notes --arxiv 2411.00816 --reference cycleresearcher --model openai:gpt-5 --workdir W
    uv run python -m agent.evals notes-cross --papers kosmos,paperqa2 --models openai:gpt-5 --workdir W
    uv run python -m agent.evals judge --papers kosmos,paperqa2 --arms skill,openai_gpt-5 --workdir W

원본 vault(`--vault`, 기본 OBSIDIAN_VAULT_PATH)는 읽기만 한다 — 사례·논문마다 PDF 캐시를 뺀 복사본에서 돈다.
교차 비교(`--cross`·`--system claude-code`)는 승인 요청을 거부로 답하고 계속하며 능력 단위로 채점한다.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import time
from dataclasses import asdict
from itertools import combinations
from pathlib import Path

from agent.evals.capabilities import grade_capabilities
from agent.evals.claude_code import prepare_plugin
from agent.evals.intents import (
    DEFAULT_CASES,
    HOLDOUT_CASES,
    collect,
    deny_approvals,
    grade,
    load_cases,
    record,
    result_lines,
    run_case,
    run_case_with,
    vault_env,
)
from agent.evals.notes import comparison_lines, prepare_note_vault, run_note_eval
from agent.evals.summary import summarize, summary_lines
from core import config

REPO = Path(__file__).resolve().parents[2]
JUDGE_MODEL = "google:gemini-2.5-pro"
JUDGE_PAGES = 40


def _label(name: str) -> str:
    return name.replace(":", "_").replace("/", "_")


def _default_stream_factory(model: str):
    from agent.jobs import AutopilotJobs
    from agent.permissions import Policy
    from agent.runtime import HarnessDeps, make_agent
    from agent.streaming import run_event_stream

    agent = make_agent(model)
    jobs = AutopilotJobs()

    def stream(utterance: str):
        deps = HarnessDeps(policy=Policy("ask"), session_id="eval", model_name=model, jobs=jobs)
        return run_event_stream(agent, utterance, deps=deps)

    return stream


def _default_harness_factory(model: str):
    """(재개 가능한 이벤트 스트림, 사용량 기록 모델) — 하위 에이전트 요청까지 기록 모델로 센다."""
    from pydantic_ai.models import infer_model

    from agent.evals.usage import RecordingModel
    from agent.jobs import AutopilotJobs
    from agent.permissions import Policy
    from agent.runtime import HarnessDeps, make_agent
    from agent.streaming import run_event_stream

    recorder = RecordingModel(infer_model(model))
    agent = make_agent(recorder)
    jobs = AutopilotJobs()

    def run(message, *, message_history=None, deferred_tool_results=None):
        deps = HarnessDeps(policy=Policy("ask"), session_id="eval", model_name=model, jobs=jobs)
        return run_event_stream(agent, message, message_history, deps=deps, deferred_tool_results=deferred_tool_results)

    return run, recorder


def _default_runner_factory(model: str, *, repo: Path, plugin_dir: Path, budget_usd: float):
    from agent.evals.claude_code import make_runner

    return make_runner(model=model, repo=repo, plugin_dir=plugin_dir,
                       api_key=os.environ.get("ANTHROPIC_API_KEY", ""), budget_usd=budget_usd)


def _default_deps_factory(model: str):
    from agent.autopilot.deps import StandaloneDeps

    return StandaloneDeps(model)


def _default_cross_deps_factory(model: str):
    from pydantic_ai.models import infer_model

    from agent.autopilot.deps import StandaloneDeps
    from agent.evals.usage import RecordingModel

    return StandaloneDeps(RecordingModel(infer_model(model)))


def _default_judge_model(name: str):
    from pydantic_ai.models import infer_model

    from agent.evals.usage import RecordingModel

    return RecordingModel(infer_model(name))


def _default_source_text(source: Path):
    async def read(arxiv_id: str) -> str:
        from tools.pdf_tools import read_paper

        with vault_env(source):
            return await read_paper(arxiv_id, max_pages=JUDGE_PAGES)

    return read


def _priced(model: str, totals: dict) -> float | None:
    from agent.evals.pricing import cost_usd

    if not totals.get("requests"):
        return None
    return cost_usd(model, input_tokens=totals["input_tokens"], cache_read_tokens=totals["cache_read_tokens"],
                    cache_write_tokens=totals["cache_write_tokens"], output_tokens=totals["output_tokens"])


def _harness_runner(run, recorder, model: str, timeout: float):
    stream = deny_approvals(run)

    async def runner(utterance: str, vault: Path):
        if recorder is not None:
            recorder.reset()
        with vault_env(vault):
            traj = await collect(stream, utterance, timeout=timeout)
        if recorder is not None:
            totals = recorder.totals()
            traj.requests, traj.output_tokens = totals["requests"], totals["output_tokens"]
            traj.input_tokens, traj.cache_read_tokens = totals["input_tokens"], totals["cache_read_tokens"]
            traj.cache_write_tokens = totals["cache_write_tokens"]
            traj.tokens = traj.input_tokens + traj.output_tokens
            traj.cost_usd = _priced(model, totals)
        return traj

    return runner


async def _run_intents(args, source: Path, model: str, *, stream_factory, harness_factory, runner_factory) -> int:
    cases = load_cases(Path(args.cases)) if args.cases else load_cases(HOLDOUT_CASES if args.split == "holdout" else DEFAULT_CASES)
    only = {s for s in args.only.split(",") if s}
    if only:
        cases = [c for c in cases if c.id in only]
    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    os.environ["RESEARCH_AGENT_STATE_DIR"] = str(workdir / "state")  # 평가의 스냅샷·감사 로그는 작업 폴더에
    cross = args.cross or args.system == "claude-code"
    arm = args.arm or f"{args.system}:{model}"
    stream = runner = None
    if args.system == "claude-code":
        plugin = prepare_plugin(Path(args.repo), workdir / "plugin")
        runner = (runner_factory or _default_runner_factory)(model, repo=Path(args.repo), plugin_dir=plugin,
                                                             budget_usd=args.budget_usd)
    elif cross:
        run, recorder = (harness_factory or _default_harness_factory)(model)
        runner = _harness_runner(run, recorder, model, args.timeout)
    else:
        stream = (stream_factory or _default_stream_factory)(model)
    rows, results = [], []
    with (workdir / "results.jsonl").open("w", encoding="utf-8") as fh:
        for run_index in range(args.repeat):
            for case in cases:
                place = dict(source_vault=source, workdir=workdir / f"run-{run_index}")
                if runner is None:
                    result = await run_case(case, stream, timeout=args.timeout, **place)
                else:
                    result = await run_case_with(case, runner, timeout=args.timeout + 30,
                                                 grader=grade_capabilities if cross else grade,
                                                 **place)
                row = {**record(result), "arm": arm, "split": args.split, "run": run_index,
                       "grading": "capabilities" if cross else "tools"}
                rows.append(row)
                results.append(result)
                fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                fh.flush()
                print(f"arm={arm} run={run_index} " + result_lines([result])[0], flush=True)
    print(result_lines(results)[-1])
    for line in summary_lines(summarize(rows)):
        print(line)
    return 0


def _run_notes(args, deps, source: Path) -> int:
    workdir = Path(args.workdir)
    vault, reference = prepare_note_vault(source, workdir, arxiv_id=args.arxiv, reference_slug=args.reference)
    cmp = asyncio.run(run_note_eval(deps, vault=vault, reference_text=reference, reference_slug=args.reference))
    (workdir / "reference.md").write_text(reference, encoding="utf-8")
    (workdir / "candidate.md").write_text(cmp.candidate_text, encoding="utf-8")
    for line in comparison_lines(cmp):
        print(line)
    log = vault / "_meta" / "autopilot-log.md"
    if log.is_file():
        usage = [line for line in log.read_text(encoding="utf-8").splitlines() if "tokens=" in line]
        if usage:
            print(usage[-1])
    return 0


def _run_summary(args) -> int:
    rows = []
    for path in args.files:
        rows += [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    for line in summary_lines(summarize(rows, resamples=args.resamples)):
        print(line)
    return 0


def _note_stems(vault: Path, *, exclude_papers: set[str] | None = None) -> set[str]:
    exclude_papers = exclude_papers or set()
    stems = set()
    for path in Path(vault).rglob("*.md"):
        parts = path.relative_to(vault).parts
        if parts[0] == "pdfs" or (parts[0] == "papers" and len(parts) > 2 and parts[1] in exclude_papers):
            continue
        stems.add(path.stem)
    return stems


def _write_metrics(paper_dir: Path, label: str, accuracy, **extra) -> None:
    data = {**asdict(accuracy), **extra}
    (paper_dir / f"metrics-{label}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    fields = " ".join(f"{k}={v}" for k, v in data.items() if not isinstance(v, list))
    print(f"paper={paper_dir.name} arm={label} {fields}", flush=True)


async def _run_notes_cross(args, source: Path, *, deps_factory, source_text_fn) -> int:
    """스킬 모드 노트(워커 트랜스크립트 원문)와 독립 런타임 노트(ingest 직전 복사본에서 한 반복)를 같은 지표로 잰다."""
    from agent.evals.crossnotes import ingest_arxiv_ids, ingest_iters, note_accuracy, rollback_vault
    from agent.evals.transcripts import worker_runs
    from agent.runtime import resolve_model_name

    log_text = (source / "_meta" / "autopilot-log.md").read_text(encoding="utf-8")
    iters, ids = ingest_iters(log_text), ingest_arxiv_ids(log_text)
    skill_runs = [r for r in worker_runs(Path(args.transcripts)) if r.action == "ingest"]
    models = [resolve_model_name(m) for m in args.models.split(",") if m]
    failures = 0
    for slug in [s for s in args.papers.split(",") if s]:
        paper_dir = Path(args.workdir) / slug
        paper_dir.mkdir(parents=True, exist_ok=True)
        arxiv_id, before_iter = ids[slug], iters[slug]
        later = {s for s, it in iters.items() if it >= before_iter}
        papers = {p.name for p in (source / "papers").iterdir() if p.is_dir()} - later
        known = papers | {slug} | _note_stems(source, exclude_papers=later)
        text = source_text_fn(arxiv_id)
        source_text = await text if inspect.isawaitable(text) else text
        (paper_dir / "source.txt").write_text(source_text, encoding="utf-8")

        skill = next((r for r in reversed(skill_runs) if r.note_body(slug)), None)
        body = skill.note_body(slug) if skill else ""
        if skill:
            (paper_dir / "skill.md").write_text(body, encoding="utf-8")
            created = {Path(str(w.get("slug", ""))).name for w in skill.writes}
            _write_metrics(paper_dir, "skill", note_accuracy(body, source_text, paper_slugs=papers, known_slugs=known | created),
                           model=skill.models[0] if skill.models else "", status="ok", requests=skill.requests,
                           cache_read_tokens=skill.cache_read_tokens, output_tokens=skill.output_tokens,
                           cost_usd=skill.cost_usd(), duration_s=skill.duration_s)
        else:
            print(f"paper={slug} arm=skill status=missing", flush=True)

        for model in models:
            label = _label(model)
            vault, _ = prepare_note_vault(source, paper_dir / label, arxiv_id=arxiv_id, reference_slug=slug)
            rollback_vault(vault, log_text, before_iter=before_iter)
            deps = (deps_factory or _default_cross_deps_factory)(model)
            started = time.monotonic()
            try:
                cmp = await run_note_eval(deps, vault=vault, reference_text=body, reference_slug=slug)
            except Exception as e:  # 한 팔의 실패(제공자 오류 등)는 기록하고 다음 팔·논문으로 넘어간다
                failures += 1
                error = f"{type(e).__name__}: {e}"[:500]
                data = {"model": model, "status": "error", "error": error, "duration_s": round(time.monotonic() - started, 1)}
                (paper_dir / f"metrics-{label}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"paper={slug} arm={label} status=error error={error[:200]}", flush=True)
                continue
            duration = round(time.monotonic() - started, 1)
            (paper_dir / f"{label}.md").write_text(cmp.candidate_text, encoding="utf-8")
            recorder = getattr(deps, "model", None)
            totals = recorder.totals() if hasattr(recorder, "totals") else {}
            created = _note_stems(vault) | {p.name for p in (vault / "papers").iterdir() if p.is_dir()}
            _write_metrics(paper_dir, label,
                           note_accuracy(cmp.candidate_text, source_text, paper_slugs=papers, known_slugs=known | created),
                           model=model, status=cmp.outcome.status or cmp.outcome.action, requests=totals.get("requests"),
                           cache_read_tokens=totals.get("cache_read_tokens"), output_tokens=totals.get("output_tokens"),
                           input_tokens=totals.get("input_tokens"), cost_usd=_priced(model, totals) if totals else None,
                           duration_s=duration, runner_unverified_numbers=len(cmp.outcome.unverified_numbers))
    return 1 if failures else 0


async def _run_judge(args, *, judge_model_factory) -> int:
    """논문마다 노트 쌍을 순서를 바꿔 두 번 판정하고, 노트마다 원문으로 뒷받침되지 않는 주장을 모은다."""
    from agent.evals.crossnotes import CRITERIA, audit_claims, judge_pair, judge_text

    arms = [a for a in args.arms.split(",") if a]
    model = (judge_model_factory or _default_judge_model)(args.model)
    pairs = [f"{a}|{b}" for a, b in combinations(arms, 2)]
    tally = {key: dict.fromkeys(("papers", "a", "b", "tie", "inconsistent"), 0) for key in pairs}
    order = ("overall", *(c for c in CRITERIA if c != "overall"))
    for slug in [s for s in args.papers.split(",") if s]:
        paper_dir = Path(args.workdir) / slug
        source_text = (paper_dir / "source.txt").read_text(encoding="utf-8")
        notes = {arm: judge_text((paper_dir / f"{arm}.md").read_text(encoding="utf-8")) for arm in arms}
        result: dict = {"pairs": {}, "audits": {}}
        for key in pairs:
            a, b = key.split("|")
            verdict = await judge_pair(model, source_text, notes[a], notes[b])
            result["pairs"][key] = verdict
            tally[key]["papers"] += 1
            tally[key][verdict["overall"]] += 1
            print(f"paper={slug} pair={key} " + " ".join(f"{c}={verdict[c]}" for c in order), flush=True)
        for arm in arms:
            audit = await audit_claims(model, source_text, notes[arm])
            result["audits"][arm] = audit.model_dump()
            print(f"paper={slug} arm={arm} claims_checked={audit.claims_checked} unsupported={len(audit.unsupported)}", flush=True)
        (paper_dir / "judge.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    for key, t in tally.items():
        print(f"pair={key} papers={t['papers']} a={t['a']} b={t['b']} tie={t['tie']} inconsistent={t['inconsistent']}")
    if hasattr(model, "totals"):
        totals = model.totals()
        print(f"judge_model={args.model} requests={totals['requests']} cost_usd={_priced(args.model, totals)}")
    return 0


def main(argv: list[str] | None = None, *, stream_factory=None, deps_factory=None, harness_factory=None,
         runner_factory=None, source_text_fn=None, judge_model_factory=None) -> int:
    parser = argparse.ArgumentParser(prog="agent.evals", description="에이전트 의도 이해·노트 품질 평가")
    sub = parser.add_subparsers(dest="command", required=True)
    intents = sub.add_parser("intents", help="의도 이해 사례 채점")
    intents.add_argument("--cases", default=None, help="사례 JSON (기본: --split에 따라 dev 또는 held-out)")
    intents.add_argument("--only", default="", help="쉼표로 고른 사례 id")
    intents.add_argument("--timeout", type=float, default=300.0, help="사례당 제한 시간(초)")
    intents.add_argument("--system", choices=("harness", "claude-code"), default="harness")
    intents.add_argument("--split", choices=("dev", "holdout"), default="dev")
    intents.add_argument("--repeat", type=int, default=1)
    intents.add_argument("--cross", action="store_true", help="승인 거부 후 계속 + 능력 단위 채점(claude-code는 항상)")
    intents.add_argument("--arm", default=None, help="결과 행의 팔 이름 (기본: system:model)")
    intents.add_argument("--budget-usd", type=float, default=3.0, help="claude-code 실행당 비용 상한")
    intents.add_argument("--repo", default=str(REPO), help="스킬 사본을 뜰 저장소")
    notes = sub.add_parser("notes", help="같은 논문의 기준 노트와 독립 런타임 노트 비교")
    notes.add_argument("--arxiv", required=True)
    notes.add_argument("--reference", required=True, help="기준 노트 slug (papers/<slug>)")
    for p in (intents, notes):
        p.add_argument("--model", default=None, help="provider:model (없으면 RESEARCH_MODEL)")
        p.add_argument("--vault", default=None, help="원본 vault (읽기만 함)")
        p.add_argument("--workdir", required=True, help="복사본·결과를 둘 폴더 (원본 vault 밖)")
    summary = sub.add_parser("summary", help="results.jsonl 집계")
    summary.add_argument("files", nargs="+")
    summary.add_argument("--resamples", type=int, default=1000)
    cross = sub.add_parser("notes-cross", help="스킬 모드 노트(트랜스크립트)와 독립 런타임 노트를 같은 지표로")
    cross.add_argument("--papers", required=True, help="쉼표로 고른 논문 slug")
    cross.add_argument("--models", default="", help="쉼표로 고른 provider:model (비우면 스킬 모드 지표만)")
    cross.add_argument("--vault", default=None, help="원본 vault (읽기만 함)")
    cross.add_argument("--workdir", required=True)
    cross.add_argument("--transcripts", default=str(Path.home() / ".claude" / "projects" / str(REPO).replace("/", "-")))
    judge = sub.add_parser("judge", help="노트 쌍 블라인드 판정(순서 교차)·주장 감사")
    judge.add_argument("--papers", required=True)
    judge.add_argument("--arms", required=True, help="쉼표로 고른 노트 이름 (notes-cross가 쓴 <arm>.md)")
    judge.add_argument("--workdir", required=True)
    judge.add_argument("--model", default=JUDGE_MODEL)
    args = parser.parse_args(argv)

    if args.command == "summary":
        return _run_summary(args)
    if args.command == "judge":
        return asyncio.run(_run_judge(args, judge_model_factory=judge_model_factory))
    source = Path(args.vault).expanduser() if args.vault else config.VAULT_PATH
    if args.command == "notes-cross":
        return asyncio.run(_run_notes_cross(args, source, deps_factory=deps_factory,
                                            source_text_fn=source_text_fn or _default_source_text(source)))

    from agent.runtime import resolve_model_name

    model = resolve_model_name(args.model)
    if args.command == "intents":
        return asyncio.run(_run_intents(args, source, model, stream_factory=stream_factory,
                                        harness_factory=harness_factory, runner_factory=runner_factory))
    return _run_notes(args, (deps_factory or _default_deps_factory)(model), source)


if __name__ == "__main__":
    raise SystemExit(main())
