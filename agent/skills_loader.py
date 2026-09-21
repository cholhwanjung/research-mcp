"""`.claude/skills/*/SKILL.md` → 스킬 목록 지침 + 스킬 로드 도구 (ADR-063 점진 로딩).

시스템 지침에는 name/description/trigger만 싣고, 본문(SKILL.md)과 같은 폴더의 다른 파일은
`load_skill`·`read_skill_file` 도구로 필요할 때 읽는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SKILLS_DIR = _PROJECT_ROOT / ".claude" / "skills"

_KEY = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):\s?(.*)$")


@dataclass
class Skill:
    name: str
    description: str = ""
    triggers: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    body: str = ""
    path: Path | None = None


def _parse_frontmatter(raw: str) -> dict:
    """관대한 frontmatter 파서.

    flat `key: value`와 `key:` 다음 `  - item` 리스트만 인식한다. strict YAML과 달리
    값에 콜론·따옴표·괄호가 섞인 산문(skill description/inputs)에도 깨지지 않는다.
    """
    meta: dict = {}
    cur_key: str | None = None
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if line[:1] in (" ", "\t") and stripped.startswith("- ") and cur_key:
            meta[cur_key].append(stripped[2:].strip().strip('"').strip("'"))
            continue
        m = _KEY.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val:
            meta[key] = val.strip('"').strip("'")
            cur_key = None
        else:
            meta[key] = []
            cur_key = key
    return meta


def _split_frontmatter(text: str) -> tuple[dict, str]:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return _parse_frontmatter(parts[1]), parts[2].strip()
    return {}, text.strip()


def load_skills(skills_dir: Path | str | None = None) -> list[Skill]:
    """`<skills_dir>/*/SKILL.md`를 읽어 Skill 목록 반환. 디렉토리 없으면 []."""
    base = Path(skills_dir) if skills_dir else DEFAULT_SKILLS_DIR
    if not base.is_dir():
        return []
    skills: list[Skill] = []
    for md in sorted(base.glob("*/SKILL.md")):
        meta, body = _split_frontmatter(md.read_text(encoding="utf-8"))
        skills.append(
            Skill(
                name=str(meta.get("name") or md.parent.name),
                description=str(meta.get("description") or ""),
                triggers=[str(t) for t in (meta.get("trigger") or [])],
                inputs=[str(i) for i in (meta.get("inputs") or [])],
                body=body,
                path=md.parent,
            )
        )
    return skills


def build_system_prompt(
    skills: list[Skill] | None = None,
    skills_dir: Path | str | None = None,
) -> str:
    """스킬 이름·설명·trigger 목록. 본문은 load_skill로 필요할 때 읽는다."""
    if skills is None:
        skills = load_skills(skills_dir)

    lines = [
        "# 워크플로우 (스킬)",
        "사용자 요청이 아래 스킬에 맞으면 먼저 load_skill(name)으로 절차를 읽고 따른다. 스킬 본문이 같은 폴더의 "
        "다른 파일을 가리키면 read_skill_file(name, path)로 읽는다. 맞는 스킬이 없으면 알맞은 도구를 직접 쓴다.",
        "",
    ]
    for s in skills:
        line = f"- {s.name} — {s.description}" if s.description else f"- {s.name}"
        if s.triggers:
            line += " (trigger: " + ", ".join(f'"{t}"' for t in s.triggers) + ")"
        lines.append(line)
    return "\n".join(lines).strip()


def make_skill_tools(skills_dir: Path | str | None = None) -> list:
    """모델에 줄 스킬 도구 두 개 — load_skill(name), read_skill_file(name, path)."""
    base = Path(skills_dir) if skills_dir else DEFAULT_SKILLS_DIR

    def _find(name: str) -> Skill | None:
        return next((s for s in load_skills(base) if s.name == name), None)

    def load_skill(name: str) -> str:
        """스킬 절차(SKILL.md 본문)를 읽는다. 요청이 스킬에 맞으면 먼저 부른다.

        Args:
            name: 스킬 이름 (지침의 워크플로우 목록에 있는 이름).
        """
        skill = _find(name)
        if skill is None:
            names = ", ".join(s.name for s in load_skills(base)) or "(없음)"
            return f"❌ 스킬 없음: {name} — 있는 스킬: {names}"
        return skill.body

    def read_skill_file(name: str, path: str) -> str:
        """스킬 폴더 안의 다른 파일(예: WORKER.md)을 읽는다.

        Args:
            name: 스킬 이름.
            path: 스킬 폴더 기준 상대경로.
        """
        skill = _find(name)
        if skill is None or skill.path is None:
            return f"❌ 스킬 없음: {name}"
        folder = skill.path.resolve()
        target = (skill.path / path).resolve()
        if folder not in target.parents:
            return f"❌ 스킬 폴더 밖 경로: {path}"
        if not target.is_file():
            return f"❌ 파일 없음: {name}/{path}"
        return target.read_text(encoding="utf-8")

    return [load_skill, read_skill_file]
