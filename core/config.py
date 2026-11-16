"""환경 상수.

- vault/PDF 경로는 [ADR-002](../docs/ADR.md#adr-002) — 프로젝트 외부 `~/Documents/research-wiki/`.
- CACHE_DIR은 프로젝트 내 `.cache/` (gitignore). 외부 API 응답 디스크 캐시 (Phase 3.0).
- SS_API_KEY는 Semantic Scholar API key (D-11). 설정 시 자동으로 `x-api-key` 헤더 첨부.
- VISION_MODEL은 figure/table bbox 추정 모델 `<provider>:<model>` (ADR-019, ADR-076).
  미설정이면 `google:<GEMINI_MODEL>` — GEMINI_MODEL 기본은 `gemini-2.5-pro`.
  provider별 키: google → GOOGLE_API_KEY, openrouter → OPENROUTER_API_KEY.
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
    for line in path.read_text(encoding="utf-8").splitlines():
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


def _env_path(name: str, default: Path) -> Path:
    """경로 env — 빈 문자열은 미설정으로 본다(`.env` 로더와 같은 규칙).

    플러그인 host가 `${user_config.vault_path}`를 ''로 넘기면 `Path("")` = cwd가 vault가 되던 문제.
    """
    return Path(os.environ.get(name) or default)


VAULT_PATH: Path = _env_path("OBSIDIAN_VAULT_PATH", _DEFAULT_VAULT)
PDF_PATH: Path = _env_path("PDF_PATH", VAULT_PATH / "pdfs")
CACHE_DIR: Path = default_cache_dir()
GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")
VISION_MODEL: str = os.environ.get("VISION_MODEL") or f"google:{GEMINI_MODEL}"
