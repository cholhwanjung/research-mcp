"""스킬 모드 워커 트랜스크립트 읽기 — autopilot 워커(서브에이전트) 한 번의 사용량·저장한 노트 원문(ADR-066).

Claude Code는 서브에이전트 대화를 `<프로젝트>/<세션>/subagents/*.jsonl`에 남긴다. 첫 사용자 메시지가 워커 프롬프트인
파일만 고른다. 한 응답이 여러 줄로 기록되므로 사용량은 메시지 id별 최댓값을 합친다. 캐시 쓰기의 5분·1시간 분할이
없는 줄은 5분으로 본다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from agent.evals.pricing import cost_usd as priced

WORKER_MARK = "research-autopilot 스킬의 한 반복을 워커 모드로"
_ACTION = re.compile(r"action=(\w+)")
_SLUG = re.compile(r"slug=([\w.-]+)")
_ARXIV = re.compile(r"\bid=(\d{4}\.\d{4,5})")


@dataclass
class WorkerRun:
    session: str
    path: Path
    action: str = "-"
    slug: str = "-"
    arxiv_id: str = "-"
    requests: int = 0
    uncached_input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_5m_tokens: int = 0
    cache_write_1h_tokens: int = 0
    output_tokens: int = 0
    duration_s: float = 0.0
    models: list[str] = field(default_factory=list)
    writes: list[dict] = field(default_factory=list)

    def note_body(self, slug: str) -> str | None:
        """그 논문 노트에 마지막으로 저장한 본문(저장 당시 원문)."""
        target = re.compile(rf"(^|/){re.escape(slug)}(/{re.escape(slug)})?(\.md)?$")
        bodies = [w.get("body") for w in self.writes if target.search(str(w.get("slug", "")))]
        return str(bodies[-1]) if bodies else None

    def cost_usd(self) -> float | None:
        if not self.models:
            return None
        total = self.uncached_input_tokens + self.cache_read_tokens + self.cache_write_5m_tokens + self.cache_write_1h_tokens
        return priced(self.models[0], input_tokens=total, cache_read_tokens=self.cache_read_tokens,
                      cache_write_tokens=self.cache_write_5m_tokens, cache_write_1h_tokens=self.cache_write_1h_tokens,
                      output_tokens=self.output_tokens)


def _events(path: Path) -> list[dict]:
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    return " ".join(part.get("text", "") for part in content or [] if isinstance(part, dict) and part.get("type") == "text")


def _measure(path: Path, events: list[dict]) -> WorkerRun:
    run = WorkerRun(session=path.parent.parent.name, path=path)
    per: dict[str, dict[str, int]] = {}
    stamps: list[str] = []
    final = ""
    for event in events:
        if event.get("timestamp"):
            stamps.append(event["timestamp"])
        if event.get("type") != "assistant":
            continue
        message = event.get("message") or {}
        usage = message.get("usage") or {}
        split = usage.get("cache_creation") or {}
        counts = per.setdefault(message.get("id") or f"_{len(per)}", dict.fromkeys(("inp", "cr", "cw", "cw5", "cw1", "out"), 0))
        for key, value in (("inp", usage.get("input_tokens")), ("cr", usage.get("cache_read_input_tokens")),
                           ("cw", usage.get("cache_creation_input_tokens")),
                           ("cw5", split.get("ephemeral_5m_input_tokens")), ("cw1", split.get("ephemeral_1h_input_tokens")),
                           ("out", usage.get("output_tokens"))):
            counts[key] = max(counts[key], int(value or 0))
        model = message.get("model")
        if model and not model.startswith("<") and model not in run.models:
            run.models.append(model)
        for block in message.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and str(block.get("name", "")).endswith("wiki_write_note"):
                run.writes.append(block.get("input") or {})
            elif block.get("type") == "text":
                final = block.get("text", "")
    run.requests = len(per)
    run.uncached_input_tokens = sum(c["inp"] for c in per.values())
    run.cache_read_tokens = sum(c["cr"] for c in per.values())
    run.cache_write_1h_tokens = sum(c["cw1"] for c in per.values())
    run.cache_write_5m_tokens = sum(max(c["cw"] - c["cw1"], c["cw5"]) for c in per.values())
    run.output_tokens = sum(c["out"] for c in per.values())
    if len(stamps) >= 2:
        first, last = (datetime.fromisoformat(s.replace("Z", "+00:00")) for s in (stamps[0], stamps[-1]))
        run.duration_s = (last - first).total_seconds()
    for pattern, attr in ((_ACTION, "action"), (_SLUG, "slug"), (_ARXIV, "arxiv_id")):
        if match := pattern.search(final):
            setattr(run, attr, match.group(1))
    return run


def worker_runs(project_dir: Path, *, mark: str = WORKER_MARK) -> list[WorkerRun]:
    runs = []
    for path in sorted(Path(project_dir).glob("*/subagents/*.jsonl")):
        events = _events(path)
        first = next((e for e in events if e.get("type") == "user"), None)
        if first is not None and mark in _content_text((first.get("message") or {}).get("content")):
            runs.append(_measure(path, events))
    return runs
