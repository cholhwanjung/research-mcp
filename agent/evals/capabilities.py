"""도구 호출을 능력 단위로 정규화한다 — 스킬 모드(Claude Code)와 독립 하네스를 같은 기대값으로 채점하려고(ADR-065).

두 시스템은 도구 이름이 다르다(`Read`·`mcp__research__wiki_write_note` 대 `read_file`·`wiki_write_note`).
호출 하나를 이름과 인자로 능력 집합에 대응시키고, 사례 기대값의 도구 이름도 같은 표로 옮긴다.
autopilot 제어 노트 쓰기는 설정·정지, 제어 노트·로그 읽기는 보고로 본다(일반 읽기·쓰기와 섞지 않는다).
"""

from __future__ import annotations

import json
import re
from dataclasses import replace

from agent.evals.intents import CaseResult, Expect, IntentCase, Trajectory, grade

SIDE_EFFECTS = frozenset({
    "vault_write", "vault_delete", "figure_extract", "graph_build", "blog_mark",
    "autopilot_start", "autopilot_stop", "autopilot_config",
})
CAPABILITIES = SIDE_EFFECTS | {
    "vault_read", "paper_search", "paper_fetch", "citation_read", "blog_read", "skill_load", "delegate",
    "autopilot_report", "web", "shell", "other",
}

_MCP_PREFIX = re.compile(r"^mcp__.+?__")
_CONTROL = re.compile(r"(^|/)_meta/autopilot(\.md)?$")
_LOG = re.compile(r"(^|/)_meta/autopilot-log(\.md)?$")
_SKILL_FILE = re.compile(r"/skills/[^/]+/[^/]+\.md$")
_STOP_TRUE = re.compile(r"(?im)^\s*stop:\s*true\b")
_WORKER_PROMPT = re.compile(r"워커 모드")
_REDIRECT_NOISE = re.compile(r"\d*>&\d|\d*>\s*/dev/null")
_BASH_DELETE = re.compile(r"(^|[\s;&|(])rm\s")
_BASH_WRITE = re.compile(r">|\btee\b|\bmv\s|\bcp\s|\bsed\s+-i|\bmkdir\s|\btouch\s")
_BASH_SEGMENTS = re.compile(r"&&|\|\||[;|]")

_READS = {"read_file", "glob_files", "grep_files", "wiki_read_note", "wiki_list", "wiki_list_hubs", "wiki_search",
          "wiki_backlinks", "Read", "Glob", "Grep"}
_WRITES = {"write_file", "edit_file", "wiki_write_note", "Write", "Edit"}
_IGNORED = {"ToolSearch", "TodoWrite", "TaskCreate", "TaskGet", "TaskList", "TaskUpdate", "TaskOutput", "TaskStop"}
_READ_COMMANDS = {"ls", "cat", "head", "tail", "grep", "rg", "find", "wc", "sed", "awk", "sort", "uniq", "cut", "tr",
                  "cd", "pwd", "echo", "stat", "du", "tree", "basename", "dirname", "jq"}
_BY_NAME = {
    "search_papers": "paper_search",
    "get_paper_by_id": "paper_fetch", "read_paper": "paper_fetch", "download_paper": "paper_fetch",
    "get_references_by_citations": "citation_read", "get_citations_by_citations": "citation_read",
    "get_citation_contexts": "citation_read",
    "extract_paper_figures": "figure_extract", "extract_paper_tables": "figure_extract",
    "render_paper_page": "figure_extract",
    "prune_paper_figures": "vault_delete", "prune_paper_tables": "vault_delete",
    "build_citation_graph": "graph_build", "export_citation_network": "graph_build",
    "get_tech_blog_posts": "blog_read", "read_blog_post": "blog_read", "mark_blog_posts_seen": "blog_mark",
    "wiki_link": "vault_write", "NotebookEdit": "vault_write",
    "load_skill": "skill_load", "read_skill_file": "skill_load", "Skill": "skill_load",
    "delegate": "delegate",
    "autopilot_start": "autopilot_start", "CronCreate": "autopilot_start", "ScheduleWakeup": "autopilot_start",
    "autopilot_stop": "autopilot_stop", "CronDelete": "autopilot_stop",
    "autopilot_config": "autopilot_config",
    "autopilot_report": "autopilot_report", "autopilot_status": "autopilot_report", "CronList": "autopilot_report",
    "WebSearch": "web", "WebFetch": "web",
}


