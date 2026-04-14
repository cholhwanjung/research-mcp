"""환경 상수.

- vault/PDF 경로는 [ADR-002](../docs/ADR.md#adr-002) — 프로젝트 외부 `~/Documents/research-wiki/`.
- CACHE_DIR은 프로젝트 내 `.cache/` (gitignore). 외부 API 응답 디스크 캐시 (Phase 3.0).
- SS_API_KEY는 Semantic Scholar API key (D-11). 설정 시 자동으로 `x-api-key` 헤더 첨부.
"""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_VAULT = Path(os.path.expanduser("~/Documents/research-wiki"))
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

def default_cache_dir() -> Path:
    """CACHE_DIR의 기본 계산 — env 우선, 없으면 프로젝트 루트의 `.cache/`.

    런타임 함수로 노출해 테스트가 env를 비운 상태의 기본값을 검증할 수 있다.
    """
    return Path(os.environ.get("CACHE_DIR", _PROJECT_ROOT / ".cache"))


VAULT_PATH: Path = Path(os.environ.get("OBSIDIAN_VAULT_PATH", _DEFAULT_VAULT))
PDF_PATH: Path = Path(os.environ.get("PDF_PATH", VAULT_PATH / "pdfs"))
CACHE_DIR: Path = default_cache_dir()
