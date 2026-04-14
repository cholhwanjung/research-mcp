"""HTTP GET helper. SS API key 자동 첨부 + 429 지수 백오프 (Phase 3.0, D-11).

- `SS_API_KEY` env가 설정되어 있고 호스트가 Semantic Scholar면 `x-api-key` 헤더 자동 첨부.
- 429 응답이면 `RETRY_DELAYS` (1→2→4초) 간격으로 재시도.
- 4번 모두 429면 마지막 응답(텍스트)을 그대로 반환 — 호출측에서 빈 응답으로 처리.
"""

from __future__ import annotations

import asyncio
import os
from urllib.parse import urlparse

import aiohttp

RETRY_DELAYS: tuple[float, ...] = (1.0, 2.0, 4.0)
_SS_HOST = "api.semanticscholar.org"
_USER_AGENT = "research-mcp/0.1 (+https://github.com/anthropics/research-mcp)"


def _default_headers(url: str) -> dict[str, str]:
    """모든 호출에 User-Agent 첨부 + SS API면 SS_API_KEY env를 `x-api-key`로 첨부.

    - User-Agent: 일부 RSS/HTML 서비스가 default Python UA를 403 차단 (news.hada.io 등).
    - D-11: API key는 SS 호출에만 첨부. 다른 호스트는 영향 없음.
    """
    headers: dict[str, str] = {"User-Agent": _USER_AGENT}
    key = os.environ.get("SS_API_KEY")
    if key:
        host = urlparse(url).netloc.lower()
        if host == _SS_HOST:
            headers["x-api-key"] = key
    return headers


async def get(url: str, params: dict | None = None, timeout: int = 30) -> dict | str:
    """단순 async GET. 429면 RETRY_DELAYS만큼 재시도, 마지막엔 텍스트 본문 반환."""
    headers = _default_headers(url)
    last_body: dict | str = ""
    async with aiohttp.ClientSession() as session:
        for attempt in range(len(RETRY_DELAYS) + 1):  # 최초 1 + 재시도 N
            async with session.get(
                url,
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status == 429 and attempt < len(RETRY_DELAYS):
                    await asyncio.sleep(RETRY_DELAYS[attempt])
                    continue
                if resp.content_type == "application/json":
                    last_body = await resp.json()
                else:
                    last_body = await resp.text()
                return last_body
    return last_body
