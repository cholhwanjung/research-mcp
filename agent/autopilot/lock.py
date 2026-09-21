"""한 vault에 루프 하나 — pid를 적은 잠금 파일.

두 루프가 같은 vault를 돌면 같은 후보를 집어 노트·제어 노트를 서로 덮어쓴다. 잠금 파일의 pid가
살아 있으면 두 번째 실행을 막고, 죽은 pid면 끊긴 실행의 잔재라 넘겨받는다.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class LockHeld(RuntimeError):
    def __init__(self, pid: int):
        super().__init__(f"이미 실행 중 (pid {pid})")
        self.pid = pid


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def holder(path: Path) -> int | None:
    """잠금을 쥔 살아 있는 pid. 없거나 죽었으면 None."""
    pid = _read_pid(path)
    return pid if pid is not None and _alive(pid) else None


def acquire(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            pid = holder(path)
            if pid is not None:
                raise LockHeld(pid)
            path.unlink(missing_ok=True)
            continue
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        return
    raise LockHeld(_read_pid(path) or -1)


def release(path: Path) -> None:
    if _read_pid(path) == os.getpid():
        path.unlink(missing_ok=True)


@contextmanager
def run_lock(path: Path) -> Iterator[None]:
    acquire(path)
    try:
        yield
    finally:
        release(path)
