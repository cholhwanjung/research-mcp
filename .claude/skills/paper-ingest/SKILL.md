---
name: paper-ingest
description: arXiv 논문 1편을 한국어 요약·핵심 figure/table과 함께 vault에 누적한다. 20쪽 이상이면 figure/table 추출은 건너뛰고 요청 시 on-demand로 뽑는다.
trigger:
  - "이 논문 ingest"
  - "{arxiv_id} 저장"
  - "BLIP-2 위키에 추가"
inputs:
  - 'arxiv_id 또는 논문 제목 (제목이면 search_papers로 ID를 먼저 해석)'
---

## When to invoke
논문을 vault에 영구 누적할 때. 검색·1회 요약이 목적이면 `search_papers` / `read_paper`만 쓴다.

## Steps

| # | 도구 | 규칙 |
|---|---|---|
| 1 | `get_paper_by_id(arxiv_id)` | 메타·인용수·**title** |
| 2 | title → slug | grep 친화 title-slug (`"BLIP-2: …"` → `blip-2`). 이후 vault 작업은 전부 이 slug. arxiv_id는 frontmatter 식별자로만 |
| 3 | `download_paper(arxiv_id)` | `pdfs/{arxiv_id}.pdf` (캐시 hit이면 skip) |
| 4 | `read_paper(arxiv_id, max_pages=0)` | 헤더 `({읽은}/{총} 페이지)`의 총 쪽수가 `page_count`. `research-autopilot` 호출이면 `max_pages=15` |
| 5 | **figure/table 게이트** | `page_count` ≥ 20 **또는** autopilot 호출 → 6~8 skip (`figures: []`, `figures_skipped: true`). 사용자가 figure 추출을 명시 요청하면 쪽수 무관 진행 |
| 6 | `extract_paper_figures(arxiv_id, slug=)` · `extract_paper_tables(arxiv_id, slug=)` | Vision bbox 추정. `GOOGLE_API_KEY` 필요 |
| 7 | 선별 (LLM) | **keep**: architecture/framework·method 도해·결과 plot/table·대표 qualitative 1-2장. **drop**: 데이터셋 샘플 그리드·부록 보충·로고·같은 정보 반복. table은 대부분 keep. 같은 번호의 sub-image는 묶어 판정. 모호하면 keep |
| 8 | `prune_paper_figures(arxiv_id, keep=[...], slug=)` · `prune_paper_tables(...)` | `keep`은 번호만(`["fig_1", "table_2"]`)도 된다 |
| 9 | `wiki_list_hubs()` → 요약 (LLM) | 한국어 TL;DR·Key Contributions·Methods·Findings. `topics`는 **기존 hub 1-3개** — 태깅 규칙은 `wiki_list_hubs()` 응답 첫 줄. 매칭 불가 → 신규 hub 후보로 사용자 승인(autopilot은 그 스킬의 자동 승인 규칙) |
| 10 | `wiki_write_note(slug, frontmatter, body)` | `papers/{slug}/{slug}.md`. `citation_velocity`는 step 1 응답의 `Velocity` |
| 11 | (선택) `citation-analysis` | references / cited_by 채움. 사용자 요청 시 |

`render_paper_page(arxiv_id, page=N, slug=)`는 사용자가 특정 페이지(수식·crop 실패 페이지) 보존을 요청할 때만.

## Frontmatter
```yaml
arxiv_id: {id}                 # 식별자 (폴더명은 slug)
ss_paper_id: {step 1}
slug: {title-slug}
title: ...
authors: [...]
year: ...
venue: ...
citation_count: ...
influential_citation_count: ...
citation_velocity: ...
topics: [{hub slug}]           # 기존 hub만
page_count: {N}
figures_skipped: false
figures:                       # 8 이후 남은 것만. skip이면 []
  - file: figures/fig_1.png
    caption: "..."
ingested_at: {today}
pdf_path: ../../pdfs/{arxiv_id}.pdf
status: read
```

## Body (고정 헤더)
```markdown
# {title}
## TL;DR
## Key Contributions
## Methods
## Findings
## Figures            ← ![[figures/fig_1.png]] + *Figure 1: caption*. skip이면 "_Figure/table 추출 생략됨. 필요 시 on-demand 추출 가능._" 한 줄
## References         ← citation-analysis가 채움
## Related            ← [[hub]]
```

vault 노트엔 연구 내용만 — 이 지침의 주석·내부 표기를 옮기지 않는다.

## Output
완료 한 줄: title · arXiv ID · PDF 경로·페이지 수 · figure 추출 {N}→유지 {M} (skip이면 사유) · 노트 경로. skip했으면 "figure/table이 필요하면 이 논문만 on-demand로 추출"을 덧붙인다.

## Failure handling
- `get_paper_by_id`가 `⏳`(SS 한도·일시 장애) → 잠시 후 재시도. `❌`만 미매핑이다. web search로 우회하지 않는다.
- PDF 다운로드 실패 → 중단.
- figure 0개 → 7·8 skip하고 계속. 전부 drop 판정이면 architecture 후보 1개는 keep.
- `wiki_write_note` 실패 → vault 경로·권한 안내.
