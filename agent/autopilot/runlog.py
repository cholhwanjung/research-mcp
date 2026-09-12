"""`_meta/autopilot-log.md` 헤더 파싱·기록. 문법은 스킬 모드와 같다.

한 반복 = `start` 헤더 + 결과 헤더 + `key=value` 줄들 + 빈 줄. 결과 없는 `start`가
마지막이면 끊긴 반복이다 — seed `refill` 헤더는 반복 결과가 아니라 닫지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_HEADER = re.compile(r"^## \[(?P<ts>[^\]]+)\] autopilot \| (?P<rest>.*)$")
_NOT_A_RESULT = {"refill"}


@dataclass
class Header:
    ts: str
    iter: int
    action: str
    fields: dict[str, str] = field(default_factory=dict)


def parse_headers(text: str) -> list[Header]:
    headers: list[Header] = []
    for line in text.splitlines():
        m = _HEADER.match(line)
        if not m:
            continue
        kv: dict[str, str] = {}
        for part in m.group("rest").split(" | "):
            if "=" in part:
                k, v = part.split("=", 1)
                kv[k.strip()] = v.strip()
        try:
            it = int(kv.pop("iter"))
        except (KeyError, ValueError):
            continue
        headers.append(Header(m.group("ts"), it, kv.pop("action", ""), kv))
    return headers


def open_start(headers: list[Header]) -> Header | None:
    """마지막 반복이 결과 없이 끝났으면 그 `start` 헤더."""
    for h in reversed(headers):
        if h.action in _NOT_A_RESULT:
            continue
        return h if h.action == "start" else None
    return None


def last_iter(headers: list[Header]) -> int:
    return max((h.iter for h in headers), default=0)


def next_iter(headers: list[Header]) -> int:
    return last_iter(headers) + 1


def format_header(ts: str, iter: int, action: str, **fields: object) -> str:
    parts = [f"## [{ts}] autopilot", f"iter={iter}", f"action={action}"]
    parts.extend(f"{k}={v}" for k, v in fields.items())
    return " | ".join(parts)


def format_kv(values: dict[str, object]) -> str:
    """`key=value` 한 줄. 빈 값은 `-`, 공백·따옴표가 있으면 큰따옴표로 감싼다."""
    out: list[str] = []
    for k, v in values.items():
        s = "" if v is None else str(v)
        if not s:
            s = "-"
        elif " " in s or '"' in s:
            s = '"' + s.replace('"', "'") + '"'
        out.append(f"{k}={s}")
    return " ".join(out)


def append_entry(path: Path, header: str, lines: list[str] | None = None) -> None:
    """헤더 한 줄(+ 결과면 key=value 줄들과 빈 줄)을 append."""
    path.parent.mkdir(parents=True, exist_ok=True)
    chunk = header + "\n"
    if lines:
        chunk += "\n".join(lines) + "\n\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(chunk)


def read_tail_headers(path: Path, n: int = 3) -> list[Header]:
    if not path.is_file():
        return []
    return parse_headers(path.read_text(encoding="utf-8"))[-n:]
