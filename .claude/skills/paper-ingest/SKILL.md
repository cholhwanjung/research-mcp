---
name: paper-ingest
description: arXiv 논문 1편을 PDF·요약·핵심 figure만 선별해 vault에 누적한다 (멀티모달 KB). PDF가 20페이지 이상으로 크면 figure/table 분석(Vision bbox 추정)이 오래 걸리므로 해당 단계를 자동 skip하고 텍스트 요약만 저장하며, 사용자가 원하면 on-demand로 추출한다.
trigger:
  - "이 논문 ingest"
  - "{arxiv_id} 저장"
  - "BLIP-2 위키에 추가"
inputs:
  - 'arxiv_id (string, 예: "2301.12597") 또는 논문 제목 (이 경우 search_papers로 ID 먼저 해석)'
---

## When to invoke
사용자가 특정 arXiv 논문을 vault에 영구 누적하길 원할 때. 단순 "검색"이나 "1회 요약"이 목적이면 본 스킬을 호출하지 말 것 — `search_papers` / `read_paper` 단독으로 충분.

## Steps (tool sequence)

| # | Tool | 목적 |
|---|---|---|
| 1 | `get_paper_by_id(arxiv_id)` | 메타데이터 + Citation 수 + TL;DR. **title 확보**. |
| 2 | (코드) title → slug 변환 | title을 사람·grep 친화 slug로. 예: `"BLIP-2: ..."` → `"blip-2"`. 이후 모든 vault 작업은 이 slug를 사용. |
| 3 | `download_paper(arxiv_id)` | PDF를 `pdfs/{arxiv_id}.pdf`에 저장 (캐시 hit이면 skip). PDF는 arxiv_id로 식별. |
| 4 | `read_paper(arxiv_id, max_pages=0)` | 전문 텍스트 추출 (요약 입력) |
| 4.5 | (코드) PDF 페이지 수 확인 → **대용량 게이트** | `pdfs/{arxiv_id}.pdf`의 페이지 수를 세어 `page_count` 확보. **`page_count >= PAGE_LIMIT`(기본 20)** 이면 5a-fig/5a-tab/5b/5c 전체를 **skip** (아래 "대용량 PDF 게이트" 참조). 미만이면 정상 진행. |
| 5a-fig | `extract_paper_figures(arxiv_id, slug={title-slug})` | *(게이트 통과 시에만)* Vision으로 bbox 추정 후 clip. 파일명은 `fig_{N}_{caption-slug}.png` — 예: `fig_1_overview-of-blip-2s-framework.png`. vector-only figure도 시각적으로 인식. **`GOOGLE_API_KEY` 환경변수 필수**. |
| 5a-tab | `extract_paper_tables(arxiv_id, slug={title-slug})` | *(게이트 통과 시에만)* Vision으로 table bbox 추정 후 clip. 학회 layout(caption above/below) 자동 인식. 파일명은 `table_{N}_{caption-slug}.png`. |
| 5b | (LLM 추론) | figure / table 각각의 caption을 검토해 **핵심만** 선별. **figure drop 패턴**: 데이터셋 sample, 부록·illustration. **figure keep 패턴**: architecture/framework, result plot, qualitative comparison(대표 1-2장). **table은 대부분 keep** — 보통 ablation/SOTA 비교라 정보 밀도 높음. 모호하면 keep (false negative 최소화). |
| 5c-fig | `prune_paper_figures(arxiv_id, keep=[...], slug={title-slug})` | 선별 외 figure 삭제. `keep`은 **번호만 명시해도 동작**: `["fig_1", "fig_3"]` → `fig_1_*.png`, `fig_3_*.png` 매칭. 정확한 파일명(`fig_1_overview-...`)도 허용. |
| 5c-tab | `prune_paper_tables(arxiv_id, keep=[...], slug={title-slug})` | 선별 외 table 삭제. `keep` 매칭은 figure와 동일 — `["table_1", "table_2"]`. |
| 5d (옵션) | `render_paper_page(arxiv_id, page=N, slug={title-slug})` | figure crop이 잡지 못한 페이지나 수식 위주 페이지를 통째로 PNG 보존. 사용자 요청 시에만. |
| 5.5 | `wiki_list_hubs()` | **vault의 안정 hub 목록 fetch** — LLM이 paper 분야 매핑에 사용. |
| 6 | (LLM 추론) | 본문에서 TL;DR / Key Contributions / Methods / Findings 요약 작성 (한국어) + paper 분야를 **기존 hub 중 1-3개 매칭** (자유문자열 금지). 매칭 불가 시 신규 hub 후보로 사용자 승인 받음. |
| 7 | (코드) citation velocity 계산 = `citation_count / max(1, 현재연도 - 출판연도)` | frontmatter `citation_velocity` 채움 |
| 8 | `wiki_write_note(slug={title-slug}, frontmatter, body)` | vault에 `papers/{title-slug}/{title-slug}.md` 저장. frontmatter에 `arxiv_id` 보존 (식별자). frontmatter `figures`와 body `## Figures`엔 5c 이후 남은 figure만 포함. |
| 9 | (선택) `citation-analysis` 스킬 위임 | references / cited_by 동적 토픽 채움. 사용자 요청 시까지 미뤄도 됨. |

