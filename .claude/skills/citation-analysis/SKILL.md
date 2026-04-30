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
- 사용자가 **주제/분야 키워드**(예: "VLM 흐름")로 요청 → `search_papers`로 anchor 후보 검색 후 1편 선정해 본 스킬 진입.
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
| 6 | `wiki_list_hubs()` | **vault의 안정 hub 목록 + 정의 fetch (ADR-022)**. LLM이 자유 토픽 생성 대신 hub 매칭에 사용. |
| 6.5 | (코드) `analysis.grouping.pack_reference` + `build_classification_prompt` | Claude 입력 패키지 (hub 목록 같이 주입) |
| 7 | (LLM 추론, ADR-022) | refs와 cites 각 paper를 **기존 hub 중 하나(또는 복수)에 매핑**. 자유문자열 신규 hub 생성 금지 — 매칭이 불가능한 경우만 "신규 hub 후보"로 표시 후 사용자 승인 게이트. 출력: `{paper_id, matched_hubs: [hub_slug, ...], abstract_summary, cited_for, new_hub_candidate?: {slug, summary, parent}}`. |
| 8 | **(승인 게이트)** | 사용자에게 미리보기 + 신규 hub 후보 함께 표시 후 vault 저장 여부 확인 — 아래 §승인 게이트 |
| 9 | (승인 시) `wiki_read_note(arxiv_id)` → `wiki_write_note(arxiv_id, frontmatter, body)` | anchor 노트 frontmatter 갱신. `references[*].hubs`, `cited_by[*].hubs` 필드에 매칭된 hub slug 리스트 저장. `_resolve_slug`가 arxiv_id를 title-slug 폴더로 자동 매핑 (ADR-016). 노트가 없으면 먼저 `paper-ingest`. |
| 10 | (승인 시) 각 매칭된 hub에 `wiki_link(arxiv_id, hub_slug, note=cited_for)` | wikilink 누적. **target은 hub slug만** (`topics/<slug>`이 아닌 hub slug 그대로 — `[[VLM]]`). 신규 hub 승인 시 `wiki_write_note(f"topics/{slug}", frontmatter={tier:hub,...}, body)`로 먼저 hub 노트 생성. |
| 11 | `build_citation_canvas(anchor, ref_groups, cite_groups, slug=<title-slug>)` | 시각화 — 승인 여부와 무관하게 항상 산출. `slug`는 vault의 title-slug. anchor frontmatter의 `slug` 필드 또는 `wiki_read_note` 응답에서 추출. |

## 승인 게이트 (Step 8)

vault에 영구 기록되기 직전에 사용자 응답을 대기한다. Claude Desktop의 대화형 UX에 맞춰 다음 형식으로 출력하고 **다음 사용자 turn까지 정지**:

```
📝 vault 저장 미리보기: papers/{slug}/{slug}.md
   anchor: {title} (cited {N}, vel {V})
   매칭된 hub ({M}개): {hub_1}, {hub_2}, ...
   refs hub 분포: {hub_1}:{N_1}, {hub_2}:{N_2}, ...
   cites hub 분포: {hub_1}:{N_1}, ...
   refs frontmatter: {R}개 entry / cites: {C}개 entry
   wikilink 추가 예정: {L}개 (hub만)

🆕 신규 hub 후보 ({K}개, 승인 시에만 생성):
   - {slug}: {summary} (parent: {parent}, seed: {seed_paper_id})

저장하시겠습니까? (예 / 아니오)
   "예"  → step 9-10 진행 (신규 hub도 생성)
   "예, 기존 hub만" → step 9-10 진행 but 신규 hub skip (해당 paper는 closest 기존 hub로 강제 매칭)
   "아니오" → vault 변경 skip, in-memory 분석 결과 + 시각화만 출력
```

응답 처리:
- **"예" / "yes" / "y" / "응" / "ㅇ"** → step 9-10 실행 (신규 hub도 생성).
- **"예, 기존 hub만"** → 신규 hub skip + closest 기존 hub로 fallback, step 9-10 실행.
- **"아니오" / "no" / "n" / "ㄴ"** → step 9-10 skip. 응답에 "vault 미저장 (사용자 거부)" 명시.
- **기타 / 무응답** → 보수적으로 skip (재요청 시 사용자가 명시).

