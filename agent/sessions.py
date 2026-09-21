"""대화 세션 저장소. W-1은 in-memory; W-2에서 SqliteSessionStore로 확장.

history는 Pydantic-AI의 message 목록(ModelMessage)을 그대로 보관한다 — 다음
턴에 `agent.run(..., message_history=store.get_history(sid))`로 넘긴다.
grants는 사용자가 '이 세션 동안 허용'한 도구 이름이다(ADR-063). clear는 history만 지운다.
"""

from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Iterable


class SessionStore(ABC):
    @abstractmethod
    def get_history(self, session_id: str) -> list[Any]:
        ...

    @abstractmethod
    def append(self, session_id: str, messages: list[Any]) -> None:
        ...

    @abstractmethod
    def clear(self, session_id: str) -> None:
        ...

    @abstractmethod
    def get_grants(self, session_id: str) -> set[str]:
        ...

    @abstractmethod
    def add_grants(self, session_id: str, tools: Iterable[str]) -> None:
        ...


class InMemorySessionStore(SessionStore):
    def __init__(self) -> None:
        self._store: dict[str, list[Any]] = {}
        self._grants: dict[str, set[str]] = {}

    def get_history(self, session_id: str) -> list[Any]:
        return list(self._store.get(session_id, []))

    def append(self, session_id: str, messages: list[Any]) -> None:
        self._store.setdefault(session_id, []).extend(messages)

    def clear(self, session_id: str) -> None:
        self._store.pop(session_id, None)

    def get_grants(self, session_id: str) -> set[str]:
        return set(self._grants.get(session_id, set()))

    def add_grants(self, session_id: str, tools: Iterable[str]) -> None:
        self._grants.setdefault(session_id, set()).update(tools)


class SqliteSessionStore(SessionStore):
    """stdlib sqlite3 기반 영속 세션. message 목록은 pydantic-ai TypeAdapter로 JSON 직렬화."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS messages "
                "(session_id TEXT, seq INTEGER, data BLOB)"
            )
            c.execute("CREATE TABLE IF NOT EXISTS grants (session_id TEXT, tool TEXT, UNIQUE(session_id, tool))")

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def get_history(self, session_id: str) -> list[Any]:
        from pydantic_ai.messages import ModelMessagesTypeAdapter

        with self._conn() as c:
            rows = c.execute(
                "SELECT data FROM messages WHERE session_id=? ORDER BY seq",
                (session_id,),
            ).fetchall()
        history: list[Any] = []
        for (blob,) in rows:
            history.extend(ModelMessagesTypeAdapter.validate_json(blob))
        return history

    def append(self, session_id: str, messages: list[Any]) -> None:
        if not messages:
            return
        from pydantic_ai.messages import ModelMessagesTypeAdapter

        blob = ModelMessagesTypeAdapter.dump_json(messages)
        with self._conn() as c:
            (max_seq,) = c.execute(
                "SELECT COALESCE(MAX(seq), -1) FROM messages WHERE session_id=?",
                (session_id,),
            ).fetchone()
            c.execute(
                "INSERT INTO messages VALUES (?, ?, ?)",
                (session_id, max_seq + 1, blob),
            )

    def clear(self, session_id: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM messages WHERE session_id=?", (session_id,))

    def get_grants(self, session_id: str) -> set[str]:
        with self._conn() as c:
            rows = c.execute("SELECT tool FROM grants WHERE session_id=?", (session_id,)).fetchall()
        return {tool for (tool,) in rows}

    def add_grants(self, session_id: str, tools: Iterable[str]) -> None:
        with self._conn() as c:
            c.executemany("INSERT OR IGNORE INTO grants VALUES (?, ?)", [(session_id, t) for t in set(tools)])