## Slug 규약
- vault 폴더·파일명은 title에서 만든 **title-slug**. 사람 가독성·grep 친화 우선.
- arxiv_id는 **frontmatter에만** 식별자로 보존. 외부 도구(예: `citation-analysis`)가 arxiv_id로 노트를 찾으면 frontmatter scan으로 자동 매핑된다.
- PDF는 `pdfs/{arxiv_id}.pdf` 그대로 (식별자 안정성).

## 대용량 PDF 게이트 (Step 4.5)

큰 논문(survey 등)은 figure/table이 많아 **Vision bbox 추정(5a-fig/5a-tab)이 오래 걸린다.** 페이지 수로 사전 판단해, 임계값 이상이면 figure/table 파이프라인을 통째로 skip한다.

**임계값**: `PAGE_LIMIT = 20` (페이지 수 **20 이상**이면 skip). 논문 성격에 따라 조정 가능.

**페이지 수 확인 (코드)** — 다운로드된 PDF에서 직접 카운트:
```python
try:
    from pypdf import PdfReader
    page_count = len(PdfReader(f"pdfs/{arxiv_id}.pdf").pages)
except Exception:
    # fallback: pdfinfo (poppler)
    import subprocess, re
    out = subprocess.run(["pdfinfo", f"pdfs/{arxiv_id}.pdf"],
                         capture_output=True, text=True).stdout
    page_count = int(re.search(r"Pages:\s+(\d+)", out).group(1))
```

**게이트 판정**:
- `page_count < PAGE_LIMIT` → 정상 진행 (5a-fig/5a-tab/5b/5c 실행).
- `page_count >= PAGE_LIMIT` → **figure/table 관련 5a·5b·5c 단계 전부 skip.** 텍스트 요약(6~8단계)은 그대로 수행. frontmatter `figures`는 빈 리스트, `figures_skipped: true`, `page_count` 기록. body `## Figures`엔 생략 사유 한 줄만 남긴다.

**override (게이트 무시)**:
- 사용자가 명시적으로 figure/table 추출을 요청한 경우(예: "figure까지 다 뽑아줘", "표 이미지도 저장해줘") → 페이지 수와 무관하게 정상 진행.
- 페이지 수 카운트 실패(PDF 손상 등) → skip하지 말고, 안전하게 정상 진행을 시도하되 사용자에게 카운트 실패를 알린다.

**skip 후 on-demand 안내**: 대용량이라 skip한 경우, ingest 완료 응답에 "figure/table이 필요하면 말씀해 주세요 — 해당 논문만 추출해 vault에 추가합니다"를 덧붙인다. 이후 요청 시 override 경로로 5a~5c만 실행하고 노트를 갱신한다.

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
arxiv_id는 frontmatter 식별자.

