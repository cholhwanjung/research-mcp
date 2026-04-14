"""[ADR-009](../docs/ADR.md#adr-009) 동적 토픽 분석 입력 패키지 빌더.

분류 자체는 Claude의 추론 — 본 모듈은 (context snippets + 인용된 논문 초록)을
Claude가 읽고 토픽 태그·`cited_for`·`abstract_summary`를 만들기 좋은 형태로 묶는다.
"""

from __future__ import annotations

_MAX_ABSTRACT = 1200
_MAX_CONTEXTS = 10


def pack_reference(ref_paper: dict, contexts: list[str]) -> dict:
    """한 reference 입력 dict.

    Args:
        ref_paper: SS/arxiv 메타 — `arxiv_id` 우선, 없으면 `paperId`. `title`, `abstract` 옵션.
        contexts:  본문 인용 문맥 스니펫 (`get_citation_contexts` 출력).

    Returns:
        Claude가 입력으로 받기 좋은 dict: paper_id, title, abstract(truncated), contexts(상위 N).
    """
    paper_id = ref_paper.get("arxiv_id") or ref_paper.get("paperId") or ""
    abstract = (ref_paper.get("abstract") or "")[:_MAX_ABSTRACT]
    return {
        "paper_id": paper_id,
        "title": ref_paper.get("title", ""),
        "abstract": abstract,
        "contexts": list(contexts)[:_MAX_CONTEXTS],
    }


def build_classification_prompt(anchor_title: str, packed_refs: list[dict]) -> str:
    """anchor 논문 + reference 패키지들 → Claude 분류 입력 마크다운.

    출력 마크다운은 각 reference에 대해 Claude가 채워야 할 3 필드를 명시:
      - topic            (자유 문자열, ADR-009)
      - abstract_summary (1-3줄)
      - cited_for        (anchor 입장에서 인용 이유, 1-2줄)
    """
    lines = [
        f"# 인용 분석 입력 — anchor: {anchor_title}",
        "",
        "각 reference에 대해 아래 세 필드를 채워주세요:",
        "- `topic`: 자유 문자열 토픽 태그 (예: \"frozen visual encoder reuse\")",
        "- `abstract_summary`: 인용된 논문 초록의 1-3줄 한국어 요약",
        f"- `cited_for`: {anchor_title} 입장에서 이 논문을 인용한 이유 (1-2줄)",
        "",
        "---",
    ]
    for r in packed_refs:
        lines.append("")
        lines.append(f"## {r.get('title') or '(no title)'}  ·  `{r.get('paper_id', '')}`")
        abstract = r.get("abstract") or ""
        if abstract:
            lines.append("")
            lines.append("**Abstract**")
            lines.append(abstract)
        contexts = r.get("contexts") or []
        if contexts:
            lines.append("")
            lines.append(f"**Contexts ({len(contexts)})**")
            for c in contexts:
                lines.append(f"- {c}")
    return "\n".join(lines)
