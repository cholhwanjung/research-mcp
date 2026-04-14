---
name: research-flow
description: 한 토픽/anchor를 골라 인용 흐름을 카드 그래프(Mermaid + Obsidian Canvas)로 산출한다 (R1, ADR-005).
trigger:
  - "VLM 흐름 보여줘"
  - "<topic> 연구 흐름 시각화"
  - "<arxiv_id> 인용 그래프"
inputs:
  - query (string) — 검색어 (예: "vision language model") **또는** arxiv_id
  - direction (string, 옵션, "LR"|"TD"|"RL"|"BT", 기본 "LR")
  - top_k (int, 기본 20)
  - sort (string, "count"|"velocity", 기본 "velocity" — 최신 흐름에 더 가까움)
---

## When to invoke
사용자가 한 분야/논문의 **흐름**을 시각적으로 한 번에 보고 싶을 때. 단순 검색은 `search_papers` 단독으로 충분.

## Steps (tool sequence)

| # | Tool | 목적 |
|---|---|---|
| 1 | `search_papers(query)` *(query가 키워드면)* | 후보 논문 리스트 |
| 2 | (LLM 추론) | anchor 1편 선정 (citation, 분야 대표성 기준). query가 arxiv_id면 그대로 anchor. |
| 3 | `get_paper_by_id(anchor_id)` | anchor 메타 (title/year/citationCount) — viz 입력 |
| 4 | `get_references_by_citations(anchor_id, top_k=20, sort='velocity')` | references velocity 순 |
| 5 | `get_citations_by_citations(anchor_id, top_k=20, sort='velocity')` | 후속 연구 velocity 순 |
| 6 | (선택) 상위 N편에 대해 `get_citation_contexts(anchor, ref)` | 본문 인용 문맥 — 토픽 그룹핑 정확도 ↑ |
| 7 | (LLM 추론) | refs/cites를 **동적 토픽**으로 그룹핑 (ADR-009). 각 그룹: `{topic, papers: [...]}` |
| 8 | `build_citation_canvas(anchor, groups, slug=anchor_id, direction='LR')` | Mermaid 응답 + `vault/canvases/<slug>.canvas` 저장 |

## Output format (사용자 응답)

`build_citation_canvas` 응답을 그대로 노출하면 Claude Desktop이 Mermaid를 즉시 렌더한다. 추가로:
```
🗺️ Research Flow: {anchor_title}
   anchor: arXiv:{id} ({year}, cited {N}, vel {V})
   토픽 ({K}개): {topic_1}, {topic_2}, ...
   refs: {R}편 / cites: {C}편 (sort={sort})
   캔버스: canvases/{slug}.canvas — Obsidian에서 자유 편집 가능
```

## Failure handling
- step 1 빈 결과 → 사용자에게 키워드 재요청.
- step 4·5 SS 429 → cache 활용 안내. `SS_API_KEY` env 권유.
- step 8 vault 권한 오류 → vault 경로 확인 안내.

## Drill-down 확장
- "더 자세히" → `citation-analysis` 스킬 위임 (vault 노트에 `topic`/`cited_for` 영구 저장)
- "다른 anchor" → 같은 토픽 다른 논문으로 step 2 재실행
- "subgraph 분리" → 그룹 1개만 골라 `build_citation_canvas(anchor, [group])`

## 후속 호출 제안
- "이 anchor를 영구 누적하려면 `paper-ingest`"
- "토픽별 누적을 보려면 `wiki_list('topics')`"
