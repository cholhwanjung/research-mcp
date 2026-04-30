---
name: paper-ingest
description: arXiv 논문 1편을 PDF·요약·핵심 figure만 선별해 vault에 누적한다 (멀티모달 KB, ADR-015).
trigger:
  - "이 논문 ingest"
  - "<arxiv_id> 저장"
  - "BLIP-2 위키에 추가"
inputs:
  - arxiv_id (string, 예: "2301.12597") 또는 논문 제목 (이 경우 search_papers로 ID 먼저 해석)
---

## When to invoke
사용자가 특정 arXiv 논문을 vault에 영구 누적하길 원할 때. 단순 "검색"이나 "1회 요약"이 목적이면 본 스킬을 호출하지 말 것 — `search_papers` / `read_paper` 단독으로 충분.

## Steps (tool sequence)

| # | Tool | 목적 |
|---|---|---|
| 1 | `get_paper_by_id(arxiv_id)` | 메타데이터 + Citation 수 + TL;DR. **title 확보**. |
| 2 | (코드) `core.slug.slugify_title(title)` | title → 사람·grep 친화 slug. 예: `"BLIP-2: ..."` → `"blip-2"`. 이후 모든 vault 작업은 이 slug를 사용 (ADR-016). |
| 3 | `download_paper(arxiv_id)` | PDF를 `pdfs/<arxiv_id>.pdf`에 저장 (캐시 hit이면 skip). PDF는 arxiv_id로 식별. |
| 4 | `read_paper(arxiv_id, max_pages=0)` | 전문 텍스트 추출 (요약 입력) |
| 5a-fig | `extract_paper_figures(arxiv_id, slug=<title-slug>)` | Gemini Vision으로 bbox 추정 후 clip (ADR-019). 파일명은 `fig_<N>_<caption-slug>.png` — 예: `fig_1_overview-of-blip-2s-framework.png`. vector-only figure도 시각적으로 인식. **`GOOGLE_API_KEY` 환경변수 필수**. |
| 5a-tab | `extract_paper_tables(arxiv_id, slug=<title-slug>)` | Gemini Vision으로 table bbox 추정 후 clip. 학회 layout(caption above/below) 자동 인식. 파일명은 `table_<N>_<caption-slug>.png`. |
| 5b | (LLM 추론) | figure / table 각각의 caption을 검토해 **핵심만** 선별. **figure drop 패턴**: 데이터셋 sample, 부록·illustration. **figure keep 패턴**: architecture/framework, result plot, qualitative comparison(대표 1-2장). **table은 대부분 keep** — 보통 ablation/SOTA 비교라 정보 밀도 높음. 모호하면 keep (false negative 최소화). |
| 5c-fig | `prune_paper_figures(arxiv_id, keep=[...], slug=<title-slug>)` | 선별 외 figure 삭제. `keep`은 **번호만 명시해도 동작**: `["fig_1", "fig_3"]` → `fig_1_*.png`, `fig_3_*.png` 매칭. 정확한 파일명(`fig_1_overview-...`)도 허용. |
| 5c-tab | `prune_paper_tables(arxiv_id, keep=[...], slug=<title-slug>)` | 선별 외 table 삭제. `keep` 매칭은 figure와 동일 — `["table_1", "table_2"]`. |
| 5d (옵션) | `render_paper_page(arxiv_id, page=N, slug=<title-slug>)` | figure crop이 잡지 못한 페이지나 수식 위주 페이지를 통째로 PNG 보존. 사용자 요청 시에만. |
| 5.5 | `wiki_list_hubs()` | **vault의 안정 hub 목록 fetch (ADR-022)** — LLM이 paper 분야 매핑에 사용. |
| 6 | (LLM 추론) | 본문에서 TL;DR / Key Contributions / Methods / Findings 요약 작성 (한국어) + paper 분야를 **기존 hub 중 1-3개 매칭** (자유문자열 금지). 매칭 불가 시 신규 hub 후보로 사용자 승인 받음. |
| 7 | (코드) `analysis.ranking.citation_velocity(meta, current_year)` | frontmatter `citation_velocity` 채움 (ADR-004) |
| 8 | `wiki_write_note(slug=<title-slug>, frontmatter, body)` | vault에 `papers/<title-slug>/<title-slug>.md` 저장. frontmatter에 `arxiv_id` 보존 (식별자). frontmatter `figures`와 body `## Figures`엔 5c 이후 남은 figure만 포함. |
| 9 | (선택) `citation-analysis` 스킬 위임 | references / cited_by 동적 토픽 채움 (ADR-009). 사용자 요청 시까지 미뤄도 됨. |

