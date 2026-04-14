---
name: citation-analysis
description: anchor 논문의 references / cited_by에 동적 토픽 + 인용 이유를 채워 vault에 누적한다 (ADR-009).
trigger:
  - "이 논문의 인용 흐름 분석해"
  - "<arxiv_id> references 동적 토픽"
  - "BLIP-2 인용 분석"
inputs:
  - arxiv_id (string, 예: "2301.12597")
  - direction (string, "references" | "cited_by", 기본 "references")
  - top_k (int, 기본 20 — 첫 호출. "더" 요청 시 확장)
---

## When to invoke
사용자가 한 논문의 인용 그래프를 **토픽 단위로** 정리하길 원할 때.
단순 "어떤 논문을 인용했나?" 수준이면 `get_references_by_citations` 단독으로 충분.

## Steps (tool sequence)

| # | Tool | 목적 |
|---|---|---|
| 1 | `get_paper_by_id(arxiv_id)` | anchor 메타 (title, abstract, citationCount) |
| 2 | `get_references_by_citations(arxiv_id, top_k=20, sort='count')` (또는 `get_citations_by_citations`) | 분석 대상 후보 — `sort='velocity'`도 옵션 (ADR-004) |
| 3 | 각 ref에 대해 `get_paper_by_id(ref_id)` | 인용된 논문 초록 fetch (병렬 가능) |
| 4 | 각 ref에 대해 `get_citation_contexts(anchor_id, ref_id)` | 본문 인용 문맥 스니펫 |
| 5 | (코드) `analysis.grouping.pack_reference` + `build_classification_prompt` | Claude 입력 마크다운 패키지 빌드 |
| 6 | (LLM 추론) | 각 ref에 `topic` + `abstract_summary` + `cited_for` 생성 (ADR-009 자유 문자열) |
| 7 | `wiki_read_note(arxiv_id)` → `wiki_write_note(arxiv_id, frontmatter, body)` | anchor 노트 `references`/`cited_by` 채움 + `citation_velocity` 갱신 |
| 8 | 각 topic에 대해 `wiki_link(arxiv_id, f"topics/{topic_slug}", note=cited_for)` | wikilink 자동 (D-2). 동일 토픽 재방문 시 자연스럽게 `topics/<slug>` MOC에 누적. |

## Frontmatter 갱신 (ARCHITECTURE §5.1, ADR-009)

```yaml
references:
  - paper_id: 2106.04560
    topic: "frozen visual encoder reuse"
    abstract_summary: "CLIP은 대규모 image-text contrastive로 학습된 ViT."
    cited_for: "BLIP-2의 frozen ViT 초기화 근거로 인용"
citation_velocity: 411.3            # analysis.ranking.citation_velocity 사용
```

`cited_by` 항목 스키마는 동일. `cited_by`는 `direction='cited_by'`로 본 스킬을 실행하거나
`vault_backlinks(arxiv_id)`로 다른 vault 노트가 anchor를 가리키면 자동으로 보강된다.

## Drill-down UX (D-6)
- **첫 호출**: top-20만 분석 (Claude 입력 token + SS 호출 절약). 사용자에게 "더 깊이 보려면 max_fetch 늘려주세요" 안내.
- **"더" 요청**: 같은 anchor에 대해 `max_fetch=1000`으로 재호출 → 캐시(Phase 3.0) 덕분에 첫 200건은 0 네트워크, 800건만 신규 fetch.
- 동일 anchor를 두 번째 분석할 때 기존 `references` frontmatter를 read → 덮어쓰지 말고 **merge** (paper_id 기준 dedup).

## Output format (사용자 응답)
```
🔍 인용 분석 완료: arXiv:{anchor_id} ({title})
   분석 references: {N}개 (top_k={top_k}, sort={sort})
   동적 토픽 ({M}개): {topic_1}, {topic_2}, ...
   vault 갱신: papers/{anchor_id}/index.md
   wikilink 추가: {K}개 → topics/...
   다음 단계: "더 깊게" → max_fetch=1000, "다른 방향" → direction=cited_by
```

## Failure handling
- step 2 SS 4xx/429 → cache 미존재 + rate-limit. CLAUDE.md "도구 한계 대응" — 임의 web search 우회 금지. 사용자에게 `SS_API_KEY` env 설정 권유.
- step 4 contexts 빈 결과 → 정상 (SS가 본문 미수집 가능). 해당 ref는 abstract만으로 분류.
- step 7 wiki_read_note 실패 → 먼저 `paper-ingest` 스킬로 anchor 노트 생성 필요.

## 후속 호출 제안
완료 직후:
- "관련 토픽 MOC을 한번에 보려면 `wiki_list('topics')`"
- "토픽별 카드 그래프를 보려면 `research-flow` 스킬 (Phase 5)"
