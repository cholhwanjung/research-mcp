"""Vision model로 figure/table bounding box 추정 (ADR-019, provider 분리는 ADR-076).

모델은 `VISION_MODEL=<provider>:<model>` 하나로 고른다 (core.config.VISION_MODEL).
- `openrouter:qwen/qwen3-vl-235b-a22b-instruct` (기본, ADR-077) — OpenAI 호환 chat completions, 키 `OPENROUTER_API_KEY`.
- `google:gemini-3.8-flash` — google-genai SDK, 키 `GOOGLE_API_KEY`.

provider 추가 = `_call_<name>(model, page_png, prompt) -> str` 함수 하나 + `_PROVIDERS` 한 줄.

설계:
- `_build_prompt(caption, kind, order)` — 0-1000 정규화 좌표를 provider의 순서로 요구.
- `_parse_to_bbox(text)` — JSON 응답 파싱. `found=false` 또는 형식 오류면 None.
- `_to_pt(bbox_1000, page_w, page_h, order)` — 정규화 좌표 → PDF pt 단위.
- `estimate_bbox(page_png, caption, page_w, page_h, kind)` — 최상위 호출.
  1회 retry 후 실패하면 None. 선택한 provider의 키가 없으면 RuntimeError.

좌표 순서(`order`)는 provider마다 다르다 — 모델은 선호하지 않는 순서를 요구받아도
선호 순서로 답하는 경우가 있어, prompt와 변환이 같은 순서를 써야 한다.
"""

from __future__ import annotations

import base64
import json
import os
import re
from functools import lru_cache

import httpx

from core import config

_BBOX_RETRY = 1
_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_OPENROUTER_TIMEOUT_S = 120

# 좌표 순서 → prompt에 적는 표기
_ORDERS = {
    "yxyx": "[ymin, xmin, ymax, xmax]",
    "xyxy": "[xmin, ymin, xmax, ymax]",
}


def _build_prompt(caption: str, kind: str, order: str = "yxyx") -> str:
    """0-1000 정규화 bbox prompt. `order`는 좌표 순서 (기본은 Gemini 관례 yxyx)."""
    coords = _ORDERS[order]
    if kind == "table":
        body_note = (
            "bounding box는 **table 본체(행/열 구조) + 해당 caption 줄까지** 포함하는 영역.\n"
            "caption은 학술지에 따라 table 위쪽 또는 아래쪽에 위치 — 어느 쪽이든 포함.\n"
            "인접 본문 텍스트는 제외."
        )
    else:
        body_note = (
            "bounding box는 **figure 본체(diagram/plot/image) + 해당 caption 줄까지**\n"
            "포함하는 영역. caption은 보통 figure 아래쪽. 인접 본문은 제외."
        )
    return (
        "이 이미지는 학술 논문 PDF의 한 페이지를 raster로 렌더한 것입니다.\n\n"
        f"다음 caption을 가진 {kind}을 페이지에서 찾고, 그 bounding box를 출력하세요:\n\n"
        f'"{caption}"\n\n'
        f"{body_note}\n\n"
        "JSON으로만 응답 (다른 텍스트 없이):\n"
        f'{{"found": true, "bbox_2d": {coords}, "confidence": "high|medium|low", "notes": "단서"}}\n\n'
        "bbox_2d 좌표 규약:\n"
        f"- 순서: {coords}\n"
        "- 모든 값은 페이지 크기에 정규화된 **0-1000 정수**.\n"
        "- (0, 0)은 좌상단, (1000, 1000)은 우하단.\n"
        "- 페이지에 해당 요소가 보이면 반드시 found=true + 좌표를 출력하세요."
    )


def _parse_to_bbox(text: str) -> list[int] | None:
    """JSON 응답 → 정규화 좌표 4개 (순서는 prompt에서 요구한 그대로). 실패 시 None."""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not data.get("found"):
        return None
    bb = data.get("bbox_2d") or data.get("bbox")
    if not bb or len(bb) != 4:
        return None
    try:
        return [int(round(float(v))) for v in bb]
    except (TypeError, ValueError):
        return None


def _to_pt(
    bbox_1000: list[int], page_w: float, page_h: float, order: str = "yxyx"
) -> tuple[float, float, float, float]:
    """정규화 좌표 × 1000 (`order` 순서) → PDF pt (x1, y1, x2, y2)."""
    if order == "xyxy":
        xmin, ymin, xmax, ymax = bbox_1000
    else:
        ymin, xmin, ymax, xmax = bbox_1000
    return (
        float(xmin) / 1000 * page_w,
        float(ymin) / 1000 * page_h,
        float(xmax) / 1000 * page_w,
        float(ymax) / 1000 * page_h,
    )


@lru_cache(maxsize=1)
def _get_client():
    """google-genai Client. `GOOGLE_API_KEY`를 env에서 읽는다."""
    from google import genai
    return genai.Client()


def _call_google(model: str, page_png: bytes, prompt: str) -> str:
    from google.genai import types

    response = _get_client().models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(data=page_png, mime_type="image/png"),
            prompt,
        ],
    )
    return response.text or ""


def _call_openrouter(model: str, page_png: bytes, prompt: str) -> str:
    """OpenAI 호환 chat completions. PNG는 base64 data URL로 싣는다."""
    image_url = "data:image/png;base64," + base64.b64encode(page_png).decode()
    response = httpx.post(
        _OPENROUTER_URL,
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
        json={
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_url}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        },
        timeout=_OPENROUTER_TIMEOUT_S,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"] or ""


# provider → (API 키 env, 좌표 순서, 호출 함수)
_PROVIDERS = {
    "google": ("GOOGLE_API_KEY", "yxyx", _call_google),
    "openrouter": ("OPENROUTER_API_KEY", "xyxy", _call_openrouter),
}


def _split_model(spec: str) -> tuple[str, str]:
    """`<provider>:<model>` → (provider, model). 모델 ID 안의 콜론은 보존."""
    provider, _, model = spec.partition(":")
    if provider not in _PROVIDERS or not model:
        raise ValueError(
            f"VISION_MODEL은 '<provider>:<model>' 형식이어야 합니다 "
            f"(provider: {', '.join(_PROVIDERS)}). 받은 값: {spec!r}"
        )
    return provider, model


def estimate_bbox(
    page_png: bytes,
    caption: str,
    page_w: float,
    page_h: float,
    kind: str = "figure",
) -> tuple[float, float, float, float] | None:
    """`VISION_MODEL`로 bbox 추정 → PDF pt (x1, y1, x2, y2). not_found / 실패 시 None.

    1회 retry까지 시도.
    """
    provider, model = _split_model(config.VISION_MODEL)
    key_env, order, call = _PROVIDERS[provider]
    if not os.environ.get(key_env):
        raise RuntimeError(
            f"{key_env} 환경변수가 비어 있습니다. "
            f"VISION_MODEL={config.VISION_MODEL}의 figure/table bbox 추정에 필요합니다. "
            ".env 또는 export로 설정하세요."
        )
    prompt = _build_prompt(caption, kind, order)
    for _ in range(1 + _BBOX_RETRY):
        try:
            text = call(model, page_png, prompt)
        except Exception:
            continue
        bb_norm = _parse_to_bbox(text.strip())
        if bb_norm is not None:
            return _to_pt(bb_norm, page_w, page_h, order)
    return None
