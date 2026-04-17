---
name: citation-analysis
description: 특정 논문 1편을 중심으로 인용 흐름을 동적 토픽으로 분석 + vault 누적(승인 게이트) + 시각화. anchor가 명확히 지정된 경우의 정식 진입점 (ADR-009, ADR-014).
trigger:
  - "BLIP-2 흐름 보여줘"
  - "<arxiv_id> 인용 흐름 분석"
  - "<arxiv_id> 흐름 시각화"
  - "이 논문의 인용 흐름 분석"
  - "BLIP-2 references 동적 토픽"
inputs:
  - arxiv_id (string, 예: "2301.12597") — **필수**. 논문 제목으로 지시받으면 `search_papers`로 ID를 먼저 해석한 뒤 본 스킬 진입.
  - direction (string, "both"|"references"|"cited_by", 기본 "both") — 두 방향 모두 분석해야 시각화가 완전.
  - top_k (int, 기본 20)
---

## When to invoke
사용자가 **특정 논문 1편**의 인용 흐름을 정리하길 원할 때 — 입력이 논문 제목 또는 arXiv ID로 명시된 경우. 시각화 + vault 영구 누적까지 한 번에 처리한다.

분기 기준:
- 사용자가 **주제/분야 키워드**(예: "VLM 흐름")로 요청 → `research-flow` 스킬 (anchor 선정 단계 필요).
- 사용자가 **단순 "어떤 논문 인용했나"** 수준 → `get_references_by_citations` 단독.
- 본 스킬은 **분석 + vault 갱신 + 시각화** 세트 — 가장 무거운 워크플로우다.

## Steps (tool sequence)

| # | Tool | 목적 |
|---|---|---|
| 1 | `get_paper_by_id(arxiv_id)` | anchor 메타 (title, abstract, citationCount) |
| 2 | `get_references_by_citations(arxiv_id, top_k=20)` | references velocity 순 (기본) + min_velocity=10 / isInfluential OR |
| 3 | `get_citations_by_citations(arxiv_id, top_k=20)` | 후속 인용 (direction='both'일 때만) |
| 4 | 각 ref/cite에 대해 `get_paper_by_id(target_id)` | 초록 fetch (병렬 권장) |
| 5 | 각 ref/cite에 대해 `get_citation_contexts(anchor_id, target_id)` | 본문 인용 문맥 |
| 6 | (코드) `analysis.grouping.pack_reference` + `build_classification_prompt` | Claude 입력 패키지 |
| 7 | (LLM 추론) | refs와 cites **각각 독립적으로** topic + abstract_summary + cited_for 생성 → `ref_groups`, `cite_groups` |
| 8 | **(승인 게이트)** | 사용자에게 미리보기 표시 후 vault 저장 여부 확인 — 아래 §승인 게이트 |
| 9 | (승인 시) `wiki_read_note(arxiv_id)` → `wiki_write_note(arxiv_id, frontmatter, body)` | anchor 노트 frontmatter 갱신. `_resolve_slug`가 arxiv_id를 title-slug 폴더로 자동 매핑 (ADR-016). 노트가 없으면 먼저 `paper-ingest`. |
| 10 | (승인 시) 각 topic에 `wiki_link(arxiv_id, f"topics/{topic_slug}", note=cited_for)` | wikilink 누적 (D-2). source는 arxiv_id 형태 그대로 사용 가능 — _resolve_slug가 매핑. |
| 11 | `build_citation_canvas(anchor, ref_groups, cite_groups, slug=<title-slug>)` | 시각화 — 승인 여부와 무관하게 항상 산출. `slug`는 vault의 title-slug. anchor frontmatter의 `slug` 필드 또는 `wiki_read_note` 응답에서 추출. |

## 승인 게이트 (Step 8)

vault에 영구 기록되기 직전에 사용자 응답을 대기한다. Claude Desktop의 대화형 UX에 맞춰 다음 형식으로 출력하고 **다음 사용자 turn까지 정지**:

```
📝 vault 저장 미리보기: papers/{arxiv_id}/index.md
   anchor: {title} (cited {N}, vel {V})
   refs 토픽 ({M_ref}개): {topic_1}, {topic_2}, ...
   cites 토픽 ({M_cite}개): {topic_1}, ...
   refs frontmatter: {R}개 entry / cites: {C}개 entry
   wikilink 추가 예정: {K}개 (topics/...)

저장하시겠습니까? (예 / 아니오)
   "예"  → step 9-10 진행
   "아니오" → vault 변경 skip, in-memory 분석 결과 + 시각화만 출력
```

응답 처리:
- **"예" / "yes" / "y" / "응" / "ㅇ"** → step 9-10 실행.
- **"아니오" / "no" / "n" / "ㄴ"** → step 9-10 skip. 응답에 "vault 미저장 (사용자 거부)" 명시.
- **기타 / 무응답** → 보수적으로 skip (재요청 시 사용자가 명시).

## Frontmatter 갱신 (승인 시)

ARCHITECTURE §5.1 스키마 + ADR-009 동적 토픽.

```yaml
references:
  - paper_id: 2106.04560
    topic: "frozen visual encoder reuse"
    abstract_summary: "CLIP은 대규모 image-text contrastive로 학습된 ViT."
    cited_for: "BLIP-2의 frozen ViT 초기화 근거로 인용"
cited_by:
  - paper_id: 2304.08485
    topic: "Q-Former 후속 변형"
    abstract_summary: ...
    cited_for: ...
citation_velocity: 411.3
```

기존 `references` / `cited_by` 가 이미 있다면 **merge** (paper_id 기준 dedup), 덮어쓰지 말 것.

## Drill-down UX (D-6)
- **첫 호출**: top-20만 분석 (Claude 입력 token + SS 호출 절약).
- **"더" 요청**: `max_fetch=1000`으로 재호출 → 캐시 덕분에 첫 200건은 0 네트워크.
- 신생 후속도 보고 싶으면 step 3 인자 `exclude_recent_year=False, min_velocity=0`.

## Output format (사용자 응답)

```
🔍 인용 분석 완료: arXiv:{anchor_id} ({title})
   refs 분석: {N_ref}개 (top_k={top_k})
   cites 분석: {N_cite}개
   ref 토픽 ({M_ref}개): {topic_1}, {topic_2}, ...
   cite 토픽 ({M_cite}개): {topic_1}, ...
   vault: {저장 완료 | 미저장 (사용자 거부)}
   wikilink: {K}개 추가 | -
   캔버스: canvases/{arxiv_id}.canvas — Obsidian에서 자유 편집 가능

```mermaid
...
```
```

## Failure handling
- step 1 SS 4xx/429 → 사용자에게 `SS_API_KEY` env 설정 권유. 임의 web search 우회 금지 (CLAUDE.md).
- step 2/3 cache miss + 429 → 백오프 후 재시도 (core/http.RETRY_DELAYS).
- step 5 contexts 빈 결과 → 정상 (SS가 본문 미수집 가능). 해당 ref/cite는 abstract만으로 분류.
- step 9 wiki_read_note 실패 → 먼저 `paper-ingest` 스킬로 anchor 노트 생성 필요.
- step 11 vault 권한 오류 → vault 경로 확인 안내.

## 후속 호출 제안
- "주제 전반의 anchor 후보를 둘러보고 싶다" → `research-flow` 스킬
- "다른 anchor 깊이 분석" → 같은 스킬 재실행 (arxiv_id 교체)
- "토픽별 누적을 보려면" → `wiki_list('topics')`
