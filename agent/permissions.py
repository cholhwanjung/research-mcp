"""도구 권한 — 모드·세션 허용·보호 경로로 호출마다 allow/ask/deny를 정하고, 한 wrapper toolset에서 집행한다(ADR-063).

판정 순서: 경로(vault 밖·보호 경로) deny → 읽기 전용 모드 deny → 읽기·제어 allow → 편집의 세션 허용·편집 자동 허용
→ ask. ask는 실행 전에 `ApprovalRequired`로 멈추고 미리보기를 metadata에 싣는다. 쓰기 계열은 실행 전에 스냅샷을
남기고 결과 metadata에 id를 싣는다. 읽기가 아닌 호출과 거부는 감사 로그에 남긴다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic_ai.exceptions import ApprovalRequired
from pydantic_ai.messages import ToolReturn
from pydantic_ai.toolsets import WrapperToolset

from agent.workspace import AuditLog, SnapshotStore, is_protected, preview, target_path
from tools.wiki_tools import _resolve_slug
from wiki.vault import VaultPathError, paper_dir, vault_path, vault_root

Decision = Literal["allow", "ask", "deny"]
MODES = ("read_only", "ask", "accept_edits")

TOOL_KINDS: dict[str, str] = {
    # 읽기 — 외부 조회·vault 읽기·캐시 다운로드·읽기 전용 위임
    "search_papers": "read", "get_paper_by_id": "read", "get_references_by_citations": "read",
    "get_citations_by_citations": "read", "get_citation_contexts": "read", "download_paper": "read",
    "read_paper": "read", "wiki_read_note": "read", "wiki_list_hubs": "read", "wiki_list": "read",
    "wiki_search": "read", "wiki_backlinks": "read", "get_tech_blog_posts": "read", "read_blog_post": "read",
    "read_file": "read", "glob_files": "read", "grep_files": "read", "load_skill": "read",
    "read_skill_file": "read", "delegate": "read", "autopilot_status": "read", "autopilot_report": "read",
    # 제어 — 실행 중인 작업을 멈춘다
    "autopilot_stop": "control",
    # 편집 — vault 파일을 바꾼다
    "wiki_write_note": "edit", "wiki_link": "edit", "write_file": "edit", "edit_file": "edit",
    "build_citation_graph": "edit", "export_citation_network": "edit", "render_paper_page": "edit",
    "mark_blog_posts_seen": "edit", "autopilot_config": "edit",
    # 삭제
    "prune_paper_figures": "delete", "prune_paper_tables": "delete",
    # 비용 — 모델·외부 API 호출이 이어진다
    "autopilot_start": "costly", "extract_paper_figures": "costly", "extract_paper_tables": "costly",
}

_KIND_REASON = {
    "edit": "vault 파일을 바꾼다",
    "delete": "vault 파일을 지운다",
    "costly": "모델·외부 API 비용이 든다",
    "unknown": "분류되지 않은 도구",
}
_PATH_ARGS = {"read_file": "path", "write_file": "path", "edit_file": "path", "wiki_read_note": "slug",
              "wiki_write_note": "slug", "wiki_link": "source", "wiki_list": "prefix"}
_SLUG_TOOLS = ("prune_paper_figures", "prune_paper_tables", "extract_paper_figures", "extract_paper_tables",
               "render_paper_page")


def tool_kind(tool: str) -> str:
    return TOOL_KINDS.get(tool, "unknown")


def rememberable(tool: str) -> bool:
    """'이 세션 동안 허용'으로 기억할 수 있는 도구 — 편집만. 삭제·비용 작업은 매번 묻는다."""
    return tool_kind(tool) == "edit"


def _path_problem(tool: str, args: dict) -> str:
    try:
        if tool in _SLUG_TOOLS and args.get("slug"):
            paper_dir(str(args["slug"]))
        if tool == "build_citation_graph" and args.get("slug"):
            vault_path(f"graphs/{args['slug']}.md")
        key = _PATH_ARGS.get(tool)
        value = args.get(key) if key else None
        if not isinstance(value, str) or not value.strip():
            return ""
        path = _resolve_slug(value) if tool.startswith("wiki_") and tool != "wiki_list" else vault_path(value)
        rel = path.resolve().relative_to(vault_root().resolve()).as_posix() if path.resolve() != vault_root().resolve() else ""
    except VaultPathError as e:
        return str(e)
    except ValueError:  # resolve 결과가 vault 밖(relative_to 실패)
        return f"vault 밖 경로는 허용되지 않습니다: {value!r}"
    if tool_kind(tool) != "read" and is_protected(rel):
        return f"보호된 경로는 쓰지 않습니다: {rel}"
    return ""


@dataclass
class Policy:
    mode: str = "ask"
    session_allow: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"알 수 없는 모드: {self.mode} ({'|'.join(MODES)})")

    def decide(self, tool: str, args: dict | None = None) -> tuple[Decision, str]:
        args = args or {}
        kind = tool_kind(tool)
        if problem := _path_problem(tool, args):
            return "deny", problem
        if self.mode == "read_only" and kind != "read":
            return "deny", "읽기 전용 모드 — 쓰기·실행 도구를 쓸 수 없다"
        if kind in ("read", "control"):
            return "allow", ""
        if kind == "edit" and (self.mode == "accept_edits" or tool in self.session_allow):
            return "allow", ""
        return "ask", _KIND_REASON[kind]

    def visible(self, tool: str) -> bool:
        return self.mode != "read_only" or tool_kind(tool) == "read"


@dataclass
class ToolContext:
    """도구 호출이 보는 실행 문맥(agent deps). 하네스는 이것을 확장해 모델·작업 레지스트리를 더한다."""

    policy: Policy = field(default_factory=Policy)
    session_id: str = ""
    snapshots: SnapshotStore = field(default_factory=SnapshotStore)
    audit: AuditLog = field(default_factory=AuditLog)


def _tool_context(ctx: Any) -> ToolContext:
    deps = ctx.deps
    if deps is None:
        return ToolContext()
    if not isinstance(getattr(deps, "policy", None), Policy):
        raise TypeError("PolicyToolset은 ToolContext deps가 필요하다")
    return deps


@dataclass
class PolicyToolset(WrapperToolset):
    """권한 판정을 집행하는 유일한 자리."""

    async def get_tools(self, ctx):
        tools = await super().get_tools(ctx)
        policy = _tool_context(ctx).policy
        return {name: tool for name, tool in tools.items() if policy.visible(name)}

    async def call_tool(self, name, tool_args, ctx, tool):
        context = _tool_context(ctx)
        decision, reason = context.policy.decide(name, tool_args)
        kind = tool_kind(name)
        approved = bool(ctx.tool_call_approved)
        target = target_path(name, tool_args) if kind != "read" else None

        def audit(snapshot: str | None = None) -> None:
            context.audit.write(session=context.session_id, tool=name, decision=decision, approved=approved,
                                path=target, snapshot=snapshot, reason=reason)

        if decision == "deny":
            audit()
            return f"❌ 권한 거부: {reason}"
        if decision == "ask" and not approved:
            audit()
            raise ApprovalRequired(metadata={"reason": reason, "preview": preview(name, tool_args),
                                             "rememberable": rememberable(name)})
        if kind == "read":
            return await super().call_tool(name, tool_args, ctx, tool)
        sid = context.snapshots.save(target) if target else None
        result = await super().call_tool(name, tool_args, ctx, tool)
        if sid and isinstance(result, str) and result.lstrip().startswith("❌"):
            context.snapshots.discard(sid)
            sid = None
        audit(sid)
        if sid and isinstance(result, str):
            return ToolReturn(return_value=result, metadata={"snapshot": sid, "path": target})
        return result
