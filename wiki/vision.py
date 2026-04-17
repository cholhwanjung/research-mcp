"""Gemini Vision으로 figure/table bounding box 추정 (ADR-019).

ADR-018 휴리스틱(column-aware + caption_y_reach)을 vision model로 대체.
BLIP-2 운영 검증: figure 5/5, table 9/9 케이스 모두에서 휴리스틱 < Gemini.

설계:
- `_build_prompt(caption, kind)` — Google Gemini spatial 관례
  (0-1000 정규화, [ymin, xmin, ymax, xmax]) 명시.
- `_parse_to_bbox(text)` — JSON 응답 파싱. `found=false` 또는 형식 오류면 None.
- `_to_pt(bbox_1000, page_w, page_h)` — 정규화 좌표 → PDF pt 단위.
- `estimate_bbox(page_png, caption, page_w, page_h, kind)` — 최상위 호출.
  1회 retry 후 실패하면 None.

환경변수:
- `GOOGLE_API_KEY` — 필수. 없으면 RuntimeError.
- `GEMINI_MODEL` — 모델명, 기본 `gemini-2.5-pro` (core.config.GEMINI_MODEL).
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache

from core import config

_BBOX_RETRY = 1


def _build_prompt(caption: str, kind: str) -> str:
    """Google Gemini spatial 관례 prompt — 0-1000 정규화 [ymin, xmin, ymax, xmax]."""
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
        '{"found": true, "bbox_2d": [ymin, xmin, ymax, xmax], "confidence": "high|medium|low", "notes": "단서"}\n\n'
        "bbox_2d 좌표 규약:\n"
        "- 순서: [ymin, xmin, ymax, xmax]\n"
        "- 모든 값은 페이지 크기에 정규화된 **0-1000 정수**.\n"
        "- (0, 0)은 좌상단, (1000, 1000)은 우하단.\n"
        "- 페이지에 해당 요소가 보이면 반드시 found=true + 좌표를 출력하세요."
    )


def _parse_to_bbox(text: str) -> list[int] | None:
    """JSON 응답 → [ymin, xmin, ymax, xmax] 정규화 좌표. 실패 시 None."""
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


def _to_pt(bbox_1000: list[int], page_w: float, page_h: float) -> tuple[float, float, float, float]:
    """[ymin, xmin, ymax, xmax] × 1000 → PDF pt (x1, y1, x2, y2)."""
    ymin, xmin, ymax, xmax = bbox_1000
    return (
        float(xmin) / 1000 * page_w,
        float(ymin) / 1000 * page_h,
        float(xmax) / 1000 * page_w,
        float(ymax) / 1000 * page_h,
    )


@lru_cache(maxsize=1)
def _get_client():
    """google-genai Client. GOOGLE_API_KEY env 필수."""
    if not os.environ.get("GOOGLE_API_KEY"):
        raise RuntimeError(
            "GOOGLE_API_KEY 환경변수가 비어 있습니다. "
            "ADR-019: figure/table bbox 추정에 Gemini API 필수. "
            ".env 또는 export로 설정하세요."
        )
    from google import genai
    return genai.Client()


def estimate_bbox(
    page_png: bytes,
    caption: str,
    page_w: float,
    page_h: float,
    kind: str = "figure",
) -> tuple[float, float, float, float] | None:
    """Gemini로 bbox 추정 → PDF pt (x1, y1, x2, y2). not_found / 실패 시 None.

    1회 retry까지 시도.
    """
    from google.genai import types

    client = _get_client()
    prompt = _build_prompt(caption, kind)
    for _ in range(1 + _BBOX_RETRY):
        try:
            response = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=[
                    types.Part.from_bytes(data=page_png, mime_type="image/png"),
                    prompt,
                ],
            )
        except Exception:
            continue
        text = (response.text or "").strip()
        bb_norm = _parse_to_bbox(text)
        if bb_norm is not None:
            return _to_pt(bb_norm, page_w, page_h)
    return None
