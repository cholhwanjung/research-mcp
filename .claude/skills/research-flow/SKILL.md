---
name: research-flow
description: 주제/분야 키워드를 받아 anchor 후보를 선정하고, 인용 흐름을 1회용 Mermaid + Canvas로 시각화한다 (vault 누적 없음). 특정 논문이 이미 정해진 경우엔 `citation-analysis`로 위임.
trigger:
  - "VLM 흐름 보여줘"
  - "<topic> 연구 흐름 시각화"
  - "확산 모델 분야 흐름"
  - "<topic> 트렌드"
inputs:
  - query (string) — **주제/키워드** (예: "vision language model", "contrastive learning"). arxiv_id가 이미 명시되면 본 스킬을 invoke하지 말고 `citation-analysis`로 위임.
  - direction (string, 옵션, "LR"|"TD"|"RL"|"BT", 기본 "LR")
  - top_k (int, 기본 20)
  - sort (string, "count"|"velocity", 기본 "velocity")
---

## When to invoke
사용자가 **주제 키워드**로 분야 흐름을 한눈에 보고 싶을 때. anchor 선정이 본 스킬의 핵심 역할.

분기 기준 (입력 종류 기반):
- 입력이 **주제 키워드** → 본 스킬. anchor 후보 검색 + 1편 선정 + 1회용 시각화.
- 입력이 **논문 제목 또는 arXiv ID** → `citation-analysis` 스킬로 위임 (시각화 + vault 영구 누적 포함).
- 입력이 단순 검색이면 `search_papers` 단독으로 충분.

## Steps (tool sequence)

| # | Tool | 목적 |
|---|---|---|
| 1 | `search_papers(query)` | 주제 키워드로 후보 논문 리스트 |
| 2 | (LLM 추론) | anchor 1편 선정 (citation 수, 분야 대표성 기준) |
| 3 | `get_paper_by_id(anchor_id)` | anchor 메타 (title/year/citationCount) — viz 입력 |
| 4 | `get_references_by_citations(anchor_id, top_k=20)` *(기본 velocity + min_velocity=10)* | anchor가 인용한 주요 논문 |
| 5 | `get_citations_by_citations(anchor_id, top_k=20)` *(기본 velocity + exclude_recent_year=True)* | anchor를 인용한 주요 후속. SS publicationDate desc 대응 (ADR-014). |
| 6 | (선택) 상위 N편에 대해 `get_citation_contexts(anchor, ref)` | 토픽 그룹핑 정확도 ↑ |
| 7 | (LLM 추론) | refs와 cites를 **각각 동적 토픽 그룹핑** → `ref_groups`, `cite_groups` |
| 8 | `build_citation_canvas(anchor, ref_groups, cite_groups, slug=anchor_id, direction='LR')` | Mermaid + `vault/canvases/<slug>.canvas` |

**vault 노트는 작성하지 않는다** — 1회용 overview. anchor를 영구 누적하려면 `citation-analysis`를 별도 호출.

## Output format (사용자 응답)

`build_citation_canvas` 응답을 그대로 노출하면 Claude Desktop이 Mermaid를 즉시 렌더. 추가로:

```
🗺️ Research Flow: {anchor_title}
   anchor: arXiv:{id} ({year}, cited {N}, vel {V})
   refs 토픽 ({M_ref}개): {topic_1}, ...
   cites 토픽 ({M_cite}개): {topic_1}, ...
   캔버스: canvases/{slug}.canvas
   ※ vault 노트는 작성되지 않음 — 영구 누적은 `citation-analysis` 사용
```

## Drill-down 확장
- "이 anchor 깊게 분석 + vault 누적" → **`citation-analysis` 스킬로 위임** (시각화 결과는 동일하게 다시 산출 + 노트 영구 기록)
- "다른 anchor" → step 2 다시 (같은 검색 후보에서 교체)
- "subgraph 분리" → 한 그룹만 골라 `build_citation_canvas(anchor, [group], [])` 또는 `(anchor, [], [group])`
- "신생 후속도 보고 싶다" → step 5 인자 `exclude_recent_year=False, min_velocity=0`

## Failure handling
- step 1 빈 결과 → 사용자에게 키워드 재요청.
- step 4·5 SS 429 → cache 활용 안내, `SS_API_KEY` env 권유.
- step 8 vault 권한 오류 → vault 경로 확인.

## 후속 호출 제안
- "이 anchor를 영구 누적 + 깊게 분석" → `citation-analysis`
- "토픽별 누적 보기" → `wiki_list('topics')`
- "관련 분야 새 토픽" → `get_recommended_papers(anchor_id)`
