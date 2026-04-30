"""ADR-021: 검색/refs/cites/daily 결과에서 survey 논문 자동 제외.

word boundary로 `survey` 단어 매칭만 drop — `SurveyNet`, `Surveying` 같은
다른 단어는 보존. case-insensitive.
"""

from __future__ import annotations

import re

_SURVEY_RE = re.compile(r"\bsurvey\b", re.IGNORECASE)


def is_survey(title: str | None) -> bool:
    """title에 단어 `survey`가 포함되면 True. None / 빈 문자열은 False."""
    if not title:
        return False
    return bool(_SURVEY_RE.search(title))


def drop_surveys(papers: list[dict]) -> list[dict]:
    """is_survey(p['title'])가 True인 entry를 제거한 새 list 반환.

    title 키가 없거나 None이면 보존 (필터 책임 밖 — 호출자가 정규화).
    """
    return [p for p in papers if not is_survey(p.get("title"))]
