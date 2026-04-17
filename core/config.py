"""환경 상수.

- vault/PDF 경로는 [ADR-002](../docs/ADR.md#adr-002) — 프로젝트 외부 `~/Documents/research-wiki/`.
- CACHE_DIR은 프로젝트 내 `.cache/` (gitignore). 외부 API 응답 디스크 캐시 (Phase 3.0).
- SS_API_KEY는 Semantic Scholar API key (D-11). 설정 시 자동으로 `x-api-key` 헤더 첨부.
- GOOGLE_API_KEY는 Gemini vision API 키 (ADR-019). figure/table bbox 추정에 필수.
- GEMINI_MODEL은 사용할 모델명 (기본 `gemini-2.5-pro`).
"""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_VAULT = Path(os.path.expanduser("~/Documents/research-wiki"))
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """프로젝트 root의 .env를 환경변수로 로드. 이미 set된 변수는 덮어쓰지 않음."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and v and not os.environ.get(k):
            os.environ[k] = v


_load_dotenv(_PROJECT_ROOT / ".env")

def default_cache_dir() -> Path:
    """CACHE_DIR의 기본 계산 — env 우선, 없으면 프로젝트 루트의 `.cache/`.

    런타임 함수로 노출해 테스트가 env를 비운 상태의 기본값을 검증할 수 있다.
    """
    return Path(os.environ.get("CACHE_DIR", _PROJECT_ROOT / ".cache"))


VAULT_PATH: Path = Path(os.environ.get("OBSIDIAN_VAULT_PATH", _DEFAULT_VAULT))
PDF_PATH: Path = Path(os.environ.get("PDF_PATH", VAULT_PATH / "pdfs"))
CACHE_DIR: Path = default_cache_dir()
GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")