> vault 노트에 기록되는 frontmatter 주석·본문 헤더·노트 본문에는 이 지침서의 내부 표기나 관리 메모를 옮기지 말고, 사용자용 연구 내용만 남긴다. 아래 예시의 `#` 코멘트는 본 지침을 읽는 LLM/에이전트용 안내이며 실제 vault yaml에는 옮기지 않는다.

```yaml
arxiv_id: {id}                        # 식별자, 폴더명 아님
ss_paper_id: {from step 1}
slug: {title-slug}                    # vault 위치와 일치하는 slug
title: ...
authors: [...]
year: ...
venue: ...
citation_count: ...
influential_citation_count: ...
topics: [{hub slug}]                  # vault의 안정 hub 목록 중 매칭된 slug만. 자유문자열 금지. wiki_list_hubs로 후보 조회 후 1-3개 선택.
page_count: {N}                       # step 4.5에서 센 PDF 페이지 수
figures_skipped: false                # 대용량 게이트로 figure/table skip 시 true
figures:                              # 5c 이후 남은 항목만. skip된 경우 빈 리스트.
  - file: figures/fig_1.png
    caption: "Architecture overview of ..."
ingested_at: {today}
pdf_path: ../../pdfs/{arxiv_id}.pdf   # PDF는 arxiv_id로 식별
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
<!-- 대용량 게이트로 skip된 경우, 위 이미지 대신 아래 한 줄만: -->
<!-- _Figure/table 추출 생략됨 ({page_count}p ≥ PAGE_LIMIT). 필요 시 on-demand 추출 가능._ -->
## References (citation-analysis 시 채움)
## Related
- [[topics/{slug}]]
```

## Output format (사용자 응답)

**정상 (게이트 통과):**
```
✅ ingest 완료: {title} (arXiv:{id})
   PDF: pdfs/{id}.pdf (캐시 hit/저장), {page_count}p
   Figures: 전체 {N_extract}개 추출 → {N_kept}개 유지 (핵심 선별)
   노트: papers/{title-slug}/index.md
```

**대용량 skip:**
```
✅ ingest 완료: {title} (arXiv:{id})
   PDF: pdfs/{id}.pdf (캐시 hit/저장), {page_count}p — 대용량(≥{PAGE_LIMIT}p)이라 figure/table 분석 skip
   노트: papers/{title-slug}/index.md (텍스트 요약만)
   ℹ️ figure/table이 필요하면 말씀해 주세요 — 이 논문만 추출해 추가합니다.
```

## Failure handling
- step 1 `get_paper_by_id`가 "❌ 논문을 찾을 수 없습니다" 반환 → SS API 429 가능 → 사용자에게 재시도/시간 두기 안내. 임의 web search로 우회하지 말 것.
- step 2 PDF 다운로드 실패 → 그대로 중단, 본 스킬 abort.
- step 4.5 페이지 수 카운트 실패 (PDF 손상 등) → skip으로 넘기지 말고 정상 진행을 시도하되 카운트 실패를 사용자에게 알림. (skip은 "확실히 대용량"일 때만.)
- step 4a figure 0개 → caption 매칭 실패 가능. 정보만 알리고 4b/4c skip 후 계속.
- step 4b LLM이 모든 figure를 drop으로 판정 → 보수적으로 architecture 후보 1개는 keep 권장. 0개여도 진행 가능.
- step 7 wiki_write_note 실패 → 디스크 권한 / vault 경로 확인 안내.

## 후속 호출 제안
ingest 직후 사용자에게:
- "인용 분석을 깊게 보려면 `citation-analysis` 스킬 (anchor 단일 깊이)"
- 대용량으로 figure/table을 skip한 경우: "figure/table을 추출하려면 말씀해 주세요 — override 경로로 5a~5c만 실행해 노트를 갱신합니다."
