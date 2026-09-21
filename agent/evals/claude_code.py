"""스킬 모드 팔 — 헤드리스 Claude Code를 vault 복사본에서 돌리고 stream-json을 궤적으로 읽는다(ADR-065).

작업 폴더 = vault 복사본, MCP 서버는 이 저장소의 server.py를 복사본 경로로 띄운다. 읽기 종류 도구만 허용하고
나머지는 `dontAsk`로 거부한다 — 거부된 부작용 호출이 하네스의 승인 요청에 해당한다. 자식 환경은 기본 변수와
API 키만 넘기고(데스크톱 앱 변수·사용자 설정·훅 차단), 실행마다 비용 상한을 둔다. 하위 에이전트 안의 호출은
궤적에 넣지 않는다(하네스 delegate와 같은 단위).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from agent.evals.intents import Runner, Trajectory

SERVER = "research"
MCP_READ_TOOLS = (
    "search_papers", "get_paper_by_id", "get_references_by_citations", "get_citations_by_citations",
    "get_citation_contexts", "download_paper", "read_paper", "wiki_read_note", "wiki_list_hubs", "wiki_list",
    "wiki_search", "wiki_backlinks", "get_tech_blog_posts", "read_blog_post",
)
BUILTIN_TOOLS = ("Read(./**)", "Glob(./**)", "Grep(./**)", "Skill", "ToolSearch",
                 "TaskCreate", "TaskGet", "TaskList", "TaskUpdate")
DEFAULT_UV = shutil.which("uv") or "/opt/homebrew/bin/uv"
_ENV_KEYS = ("HOME", "USER", "PATH", "LANG", "LC_ALL", "TMPDIR", "SHELL", "TERM")


def allowed_tools() -> list[str]:
    return [*BUILTIN_TOOLS, *(f"mcp__{SERVER}__{name}" for name in MCP_READ_TOOLS)]


def prepare_plugin(repo: Path, dest: Path) -> Path:
    """저장소 스킬을 사본으로 떠 플러그인 디렉토리를 만든다 — 실행 중에 스킬 파일이 바뀌어도 평가 조건이 고정된다."""
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(Path(repo) / ".claude" / "skills", dest / "skills")
    (dest / ".claude-plugin").mkdir(parents=True)
    manifest = {"name": "research-mcp", "version": "0.0.0-eval", "skills": "./skills/"}
    (dest / ".claude-plugin" / "plugin.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return dest


def mcp_config(repo: Path, vault: Path, *, uv: str | None = None) -> dict:
    return {"mcpServers": {SERVER: {
        "command": uv or DEFAULT_UV,
        "args": ["--directory", str(repo), "run", "python", "server.py"],
        "env": {"OBSIDIAN_VAULT_PATH": str(vault), "PDF_PATH": str(Path(vault) / "pdfs")},
    }}}


def child_env(api_key: str, base: Mapping[str, str]) -> dict[str, str]:
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY가 비어 있다 — 헤드리스 Claude Code 평가는 API 키로만 돈다")
    env = {key: base[key] for key in _ENV_KEYS if base.get(key)}
    env["ANTHROPIC_API_KEY"] = api_key
    return env


def build_command(utterance: str, *, model: str, plugin_dir: Path, mcp_path: Path, budget_usd: float,
                  claude: Sequence[str] = ("claude",)) -> list[str]:
    return [*claude, "-p", utterance, "--model", model, "--output-format", "stream-json", "--verbose",
            "--no-session-persistence", "--setting-sources", "project", "--strict-mcp-config",
            "--mcp-config", str(mcp_path), "--plugin-dir", str(plugin_dir), "--permission-mode", "dontAsk",
            "--max-budget-usd", f"{budget_usd:g}", "--allowedTools", *allowed_tools()]


def _usage(result: dict) -> tuple[int, int, int, int]:
    """(캐시 제외 입력, 캐시 읽기, 캐시 쓰기, 출력) — 모델별 합계가 있으면 그것(하위 에이전트 포함)."""
    by_model = result.get("modelUsage") or {}
    if by_model:
        keys = ("inputTokens", "cacheReadInputTokens", "cacheCreationInputTokens", "outputTokens")
        return tuple(sum(int(u.get(k) or 0) for u in by_model.values()) for k in keys)  # type: ignore[return-value]
    u = result.get("usage") or {}
    keys = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens")
    return tuple(int(u.get(k) or 0) for k in keys)  # type: ignore[return-value]


def parse_stream(lines: Iterable[str]) -> Trajectory:
    traj = Trajectory()
    message_ids: set[str] = set()
    result: dict | None = None
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "assistant":
            message = event.get("message") or {}
            if message.get("id"):
                message_ids.add(message["id"])
            if event.get("parent_tool_use_id"):
                continue
            for block in message.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    args = block.get("input") if isinstance(block.get("input"), dict) else {}
                    traj.calls.append(block["name"])
                    traj.raw_calls.append((block["name"], args))
        elif event.get("type") == "result":
            result = event
    traj.requests = len(message_ids)
    if result is None:
        traj.error = "no result"
        return traj
    text = str(result.get("result") or "")
    if result.get("is_error") or result.get("subtype") != "success":
        traj.error = f"{result.get('subtype')}: {text[:300]}"
    else:
        traj.final = text
    for denial in result.get("permission_denials") or []:
        args = denial.get("tool_input") if isinstance(denial.get("tool_input"), dict) else {}
        traj.approvals.append(str(denial.get("tool_name", "")))
        traj.raw_approvals.append((str(denial.get("tool_name", "")), args))
    uncached, cache_read, cache_write, output = _usage(result)
    traj.cache_read_tokens, traj.cache_write_tokens, traj.output_tokens = cache_read, cache_write, output
    traj.input_tokens = uncached + cache_read + cache_write
    traj.tokens = traj.input_tokens + output
    traj.cost_usd = result.get("total_cost_usd")
    traj.duration_s = (result.get("duration_ms") or 0) / 1000
    return traj


def make_runner(*, model: str, repo: Path, plugin_dir: Path, api_key: str, budget_usd: float,
                claude: Sequence[str] = ("claude",), base_env: Mapping[str, str] | None = None,
                uv: str | None = None) -> Runner:
    """(발화, vault 복사본) → 궤적. 복사본 옆에 mcp.json·stream.jsonl·stderr.log를 남긴다."""
    env = child_env(api_key, os.environ if base_env is None else base_env)

    async def runner(utterance: str, vault: Path) -> Trajectory:
        vault = Path(vault)
        mcp_path = vault.parent / "mcp.json"
        mcp_path.write_text(json.dumps(mcp_config(Path(repo), vault, uv=uv), ensure_ascii=False, indent=1),
                            encoding="utf-8")
        cmd = build_command(utterance, model=model, plugin_dir=plugin_dir, mcp_path=mcp_path,
                            budget_usd=budget_usd, claude=claude)
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(vault), env=env, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await proc.communicate()
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
        (vault.parent / "stream.jsonl").write_bytes(stdout)
        (vault.parent / "stderr.log").write_bytes(stderr)
        traj = parse_stream(stdout.decode("utf-8", "replace").splitlines())
        if traj.error == "no result" and proc.returncode:
            traj.error = f"exit={proc.returncode}: {stderr.decode('utf-8', 'replace')[-300:]}"
        return traj

    return runner
