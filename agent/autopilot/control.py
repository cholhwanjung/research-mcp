"""research-autopilot 제어 노트(`_meta/autopilot.md`)를 코드로 읽고 쓴다.

본문은 `## 절` 단위로 나누고 절 안의 `- ` 줄만 항목으로 본다. 설명 줄·빈 줄은
원문 그대로 되돌려 사용자가 Obsidian에서 편집한 내용을 보존한다. 저장할 때는
`merge_changes`로 디스크 최신본에 이번 반복이 바꾼 것만 얹는다 — 반복 도중 사용자가 적은
정지 요청·항목을 덮어쓰지 않는다.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

import yaml

from core.slug import is_arxiv_id

_ITEM_SEP = " — "
_ARXIV_IN_TEXT = re.compile(r"(?<![\d.])(\d{4}\.\d{4,5})(?:v\d+)?(?![\d.])")
_VERSION = re.compile(r"v\d+$")
# 정지 시 비우는 실행 단위 필드. max_papers·min_velocity·explore 등은 유지.
_RUN_RESET = {
    "stop": True,
    "scope": [],
    "scope_input": "",
    "run_started": "",
    "processed": 0,
    "consecutive_failures": 0,
    "topics_added": 0,
}


class ControlParseError(ValueError):
    """frontmatter가 없거나 YAML로 읽히지 않는 제어 노트."""


def item_key(item: str) -> str:
    """항목 줄에서 식별 부분(` — ` 앞). 구분자가 없으면 줄 전체."""
    return item.strip().split(_ITEM_SEP, 1)[0].strip()


def item_arxiv_id(item: str) -> str | None:
    """식별 부분에 든 arXiv ID(버전 제외). 제목만 적힌 항목이면 None."""
    m = _ARXIV_IN_TEXT.search(item_key(item))
    return m.group(1) if m else None


@dataclass
class Section:
    name: str
    lines: list[str] = field(default_factory=list)


@dataclass
class ControlNote:
    frontmatter: dict
    head: list[str]
    sections: list[Section]

    def section_names(self) -> list[str]:
        return [s.name for s in self.sections]

    def _section(self, name: str) -> Section | None:
        return next((s for s in self.sections if s.name == name), None)

    def items(self, name: str) -> list[str]:
        section = self._section(name)
        if section is None:
            return []
        return [line[2:].strip() for line in section.lines if line.startswith("- ")]

    def remove_item(self, name: str, key: str) -> bool:
        """식별 부분이 key와 같거나 arXiv ID가 key인 첫 항목을 지운다."""
        section = self._section(name)
        if section is None:
            return False
        wanted = key.strip()
        wanted_id = _VERSION.sub("", wanted) if is_arxiv_id(wanted) else None
        for i, line in enumerate(section.lines):
            if not line.startswith("- "):
                continue
            item = line[2:]
            if item_key(item) == wanted or (wanted_id and item_arxiv_id(item) == wanted_id):
                del section.lines[i]
                return True
        return False

    def replace_item(self, name: str, old: str, new: str) -> bool:
        """본문이 old와 같은 항목 줄을 제자리에서 new로 바꾼다."""
        section = self._section(name)
        if section is None:
            return False
        for i, line in enumerate(section.lines):
            if line.startswith("- ") and line[2:].strip() == old.strip():
                section.lines[i] = f"- {new}"
                return True
        return False

    def remove_exact(self, name: str, text: str) -> bool:
        section = self._section(name)
        if section is None:
            return False
        for i, line in enumerate(section.lines):
            if line.startswith("- ") and line[2:].strip() == text.strip():
                del section.lines[i]
                return True
        return False

    def add_item(self, name: str, text: str) -> None:
        """마지막 항목 뒤(항목이 없으면 설명 줄 뒤)에 붙인다. 절이 없으면 끝에 만든다."""
        section = self._section(name)
        if section is None:
            if self.sections and self.sections[-1].lines[-1:] != [""]:
                self.sections[-1].lines.append("")
            self.sections.append(Section(name, [f"- {text}", ""]))
            return
        bullets = [i for i, line in enumerate(section.lines) if line.startswith("- ")]
        if bullets:
            at = bullets[-1] + 1
        else:
            filled = [i for i, line in enumerate(section.lines) if line.strip()]
            at = filled[-1] + 1 if filled else 0
        section.lines.insert(at, f"- {text}")

    def reset_on_stop(self) -> None:
        self.frontmatter.update(_RUN_RESET)


def parse_control(text: str) -> ControlNote:
    if not text.startswith("---\n"):
        raise ControlParseError("frontmatter가 없다")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ControlParseError("frontmatter 닫는 구분자가 없다")
    try:
        fm = yaml.safe_load(text[4 : end + 1]) or {}
    except yaml.YAMLError as e:
        raise ControlParseError(f"frontmatter YAML 오류: {e}") from e
    if not isinstance(fm, dict):
        raise ControlParseError("frontmatter가 매핑이 아니다")

    head: list[str] = []
    sections: list[Section] = []
    for line in text[end + 5 :].split("\n"):
        if line.startswith("## "):
            sections.append(Section(line[3:].strip()))
        elif sections:
            sections[-1].lines.append(line)
        else:
            head.append(line)
    return ControlNote(fm, head, sections)


def render_control(note: ControlNote) -> str:
    body: list[str] = list(note.head)
    for section in note.sections:
        body.append(f"## {section.name}")
        body.extend(section.lines)
    yaml_block = yaml.safe_dump(note.frontmatter, allow_unicode=True, sort_keys=False)
    return "---\n" + yaml_block + "---\n" + "\n".join(body)


@dataclass
class ControlSnapshot:
    frontmatter: dict
    items: dict[str, list[str]]


def snapshot(note: ControlNote) -> ControlSnapshot:
    return ControlSnapshot(copy.deepcopy(note.frontmatter), {s.name: note.items(s.name) for s in note.sections})


def _minus(items: list[str], other: list[str]) -> list[str]:
    pool = list(other)
    out: list[str] = []
    for item in items:
        if item in pool:
            pool.remove(item)
        else:
            out.append(item)
    return out


def merge_changes(fresh: ControlNote, before: ControlSnapshot, after: ControlNote) -> ControlNote:
    """before → after 사이의 변경만 fresh(디스크 최신본)에 얹어 돌려준다.

    frontmatter는 값이 바뀐 키만, 절은 지운 줄·더한 줄만 반영한다. 같은 식별 부분의 줄을 지우고
    더했으면 제자리 교체로 보고, 그 사이 사용자가 원래 줄을 지웠으면 되살리지 않는다.
    """
    for key, value in after.frontmatter.items():
        if key not in before.frontmatter or before.frontmatter[key] != value:
            fresh.frontmatter[key] = copy.deepcopy(value)
    for name in after.section_names():
        old_items = before.items.get(name, [])
        new_items = after.items(name)
        added = _minus(new_items, old_items)
        for removed in _minus(old_items, new_items):
            match = next((a for a in added if item_key(a) == item_key(removed)), None)
            if match is None:
                fresh.remove_exact(name, removed)
                continue
            added.remove(match)
            fresh.replace_item(name, removed, match)
        for item in added:
            fresh.add_item(name, item)
    return fresh