def _text(value) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _target(args: dict) -> str:
    for key in ("file_path", "path", "slug", "notebook_path"):
        if args.get(key):
            return str(args[key])
    return ""


def _written_text(args: dict) -> str:
    parts = [_text(args.get(key)) for key in ("content", "new_string", "body")]
    frontmatter = args.get("frontmatter")
    if isinstance(frontmatter, dict):
        parts.append("\n".join(f"{k}: {str(v).lower() if isinstance(v, bool) else v}" for k, v in frontmatter.items()))
    else:
        parts.append(_text(frontmatter))
    return "\n".join(p for p in parts if p)


def _bash(command: str) -> set[str]:
    cleaned = _REDIRECT_NOISE.sub(" ", command)
    touches_autopilot = "_meta/autopilot" in cleaned
    if _BASH_DELETE.search(cleaned):
        return {"vault_delete"}
    if _BASH_WRITE.search(cleaned):
        if touches_autopilot:
            return {"autopilot_stop"} if re.search(r"stop:\s*true", cleaned) else {"autopilot_config"}
        return {"vault_write"}
    segments = [s.strip() for s in _BASH_SEGMENTS.split(cleaned) if s.strip()]
    if segments and all(s.split()[0] in _READ_COMMANDS for s in segments):
        return {"autopilot_report"} if touches_autopilot else {"vault_read"}
    return {"shell"}


def capabilities_of(tool: str, args: dict | None = None) -> set[str]:
    """도구 호출 하나(이름·인자) → 능력 집합. 기록만 하는 도구(ToolSearch·작업 목록)는 빈 집합."""
    name = _MCP_PREFIX.sub("", tool)
    args = args if isinstance(args, dict) else {}
    if name in _IGNORED:
        return set()
    if name == "Bash":
        return _bash(str(args.get("command", "")))
    if name in ("Task", "Agent"):
        return {"autopilot_start"} if _WORKER_PROMPT.search(_text(args.get("prompt"))) else {"delegate"}
    target = _target(args)
    if name in _READS:
        if _CONTROL.search(target) or _LOG.search(target):
            return {"autopilot_report"}
        return {"skill_load"} if _SKILL_FILE.search(target) else {"vault_read"}
    if name in _WRITES:
        if _CONTROL.search(target):
            return {"autopilot_stop"} if _STOP_TRUE.search(_written_text(args)) else {"autopilot_config"}
        return {"vault_write"}
    return {_BY_NAME[name]} if name in _BY_NAME else {"other"}


def _translate(names: list[str]) -> list[str]:
    out: list[str] = []
    for name in names:
        for cap in ([name] if name in CAPABILITIES else sorted(capabilities_of(name))):
            if cap not in out:
                out.append(cap)
    return out


def translate_expect(expect: Expect) -> Expect:
    """기대값의 도구 이름을 능력 이름으로 옮긴다. 이미 능력 이름이면 그대로."""
    return expect.model_copy(update={
        "tools_all": _translate(expect.tools_all),
        "tools_any": [_translate(group) for group in expect.tools_any],
        "tools_none": _translate(expect.tools_none),
        "approval_for": [_translate(group) for group in expect.approval_for],
    })


def _flatten(calls: list[tuple[str, dict]]) -> list[str]:
    out: list[str] = []
    for tool, args in calls:
        for cap in sorted(capabilities_of(tool, args)):
            if cap not in out:
                out.append(cap)
    return out


def capability_trajectory(traj: Trajectory) -> Trajectory:
    """호출·승인 요청을 능력 이름으로 바꾼 궤적. 승인 요청은 부작용 능력만 남긴다(거부된 읽기는 승인 요청이 아니다)."""
    calls = traj.raw_calls or [(tool, {}) for tool in traj.calls]
    approvals = traj.raw_approvals or [(tool, {}) for tool in traj.approvals]
    return replace(traj, calls=_flatten(calls), approvals=[c for c in _flatten(approvals) if c in SIDE_EFFECTS])


def grade_capabilities(case: IntentCase, traj: Trajectory, *, before: dict, after: dict,
                       outside_before: dict | None = None, outside_after: dict | None = None) -> CaseResult:
    translated = case.model_copy(update={"expect": translate_expect(case.expect)})
    return grade(translated, capability_trajectory(traj), before=before, after=after,
                 outside_before=outside_before, outside_after=outside_after)
