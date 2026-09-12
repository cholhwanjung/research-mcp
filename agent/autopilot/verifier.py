"""노트의 수치 주장을 원문 텍스트와 결정론으로 대조한다.

LLM 판정자를 두지 않고 입력(원문)을 직접 본다. 연도·한 자리 정수·arXiv ID처럼 흔해서
대조 의미가 없는 수는 건너뛴다. 원문에 없는 수치는 환각이거나 계산·반올림 결과다 —
판정은 사람 몫이고 여기선 목록만 만든다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 앞이 글자·숫자·점이 아니고 뒤가 숫자가 아닌 수: 1,500 · 42,000 · 79.4 · 85.2
_NUMBER = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?!\d)")
_ARXIV = re.compile(r"\b\d{4}\.\d{4,5}(?:v\d+)?\b")
_CONTEXT_CHARS = 30


@dataclass
class ClaimCheck:
    number: str
    context: str
    found: bool


def _normalize(number: str) -> str:
    return number.replace(",", "")


def _is_trivial(number: str) -> bool:
    if "." in number:
        return False
    value = int(number)
    return value < 10 or 1900 <= value <= 2099


def _blank_arxiv_ids(text: str) -> str:
    return _ARXIV.sub(lambda m: " " * len(m.group(0)), text)


def verify_numbers(note_text: str, source_text: str) -> list[ClaimCheck]:
    available = {_normalize(m.group(1)) for m in _NUMBER.finditer(_blank_arxiv_ids(source_text))}
    checks: list[ClaimCheck] = []
    seen: set[str] = set()
    for m in _NUMBER.finditer(_blank_arxiv_ids(note_text)):
        number = _normalize(m.group(1))
        if number in seen or _is_trivial(number):
            continue
        seen.add(number)
        start = max(0, m.start() - _CONTEXT_CHARS)
        end = min(len(note_text), m.end() + _CONTEXT_CHARS)
        checks.append(ClaimCheck(number, note_text[start:end].strip(), number in available))
    return checks


def unsupported(checks: list[ClaimCheck]) -> list[ClaimCheck]:
    return [c for c in checks if not c.found]
