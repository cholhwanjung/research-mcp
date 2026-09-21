"""요청마다 사용량을 모으는 모델 래퍼 — 하위 에이전트(delegate)의 요청까지 한 곳에서 센다(ADR-065)."""

from __future__ import annotations

from contextlib import asynccontextmanager

from pydantic_ai.models.wrapper import WrapperModel

_KEYS = ("requests", "input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens")


class RecordingModel(WrapperModel):
    def __init__(self, wrapped):
        super().__init__(wrapped)
        self.reset()

    def reset(self) -> None:
        self._totals = dict.fromkeys(_KEYS, 0)

    def totals(self) -> dict[str, int]:
        return dict(self._totals)

    def _record(self, usage) -> None:
        self._totals["requests"] += 1
        for key in _KEYS[1:]:
            self._totals[key] += getattr(usage, key, 0) or 0

    async def request(self, messages, model_settings, model_request_parameters):
        response = await super().request(messages, model_settings, model_request_parameters)
        self._record(response.usage)
        return response

    @asynccontextmanager
    async def request_stream(self, *args, **kwargs):
        async with super().request_stream(*args, **kwargs) as stream:
            yield stream
        self._record(stream.usage)