## Frontmatter 갱신 (승인 시, hub-only)

ARCHITECTURE §5.1 스키마. **자유문자열 `topic` 필드 폐기**, 대신 vault hub slug 리스트 `hubs`로 대체.

> **vault 본문 격리** (CLAUDE.md 하드 룰): wiki_write_note로 vault에 기록되는 frontmatter 주석·본문 헤더·노트 본문 어디에도 `ADR-N` / `SKILL.md` / `ARCHITECTURE` 같은 내부 메타 식별자를 박지 말 것. 메타 트레이서빌리티는 본 SKILL.md / docs/ADR.md / 코드 주석으로 유지.

```yaml
topics:                                 # paper 자체의 분야 — root hub slug만 (자유문자열 금지)
  - VLM
  - LLM
references:
  - paper_id: 2106.04560
    hubs: [VLM, Self-Supervised]        # 매칭된 hub (복수 가능)
    abstract_summary: "CLIP은 대규모 image-text contrastive로 학습된 ViT."
    cited_for: "BLIP-2의 frozen ViT 초기화 근거로 인용"
cited_by:
  - paper_id: 2304.08485
    hubs: [VLA]
    abstract_summary: ...
    cited_for: ...
citation_velocity: 411.3
```

기존 `references` / `cited_by`가 이미 있다면 **merge** (paper_id 기준 dedup), 덮어쓰지 말 것.

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

## Filter 노트 (ADR-021)
모든 refs/cites 응답은 `core.filter.is_survey`로 title에 `\bsurvey\b`가 매칭되는 논문이 자동 제외된다 (case-insensitive, word boundary). 결과적으로 step 2/3에서 받는 top_k는 "non-survey 기준 상위 N편". 사용자가 명시적으로 survey 논문을 분석하고 싶다면 직접 `get_paper_by_id(arxiv_id)` 호출.

## Failure handling
- step 1 SS 4xx/429 → 사용자에게 `SS_API_KEY` env 설정 권유. 임의 web search 우회 금지 (CLAUDE.md).
- step 2/3 cache miss + 429 → 백오프 후 재시도 (core/http.RETRY_DELAYS).
- **step 4 부분 실패 (`get_paper_by_id`가 일부 ref/cite에 "❌ 논문을 찾을 수 없습니다"** — 보통 신생 arxiv ID가 SS DB에 아직 매핑 안 됐거나 BLIP/ALIGN/FLAN 같이 SS sha lookup이 필요한 케이스):
  - **fallback (강제)**: step 2/3의 references/citations endpoint 응답에 이미 들어있는 **title + citation_count + velocity**로 title-only 분류 진행. abstract 없이 title + anchor 도메인 지식으로 topic + cited_for 추론.
  - 실패 비율(예: 9/20)과 paper_id 목록을 사용자 응답 상단에 **반드시 명시**.
  - **우회 금지**: 임의 web search로 abstract 보강 시도하지 않음 (CLAUDE.md "도구 한계 대응"). 같은 패턴이 누적되면 `sources/semantic_scholar`에 SS `paperId(sha)` fallback lookup 추가를 ADR 후보로 등록.
  - 한 토픽 그룹이 전부 fallback 항목이라면 topic 라벨은 보수적으로 (`"<주제> 응용"`처럼 일반화).
- step 5 contexts 빈 결과 → 정상 (SS가 본문 미수집 가능). 해당 ref/cite는 abstract만으로 분류.
- step 9 wiki_read_note 실패 → 먼저 `paper-ingest` 스킬로 anchor 노트 생성 필요.
- step 11 vault 권한 오류 → vault 경로 확인 안내.

## 후속 호출 제안
- "다른 anchor 깊이 분석" → 같은 스킬 재실행 (arxiv_id 교체)
- "토픽별 누적을 보려면" → `wiki_list('topics')`
