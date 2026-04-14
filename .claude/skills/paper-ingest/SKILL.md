---
name: paper-ingest
description: arXiv 논문 1편을 PDF·figure·요약 노트로 vault에 누적한다 (멀티모달 KB, ADR-010).
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
| 1 | `get_paper_by_id(arxiv_id)` | 메타데이터 + Citation 수 + TL;DR |
| 2 | `download_paper(arxiv_id)` | PDF를 `pdfs/<id>.pdf`에 저장 (캐시 hit이면 skip) |
| 3 | `read_paper(arxiv_id, max_pages=0)` | 전문 텍스트 추출 (요약 입력) |
| 4 | `extract_paper_figures(arxiv_id)` | 모든 raster figure를 `papers/<id>/figures/`에 저장 + caption 매칭 |
| 5 | (LLM 추론) | 본문에서 TL;DR / Key Contributions / Methods / Findings 요약 작성 (한국어) |
| 6 | (코드) `analysis.ranking.citation_velocity(meta, current_year)` | frontmatter `citation_velocity` 채움 (ADR-004) |
| 7 | `wiki_write_note(arxiv_id, frontmatter, body)` | vault에 `papers/<id>/index.md` 저장 |
| 8 | (선택) `citation-analysis` 스킬 위임 | references / cited_by 동적 토픽 채움 (ADR-009). 첫 ingest 시 자동 실행해도 좋고, 사용자 요청 때까지 미뤄도 됨. |

## Frontmatter 구성
ARCHITECTURE §5.1 스키마. ADR-009 동적 토픽 + ADR-010 figures.

```yaml
arxiv_id: <id>
ss_paper_id: <from step 1>
title: ...
authors: [...]
year: ...
venue: ...
citation_count: ...
influential_citation_count: ...
topics: [<자유 문자열 태그>]            # ADR-009
figures:                              # ADR-010: extract_paper_figures 결과 그대로
  - file: figures/fig_1.png
    caption: ...
ingested_at: <today>
pdf_path: ../../pdfs/<id>.pdf
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
## References (Phase 3에서 채움)
## Related
- [[topics/<slug>]]
```

## Output format (사용자 응답)
```
✅ ingest 완료: arXiv:{id} ({title})
   PDF: {pdf_path} (캐시 hit/저장)
   Figures: {N}개 추출 → papers/{id}/figures/
   노트: papers/{id}/index.md
```

## Failure handling
- step 1 `get_paper_by_id`가 "❌ 논문을 찾을 수 없습니다" 반환 → SS API 429 가능 → 사용자에게 재시도/시간 두기 안내 (CLAUDE.md "도구 한계 대응" — 임의 web search 우회 금지).
- step 2 PDF 다운로드 실패 → 그대로 중단, 본 스킬 abort.
- step 4 figure 0개 → 정보만 알리고 계속 진행 (scan-only 논문일 수 있음).
- step 6 wiki_write_note 실패 → 디스크 권한 / vault 경로 확인 안내.

## 후속 호출 제안
ingest 직후 사용자에게:
- "관련 흐름이 궁금하면 `research-flow` 스킬 (Phase 5)"
- "인용 분석을 깊게 보려면 `citation-analysis` 스킬 (Phase 3, ADR-009)"
