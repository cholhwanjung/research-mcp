"""vault 작업 공간 — 파일 읽기·쓰기·편집·찾기·검색 도구, 쓰기 전 스냅샷, 감사 로그, 승인 미리보기(ADR-063).

Claude Code의 파일 도구에 대응하되 경로는 vault 안만 받는다(`wiki.vault.vault_path`). `.obsidian/`·`.git/`은
쓰지 않는다. 스냅샷·감사 로그는 vault 밖 상태 폴더(`RESEARCH_AGENT_STATE_DIR`, 기본 `CACHE_DIR/agent`)에 둔다 —
작업 공간 도구로 고칠 수 없게.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import secrets
import shutil
from datetime import datetime
from pathlib import Path

from core import config
from tools.wiki_tools import _resolve_slug
from wiki.frontmatter import dump_note
from wiki.vault import VaultPathError, paper_dir, vault_path, vault_root

PROTECTED_DIRS = (".obsidian", ".git")
READ_LIMIT = 400
_PREVIEW_LIMIT = 6000
_LINE_LIMIT = 300
_SID = re.compile(r"^\d{8}T\d{6}-[0-9a-f]{6}$")


def state_dir() -> Path:
    env = os.getenv("RESEARCH_AGENT_STATE_DIR")
    return Path(env) if env else config.CACHE_DIR / "agent"


def is_protected(rel: str) -> bool:
    parts = Path(rel).parts
    return bool(parts) and parts[0] in PROTECTED_DIRS


def _rel(path: Path) -> str:
    return path.resolve().relative_to(vault_root().resolve()).as_posix()


def _writable(path: str) -> Path | str:
    try:
        p = vault_path(path)
    except VaultPathError as e:
        return f"❌ {e}"
    if is_protected(_rel(p)):
        return f"❌ 보호된 경로는 쓰지 않습니다: {path}"
    if p.is_dir():
        return f"❌ 폴더에는 쓸 수 없습니다: {path}"
    return p


# ---- 도구 ----


def read_file(path: str, offset: int = 1, limit: int = READ_LIMIT) -> str:
    """vault 안 텍스트 파일을 줄 번호와 함께 읽는다.

    Args:
        path: vault 상대경로 (예: "papers/kosmos/kosmos.md", "_meta/autopilot-log.md").
        offset: 시작 줄 번호(1부터).
        limit: 읽을 줄 수.
    """
    try:
        p = vault_path(path)
    except VaultPathError as e:
        return f"❌ {e}"
    if not p.is_file():
        return f"❌ 파일 없음: {path}"
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return f"❌ 텍스트 파일이 아닙니다: {path}"
    start = max(offset, 1)
    chunk = lines[start - 1 : start - 1 + max(limit, 1)]
    body = "\n".join(f"{start + i:>6}\t{line[:2000]}" for i, line in enumerate(chunk))
    end = start + len(chunk) - 1
    if end < len(lines):
        body += f"\n({len(lines)}줄 중 {start}~{end}줄 — 이어 읽으려면 offset={end + 1})"
    return body


def write_file(path: str, content: str) -> str:
    """vault 안 파일을 통째로 쓴다(없으면 만든다). 일부만 고칠 때는 edit_file.

    Args:
        path: vault 상대경로.
        content: 파일 전체 내용.
    """
    p = _writable(path)
    if isinstance(p, str):
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"💾 저장: {_rel(p)} ({len(content.splitlines())}줄)"


def edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    """vault 안 파일에서 old_string을 정확히 찾아 new_string으로 바꾼다. 일치가 여럿이면 문맥을 늘리거나 replace_all.

    Args:
        path: vault 상대경로.
        old_string: 바꿀 원문(공백·줄바꿈까지 정확히).
        new_string: 새 내용.
        replace_all: 모든 일치를 바꿀지.
    """
    p = _writable(path)
    if isinstance(p, str):
        return p
    if not p.is_file():
        return f"❌ 파일 없음: {path}"
    text = p.read_text(encoding="utf-8")
    count = text.count(old_string) if old_string else 0
    if count == 0:
        return f"❌ old_string을 찾을 수 없습니다: {path}"
    if count > 1 and not replace_all:
        return f"❌ old_string이 {count}곳에 있습니다 — 앞뒤 문맥을 더 넣거나 replace_all=true: {path}"
    new = text.replace(old_string, new_string) if replace_all else text.replace(old_string, new_string, 1)
    p.write_text(new, encoding="utf-8")
    return f"✏️ 수정: {_rel(p)} ({count}곳)"


def _glob(pattern: str) -> list[str] | str:
    root = vault_root()
    base = root.resolve()
    found: set[str] = set()
    try:
        matches = list(root.glob(pattern))
    except (ValueError, NotImplementedError) as e:
        return f"❌ 패턴 오류: {e}"
    for p in matches:
        resolved = p.resolve()
        if not p.is_file() or base not in resolved.parents:
            continue
        rel = resolved.relative_to(base).as_posix()
        if not is_protected(rel):
            found.add(rel)
    return sorted(found)


def glob_files(pattern: str = "**/*.md", limit: int = 200) -> str:
    """vault 안에서 glob 패턴에 맞는 파일의 vault 상대경로를 찾는다.

    Args:
        pattern: glob 패턴 (예: "papers/*/*.md", "topics/*.md").
        limit: 최대 개수.
    """
    found = _glob(pattern)
    if isinstance(found, str):
        return found
    if not found:
        return "(일치 없음)"
    out = "\n".join(found[:limit])
    return out + (f"\n({len(found)}개 중 {limit}개)" if len(found) > limit else "")


def grep_files(pattern: str, glob: str = "**/*.md", ignore_case: bool = False, limit: int = 100) -> str:
    """vault 파일 내용에서 정규식을 찾아 `경로:줄: 내용`으로 돌려준다.

    Args:
        pattern: 정규식.
        glob: 찾을 파일 glob 패턴.
        ignore_case: 대소문자 무시.
        limit: 최대 일치 줄 수.
    """
    try:
        rx = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as e:
        return f"❌ 정규식 오류: {e}"
    found = _glob(glob)
    if isinstance(found, str):
        return found
    hits: list[str] = []
    root = vault_root()
    for rel in found:
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                hits.append(f"{rel}:{n}: {line.strip()[:_LINE_LIMIT]}")
                if len(hits) >= limit:
                    return "\n".join(hits) + f"\n(처음 {limit}건에서 멈춤)"
    return "\n".join(hits) or "(일치 없음)"


WORKSPACE_TOOLS = [read_file, write_file, edit_file, glob_files, grep_files]


# ---- 스냅샷·감사 로그 ----


class SnapshotStore:
    """쓰기 전 파일 내용을 보관했다가 되돌린다. 되돌리기용 최근 이력이지 백업이 아니다."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else state_dir() / "snapshots"

    def save(self, rel: str) -> str:
        path = vault_path(rel)
        sid = f"{datetime.now():%Y%m%dT%H%M%S}-{secrets.token_hex(3)}"
        folder = self.root / sid
        folder.mkdir(parents=True)
        existed = path.is_file()
        if existed:
            shutil.copy2(path, folder / "content")
        meta = {"path": rel, "vault": str(vault_root()), "existed": existed,
                "created": datetime.now().isoformat(timespec="seconds")}
        (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        return sid

    def _folder(self, sid: str) -> Path:
        if not _SID.match(sid or ""):
            raise ValueError(f"스냅샷 id 형식이 아니다: {sid!r}")
        folder = self.root / sid
        if not (folder / "meta.json").is_file():
            raise ValueError(f"스냅샷 없음: {sid}")
        return folder

    def meta(self, sid: str) -> dict:
        return json.loads((self._folder(sid) / "meta.json").read_text(encoding="utf-8"))

    def restore(self, sid: str) -> str:
        folder = self._folder(sid)
        meta = self.meta(sid)
        if meta["vault"] != str(vault_root()):
            raise ValueError(f"다른 vault의 스냅샷이다: {meta['vault']}")
        path = vault_path(meta["path"])
        if meta["existed"]:
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(folder / "content", path)
        elif path.is_file():
            path.unlink()
        return meta["path"]

    def discard(self, sid: str) -> None:
        shutil.rmtree(self._folder(sid), ignore_errors=True)


class AuditLog:
    """쓰기 계열 호출과 거부를 `key=value` 한 줄씩 남긴다."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else state_dir() / "audit.log"

    def write(self, **fields) -> None:
        parts = [f"ts={datetime.now().isoformat(timespec='seconds')}"]
        for key, value in fields.items():
            if isinstance(value, bool):
                value = str(value).lower()
            text = "-" if value is None or value == "" else str(value)
            text = re.sub(r"\s+", "_", text)[:160]
            parts.append(f"{key}={text}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(" ".join(parts) + "\n")


# ---- 대상 경로·미리보기 ----


def target_path(tool: str, args: dict) -> str | None:
    """호출이 쓰는 단일 파일의 vault 상대경로(스냅샷 대상). 없거나 여러 파일이면 None."""
    try:
        if tool in ("write_file", "edit_file"):
            return _rel(vault_path(args["path"]))
        if tool == "wiki_write_note":
            return _rel(_resolve_slug(args["slug"]))
        if tool == "wiki_link":
            return _rel(_resolve_slug(args["source"]))
        if tool == "build_citation_graph":
            anchor = args.get("anchor") or {}
            slug = args.get("slug") or anchor.get("arxiv_id") or "graph"
            return _rel(vault_path(f"graphs/{slug}.md"))
        if tool == "autopilot_config":
            return "_meta/autopilot.md"
    except (VaultPathError, KeyError, TypeError, AttributeError):
        return None
    return None


def _current(rel: str) -> str:
    path = vault_path(rel)
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _diff(rel: str, new: str) -> str:
    lines = difflib.unified_diff(
        _current(rel).splitlines(keepends=True), new.splitlines(keepends=True), fromfile=f"a/{rel}", tofile=f"b/{rel}", n=2
    )
    return ("".join(lines) or "(변경 없음)")[:_PREVIEW_LIMIT]


def _edit_preview(args: dict) -> str:
    rel, old, new = args.get("path", ""), args.get("old_string", ""), args.get("new_string", "")
    current = _current(rel)
    count = current.count(old) if old else 0
    if count == 0:
        return f"❌ old_string을 찾을 수 없습니다: {rel}"
    if count > 1 and not args.get("replace_all"):
        return f"❌ old_string이 {count}곳에 있습니다: {rel}"
    return _diff(rel, current.replace(old, new) if args.get("replace_all") else current.replace(old, new, 1))


def _note_content(args: dict) -> str:
    fm = args.get("frontmatter")
    if isinstance(fm, str):
        try:
            fm = json.loads(fm)
        except ValueError:
            fm = None
    return dump_note(fm if isinstance(fm, dict) else {}, args.get("body", ""))


def _prune_preview(tool: str, args: dict) -> str:
    from tools.pdf_tools import _build_keep_matcher, _keep_decision

    kind, prefix = ("figures", "fig") if tool == "prune_paper_figures" else ("tables", "table")
    slug = args.get("slug") or args.get("paper_id", "")
    folder = paper_dir(slug) / kind
    files = sorted(p.name for p in folder.glob("*.png")) if folder.is_dir() else []
    exact, numbers = _build_keep_matcher(list(args.get("keep") or []), prefix)
    remove = [f for f in files if not _keep_decision(f, prefix, exact, numbers)]
    kept = [f for f in files if f not in remove]
    return (f"papers/{slug}/{kind}/ — 유지: {', '.join(kept) or '(없음)'} · "
            f"삭제 {len(remove)}개: {', '.join(remove) or '(없음)'}")


def preview(tool: str, args: dict) -> str:
    """승인 카드에 보일 미리보기 — 쓰기는 diff, 삭제는 대상 목록, 비용 작업은 안내."""
    try:
        if tool == "write_file":
            return _diff(args.get("path", ""), args.get("content", ""))
        if tool == "edit_file":
            return _edit_preview(args)
        if tool == "wiki_write_note":
            return _diff(target_path(tool, args) or "", _note_content(args))
        if tool == "wiki_link":
            line = f"- [[{args.get('target', '')}]]" + (f" — {args['note']}" if args.get("note") else "")
            return f"{target_path(tool, args)} 끝에 한 줄 추가: {line}"
        if tool in ("prune_paper_figures", "prune_paper_tables"):
            return _prune_preview(tool, args)
        if tool == "autopilot_start":
            return (f"autopilot 실행 — scope={args.get('scope') or '(제어 노트 값)'} · "
                    f"max_papers={args.get('max_papers') or '(제어 노트 값)'}\n"
                    "모델 호출 비용 발생: 실측 편당 약 6만 토큰(요약·인용 판정). 멈추려면 autopilot_stop.")
        if tool == "autopilot_config":
            return f"_meta/autopilot.md에 기록 — scope={args.get('scope')!r} · max_papers={args.get('max_papers')}"
        if tool in ("extract_paper_figures", "extract_paper_tables"):
            return f"비전 모델 호출로 추출(비용 발생) → papers/{args.get('slug') or args.get('paper_id')}/"
    except (VaultPathError, OSError, ValueError) as e:
        return f"(미리보기를 만들지 못했다: {e})"
    return json.dumps(args, ensure_ascii=False, default=str)[:_PREVIEW_LIMIT]
