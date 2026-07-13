"""title-slug + arxiv_id 패턴 헬퍼 (ADR-016 vault 명명 규약).

설계:
- vault `papers/<slug>/` 의 slug는 사람·grep 친화적 title-slug로 한다 (ADR-016).
- arxiv_id는 frontmatter에 식별자로 보존. `is_arxiv_id`로 단순 식별자 입력이
  arxiv_id인지 title-slug인지 구별해 호출측이 적절히 처리.
"""

from __future__ import annotations

import re
import unicodedata

_MAX_SLUG_LEN = 80
_ARXIV_RE = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")


def is_arxiv_id(s: str) -> bool:
    """`s`가 arxiv_id 형식이면 True (예: '2301.12597', '2301.12597v2').

    True를 반환하는 입력은 vault slug로 사용되지 않고 frontmatter 식별자로 대접한다.
    """
    if not s:
        return False
    return bool(_ARXIV_RE.match(s.strip()))


def _normalize(text: str, max_len: int) -> str:
    """공통 정규화 파이프라인. 빈 결과면 빈 문자열 (fallback은 caller 몫).

    - 비ASCII 문자는 NFKD 정규화 후 ASCII로 변환 시도, 실패하면 원문 보존
      (한글 등은 NFKD로도 ASCII가 안 됨).
    - 소문자.
    - 어포스트로피·따옴표는 단어 안에서 drop ("what's" → "whats").
    - 영숫자가 아닌 모든 문자(공백·구두점·기타) → 하이픈. 연속 축약 + 좌우 트림.
    - `max_len`으로 truncate (파일시스템 길이·grep 친화).
    """
    normalized = unicodedata.normalize("NFKD", text)
    ascii_attempt = normalized.encode("ascii", "ignore").decode("ascii")
    base = ascii_attempt if ascii_attempt.strip() else text
    base = base.lower()
    base = re.sub(r"['’‘`\"]", "", base)
    base = re.sub(r"[^a-z0-9À-￿]+", "-", base)
    base = re.sub(r"-+", "-", base).strip("-")
    if len(base) > max_len:
        base = base[:max_len].rstrip("-")
    return base


def slugify_title(title: str) -> str:
    """논문 title → 사람·grep 친화 파일시스템 slug (최대 80자).

    콜론(`:`) 이전 부분만 사용 — 보통 짧은 약어/이름이 콜론 앞에 옴.
    예: "BLIP-2: Bootstrapping ..." → "blip-2". 빈 결과는 'untitled'.
    """
    if not title:
        return "untitled"
    head = title.split(":", 1)[0].strip() or title.strip()
    return _normalize(head, _MAX_SLUG_LEN) or "untitled"


_MAX_CAPTION_LEN = 60


def slugify_caption(caption: str, max_len: int = _MAX_CAPTION_LEN) -> str:
    """figure/table caption → 파일명 친화 슬러그.

    `slugify_title`과 다른 점:
    - 콜론 이전 단축을 하지 않음 (caption은 일반 문장이라 subtitle 개념 없음).
    - 기본 최대 길이가 더 짧음 (60자 — 파일명에 fig_N_ 접두 + 확장자가 추가됨).
    - 빈 입력·빈 결과는 빈 문자열 반환 (caller가 'fig_<N>' 같은 fallback 결정).
    """
    if not caption or not caption.strip():
        return ""
    return _normalize(caption.strip(), max_len)
