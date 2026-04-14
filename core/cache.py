"""디스크 캐시. `config.CACHE_DIR` 아래 JSON 파일로 저장 (Phase 3.0).

런타임 참조 패턴: `config.CACHE_DIR`을 매 호출마다 읽어 monkeypatch 가능.
SS API rate-limit (HTTP 429) 직격을 막기 위해 도입 — 같은 key는 두 번째부터 디스크 hit.

설계:
- key는 SHA-256 해시 → 파일명. 충돌·경로 안전·길이 일정.
- payload는 JSON 직렬화. dict/list/str/int/None 지원 (외부 API JSON 응답 대상).
- TTL은 mtime 기반. `None`이면 무한.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Awaitable, Callable

from core import config


def _key_to_path(key: str):
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return config.CACHE_DIR / f"{digest}.json"


def _is_fresh(path, ttl: int | None) -> bool:
    if ttl is None:
        return True
    age = time.time() - path.stat().st_mtime
    return age < ttl


async def get_or_fetch(
    key: str,
    fetcher: Callable[[], Awaitable[Any]],
    ttl: int | None = None,
    force_refresh: bool = False,
) -> Any:
    """`key`로 디스크 캐시 조회. miss 또는 force_refresh면 `fetcher()` 호출 후 저장.

    Args:
        key:           캐시 식별자 (URL+params 등을 호출측에서 합성).
        fetcher:       miss 시 호출할 async 함수. 반환값은 JSON 직렬화 가능해야 함.
        ttl:           초 단위 만료. None이면 무한.
        force_refresh: True면 디스크 무시 + fetcher 호출 + 덮어쓰기.
    """
    path = _key_to_path(key)
    if not force_refresh and path.is_file() and _is_fresh(path, ttl):
        return json.loads(path.read_text(encoding="utf-8"))

    value = await fetcher()
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return value
