"""`.claude/skills/*/SKILL.md` frontmatter + body → 에이전트 시스템 프롬프트.

각 skill의 name/description/trigger(라우팅 힌트) + body(tool 시퀀스)를 모아
에이전트가 사용자 요청을 어떤 워크플로우로 처리할지 안내한다.
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
            )
        )
    return skills


def build_system_prompt(
    skills: list[Skill] | None = None,
    skills_dir: Path | str | None = None,
) -> str:
    """skill 목록을 라우팅 힌트 + tool 시퀀스로 펼친 시스템 프롬프트."""
    if skills is None:
        skills = load_skills(skills_dir)

    lines = [
        "당신은 연구 논문 분석 에이전트입니다. arXiv / Semantic Scholar 도구와",
        "Obsidian vault 도구를 사용해 사용자의 연구 워크플로우를 수행합니다.",
        "사용자 요청이 아래 워크플로우의 trigger와 맞으면 해당 tool 시퀀스를 따르세요.",
        "맞는 워크플로우가 없으면 적절한 단일 도구(검색·조회 등)를 직접 사용하세요.",
        "",
        "# 워크플로우",
    ]
    for s in skills:
        lines.append(f"\n## {s.name}")
        if s.description:
            lines.append(s.description)
        if s.triggers:
            lines.append("trigger: " + ", ".join(f'"{t}"' for t in s.triggers))
        if s.inputs:
            lines.append("inputs: " + "; ".join(s.inputs))
        if s.body:
            lines.append("")
            lines.append(s.body)
    return "\n".join(lines).strip()