## Slug 규약 (ADR-016)
- vault 폴더·파일명은 `core.slug.slugify_title`로 만든 **title-slug**. 사람 가독성·grep 친화 우선.
- arxiv_id는 **frontmatter에만** 식별자로 보존. 외부 도구(예: `citation-analysis`)가 arxiv_id로 노트를 찾으면 `tools.wiki_tools._resolve_slug`가 frontmatter scan으로 자동 매핑.
- PDF는 `pdfs/<arxiv_id>.pdf` 그대로 (식별자 안정성).

## Figure 선별 가이드 (Step 4b)

LLM 판단 기준:
- **keep**: 논문의 핵심 주장을 시각적으로 전달하는 figure.
  - architecture / framework overview
  - method / algorithm illustration
  - ablation·결과 table 또는 plot
  - 정량 비교 차트 (loss curve, accuracy 등)
  - 대표적 qualitative 결과 1-2장
- **drop**: 보조·장식 figure.
  - 데이터셋 sample 그리드 (`"Examples of ..."`, `"Samples from ..."`)
  - 부록의 보충 figure
  - 논문 로고·journal 양식 elements
  - 동일 정보를 반복하는 figure

판단이 모호하면 keep 쪽으로 (false negative 최소화). 사용자는 vault에서 직접 추가 정리 가능.

## Frontmatter 구성
ARCHITECTURE §5.1 + ADR-016 (arxiv_id는 frontmatter 식별자).

> **vault 본문 격리** (CLAUDE.md 하드 룰): wiki_write_note로 vault에 기록되는 frontmatter 주석·본문 헤더·노트 본문 어디에도 `ADR-N` / `SKILL.md` / `ARCHITECTURE` 같은 내부 메타 식별자를 박지 말 것. 아래 frontmatter 예시의 `# ADR-016` 같은 코멘트는 **본 SKILL.md를 읽는 LLM/에이전트용 가이드**이며, 실제 vault yaml에는 코멘트 자체를 옮기지 않는다.

```yaml
arxiv_id: <id>                        # ADR-016: 식별자, 폴더명 아님
ss_paper_id: <from step 1>
slug: <title-slug>                    # ADR-016: vault 위치와 일치하는 slug
title: ...
authors: [...]
year: ...
venue: ...
citation_count: ...
influential_citation_count: ...
topics: [<hub slug>]                  # ADR-022: vault topics/*.md (tier:hub) 중 매칭된 slug만. 자유문자열 금지. wiki_list_hubs로 후보 조회 후 LLM이 1-3개 선택.
figures:                              # ADR-015: 5c 이후 남은 항목만
  - file: figures/fig_1.png
    caption: "Architecture overview of ..."
ingested_at: <today>
pdf_path: ../../pdfs/<arxiv_id>.pdf   # PDF는 arxiv_id로 식별
status: read
```

## Body 구조 (고정 헤더)
```markdown
# {title}
## TL;DR
## Key Contributions
## Methods
## Findings
## Figures
![[figures/fig_1.png]]
*Figure 1: {caption}*
...
## References (citation-analysis 시 채움)
## Related
- [[topics/<slug>]]
```

## Output format (사용자 응답)
```
✅ ingest 완료: {title} (arXiv:{id})
   PDF: pdfs/{id}.pdf (캐시 hit/저장)
   Figures: 전체 {N_extract}개 추출 → {N_kept}개 유지 (핵심 선별)
   노트: papers/{title-slug}/index.md
```

## Failure handling
- step 1 `get_paper_by_id`가 "❌ 논문을 찾을 수 없습니다" 반환 → SS API 429 가능 → 사용자에게 재시도/시간 두기 안내 (CLAUDE.md "도구 한계 대응" — 임의 web search 우회 금지).
- step 2 PDF 다운로드 실패 → 그대로 중단, 본 스킬 abort.
- step 4a figure 0개 → caption 매칭 실패 가능. 정보만 알리고 4b/4c skip 후 계속.
- step 4b LLM이 모든 figure를 drop으로 판정 → 보수적으로 architecture 후보 1개는 keep 권장. 0개여도 진행 가능.
- step 7 wiki_write_note 실패 → 디스크 권한 / vault 경로 확인 안내.

## 후속 호출 제안
ingest 직후 사용자에게:
- "인용 분석을 깊게 보려면 `citation-analysis` 스킬 (anchor 단일 깊이, ADR-009)"
