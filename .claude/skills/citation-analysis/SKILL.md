---
name: citation-analysis
description: 논문 1편(anchor)의 references/cited_by를 기존 hub로 분류해 vault frontmatter·wikilink에 누적하고(승인 게이트) Mermaid 인용 그래프를 만든다. anchor가 제목·arXiv ID로 지정된 경우의 진입점.
trigger:
  - "BLIP-2 흐름 보여줘"
  - "{arxiv_id} 인용 흐름 분석"
  - "이 논문의 인용 흐름 분석"
inputs:
  - 'arxiv_id (필수) — 제목으로 지시받으면 search_papers로 ID를 먼저 해석'
  - 'direction ("both"|"references"|"cited_by", 기본 "both") — 시각화가 완전하려면 both'
  - 'top_k (기본 20)'
---

## When to invoke
특정 논문 1편의 인용 흐름을 분석·시각화·vault 누적할 때. 주제 키워드("VLM 흐름")로 오면 `search_papers`로 anchor 1편을 고른 뒤 진입. "어떤 논문을 인용했나" 수준이면 `get_references_by_citations` 단독.

## Steps

| # | 도구 | 규칙 |
|---|---|---|
| 1 | `get_paper_by_id(arxiv_id)` | anchor 메타 |
| 2 | `get_references_by_citations(arxiv_id, top_k=20)` | velocity 순 (기본 `min_velocity=10` 또는 influential) |
| 3 | `get_citations_by_citations(arxiv_id, top_k=20)` | `both`일 때만. **anchor가 최근 1~2년(출판연도 ≥ 올해−1)이면 `exclude_recent_year=False, min_velocity=0`** — 기본 필터가 그 인용을 전부 잘라낸다 |
| 4 | 각 ref/cite에 `get_paper_by_id(target)` | 초록. 병렬 |
| 5 | 각 ref/cite에 `get_citation_contexts(anchor, target)` | 본문 인용 문맥. 빈 결과는 정상 — 초록만으로 분류 |
| 6 | `wiki_list_hubs()` | hub 목록·정의 |
| 7 | 분류 (LLM) | 각 논문을 **기존 hub**에 매핑 → `{paper_id, matched_hubs, abstract_summary, cited_for, new_hub_candidate?: {slug, summary, parent}}`. 태깅 규칙은 `wiki_list_hubs()` 응답 첫 줄 — 특히 **anchor 자신의 hub는 여기서 늘리지 않는다**(인용 흐름은 소속 근거가 아니다). 매칭 불가만 신규 후보 |
| 8 | **승인 게이트** | 미리보기(anchor · hub 분포 · refs/cites entry 수 · wikilink 수 · 신규 hub 후보) 출력 후 **사용자 turn까지 정지**. 예 → 9-10 · "기존 hub만" → 신규 hub 없이 closest 기존 hub로 9-10 · 아니오/무응답 → 9-10 skip, 분석·그래프만. **autopilot 호출이면 정지 없이 자동 승인** — refs/cites 쪽 신규 hub는 만들지 않고 closest 기존 hub |
| 9 | `wiki_read_note(arxiv_id)` → `wiki_write_note(arxiv_id, fm, body)` | anchor frontmatter `references`/`cited_by` 갱신 — **paper_id 기준 merge+dedup, 덮어쓰지 않는다**. 노트 없으면 `paper-ingest` 먼저 |
| 10 | 매칭 hub마다 `wiki_link(arxiv_id, hub_slug, note=cited_for)` | target은 hub slug 그대로(`topics/` 접두사 없이). 신규 hub 승인 시 `wiki_write_note("topics/<slug>", {tier: hub, …})`로 먼저 생성 — 본문에서 vault 논문은 `[[slug\|표기]]` |
| 11 | `build_citation_graph(anchor, ref_groups, cite_groups, slug=title-slug)` | 승인 여부 무관 항상. `graphs/{slug}.md` (Mermaid). slug는 anchor frontmatter `slug` |
| 12 | (선택) `export_citation_network()` | vault 통합 네트워크. 전역 엣지 > 200이면 CSV/GEXF + Cosmograph/Gephi Lite 권고 |

## Frontmatter (승인 시)
```yaml
topics: [VLM, LLM]                     # anchor 자신의 분야 — hub slug만
references:
  - paper_id: 2106.04560
    hubs: [VLM, Self-Supervised]
    abstract_summary: "..."
    cited_for: "..."
cited_by:
  - paper_id: 2304.08485
    hubs: [VLA]
    abstract_summary: "..."
    cited_for: "..."
citation_velocity: 411.3
```
vault 노트엔 연구 내용만 — 이 지침의 주석·내부 표기를 옮기지 않는다.

## Drill-down
첫 호출은 top-20. "더" → `max_fetch=1000` (캐시로 첫 200건은 네트워크 0). 신생 후속까지 보려면 step 3을 `exclude_recent_year=False, min_velocity=0`.
refs/cites 응답은 제목에 `survey`가 든 논문을 자동 제외한다 — survey를 보려면 `get_paper_by_id` 직접 호출.

## Output
anchor · refs/cites 분석 수 · hub 분포 · vault 저장 여부(거부면 "미저장") · 추가된 wikilink 수 · `graphs/{slug}.md` 경로 + mermaid 블록.

## Failure handling
- `⏳`(SS 한도·일시 장애) → 재시도, 그래도 안 되면 title-only fallback. `❌`만 미매핑이다. web search로 우회하지 않는다. 429가 잦으면 `SS_API_KEY` 설정 권유.
- step 4에서 일부 `❌`(신생 ID·SS sha 케이스) → step 2/3 응답의 title·citation_count·velocity로 **title-only 분류**. 실패 비율과 paper_id를 응답 상단에 명시. 한 그룹이 전부 fallback이면 hub 라벨은 보수적으로.
- step 9 노트 없음 → `paper-ingest` 먼저.
- step 11 vault 권한 오류 → 경로 확인 안내.
