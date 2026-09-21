"""공개 단가로 비용을 계산한다(USD/MTok, 2026-09-12 확인) — ADR-065.

- Anthropic: platform.claude.com/docs/en/about-claude/pricing (5분·1시간 캐시 쓰기 구분).
- OpenAI gpt-5·Google gemini-2.5-pro: genai-prices 표(gemini는 20만 토큰 이하 구간).
입력 토큰은 캐시 읽기·쓰기를 포함한 전체로 받고, 캐시가 아닌 부분만 기본 단가로 친다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    input: float
    cache_read: float
    cache_write: float  # 5분 캐시 쓰기
    output: float
    cache_write_1h: float | None = None  # 없으면 입력 단가의 2배


PRICES: dict[str, Price] = {
    "claude-opus-5": Price(5.0, 0.50, 6.25, 25.0, 10.0),
    "claude-sonnet-5": Price(2.0, 0.20, 2.50, 10.0, 4.0),
    "claude-haiku-4-5": Price(1.0, 0.10, 1.25, 5.0, 2.0),
    "gpt-5": Price(1.25, 0.125, 1.25, 10.0),
    "gemini-2.5-pro": Price(1.25, 0.125, 1.25, 10.0),
}
_DATE_SUFFIX = re.compile(r"-\d{8}$")


def price_for(model: str) -> Price | None:
    return PRICES.get(_DATE_SUFFIX.sub("", model.split(":", 1)[-1]))


def cost_usd(model: str, *, input_tokens: int, cache_read_tokens: int = 0, cache_write_tokens: int = 0,
             cache_write_1h_tokens: int = 0, output_tokens: int = 0) -> float | None:
    price = price_for(model)
    if price is None:
        return None
    write_1h = price.cache_write_1h if price.cache_write_1h is not None else 2 * price.input
    uncached = max(input_tokens - cache_read_tokens - cache_write_tokens - cache_write_1h_tokens, 0)
    return (uncached * price.input + cache_read_tokens * price.cache_read + cache_write_tokens * price.cache_write
            + cache_write_1h_tokens * write_1h + output_tokens * price.output) / 1_000_000
