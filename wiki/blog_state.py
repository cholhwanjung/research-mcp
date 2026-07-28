"""tech-blog-digest의 seen URL 상태 — vault `_meta/blog_digest_state.json` (ADR-030).

`_meta/`는 vault 본문 격리 룰이 허용하는 시스템 영역. 포맷: `{url: first_seen_iso}`.
`config.VAULT_PATH`를 매 호출마다 참조 — 테스트에서 monkeypatch 가능.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from core import config


def _state_path() -> Path:
    return config.VAULT_PATH / "_meta" / "blog_digest_state.json"


def seen_urls() -> dict[str, str]:
    """{url: first_seen_iso}. 파일 없음/손상이면 빈 dict."""
    p = _state_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def mark_seen(urls: list[str]) -> int:
    """urls를 seen에 추가 (기존 항목의 timestamp는 보존). 신규 추가 수 반환."""
    seen = seen_urls()
    now = datetime.now(timezone.utc).isoformat()
    added = 0
    for u in urls:
        if u and u not in seen:
            seen[u] = now
            added += 1
    if added:
        p = _state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(seen, ensure_ascii=False, indent=1), encoding="utf-8")
    return added
