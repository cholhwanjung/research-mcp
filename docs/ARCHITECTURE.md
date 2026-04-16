# ARCHITECTURE — Research MCP

관련 문서: [PRD](PRD.md) · [ADR](ADR.md) · [PLAN](PLAN.md) · [../CLAUDE.md](../CLAUDE.md)

---

## 1. 레이어 모델

```
sources/   raw fetch (arxiv, ss, hf)
   ↓
analysis/  가공 (ranking, grouping, viz)
   ↓
wiki/      영속화 (Obsidian vault, frontmatter, wikilink)
   ↓
tools/     MCP exposure (얇은 wrapper)
   ↑
skills/    워크플로우 (Claude Desktop이 호출)
```

**의존 방향은 단방향**: 위에서 아래만 import. 역방향 import 금지(예: `sources/`가 `wiki/`를 부르면 안 된다).

---

## 2. 디렉토리 구조

```
research-mcp/
├── server.py                      # MCP 진입점 — tool 등록만, 로직 없음
├── CLAUDE.md                      # 코드베이스 규칙 (자가개선 타깃)
├── docs/                          # PRD / ARCHITECTURE / ADR / PLAN
├── pyproject.toml
│
├── core/
│   ├── http.py                    # aiohttp GET. `_default_headers(url)`로 SS_API_KEY 자동 첨부, RETRY_DELAYS=(1,2,4) 백오프
│   ├── cache.py                   # 디스크 캐시 (.cache/<sha256>.json). `get_or_fetch(key, fetcher, ttl, force_refresh)`
│   ├── models.py                  # Paper / CitationEdge / FigureRef (Phase 3.1). frontmatter ↔ in-memory round-trip.
│   └── config.py                  # vault/PDF/CACHE 경로 env, SS_API_KEY env
│
├── sources/
│   ├── arxiv.py                   # search, metadata, pdf, text-extract. `build_pdf_url(id)` (HTTPS + .pdf suffix)
│   ├── semantic_scholar.py        # meta, refs, cites. `ss_get(url, params, ttl)` 단일 진입점 + `get_contexts(citing, cited)` (ADR-009) + `recommend_for_paper(pid, k)` (D-4, SS_REC_BASE). `fetch_network_papers`는 light 필드 + `publication_date_or_year` 옵션 (ADR-014)
│   └── hf_daily.py                # 일일 인기 논문 (Phase 4). 비공식 JSON API → HTML 스크래핑 (paper ID + title) fallback (ADR-006). 1일 TTL cache.
│
├── analysis/
│   ├── format.py                  # 논문 dict → 한국어 텍스트
│   ├── ranking.py                 # citation 정렬·렌더. `citation_velocity(p, year, bias_newcomer)`, `sort_by_velocity`, `render_sorted_list(sort=count|velocity, min_velocity)` (ADR-004, ADR-014)
│   ├── grouping.py                # Claude 동적 토픽 분류 입력 빌더. `pack_reference(ref, contexts)` + `build_classification_prompt(anchor, packed)` (ADR-009)
│   └── viz.py                     # `build_mermaid(anchor, ref_groups, cite_groups, direction)` + `build_canvas_json(anchor, ref_groups, cite_groups)` — refs → anchor → cites 흐름 (ADR-005, ADR-014)
│
├── wiki/
│   ├── vault.py                   # Obsidian vault read/write
│   ├── frontmatter.py             # YAML schema 검증
│   ├── linker.py                  # [[wikilink]] 추출 + `read_vault_notes()` + `vault_backlinks(target)` (D-2 자동 백링크)
│   └── figures.py                 # pymupdf로 figure + caption 추출 (ADR-010)
│
├── tools/                         # MCP tool 정의 (얇은 wrapper)
│   ├── search_tools.py
│   ├── citation_tools.py
│   ├── pdf_tools.py
│   ├── wiki_tools.py
│   ├── feed_tools.py
│   └── viz_tools.py
│
├── .claude/
│   ├── settings.json
│   ├── commands/
│   │   └── harness.md             # CLAUDE.md 워크플로우 5단계 명령형 wrapper (Phase 6)
│   └── skills/                    # 워크플로우 — 5 skill 완비
│       ├── research-flow/SKILL.md
│       ├── paper-ingest/SKILL.md
│       ├── citation-analysis/SKILL.md
│       ├── daily-digest/SKILL.md
│       └── self-improve/SKILL.md
│
├── vault/                         # Obsidian vault (gitignore)
└── pdfs/                          # 원본 PDF (gitignore)
```

설계 원칙:
- **단일 MCP 서버 + 모듈 분리** — Claude Desktop config는 한 줄, 코드는 독립 (→ [ADR-001](ADR.md#adr-001))
- **tool은 얇게** — 비즈니스 로직은 `analysis/`·`wiki/`에. tool은 인자 검증 + 호출 + 출력 포맷만.
- **모든 외부 fetch는 `core/cache.py` 통과** — 동일 paper_id는 디스크 캐시 hit.

---

## 3. MCP Tool 카탈로그

### 3.1 카테고리 (직교성 룰)
한 tool은 정확히 **한 카테고리**에 속해야 한다.

| 카테고리 | Tool |
|---|---|
| **fetch** | `search_papers`, `get_paper_by_id`, `get_recommended_papers`, `get_hf_daily_papers`, `get_citation_contexts` |
| **graph** | `get_references_by_citations`, `get_citations_by_citations` |
| **artifact** | `download_paper`, `read_paper`, `extract_paper_figures` |
| **wiki** | `wiki_read_note`, `wiki_write_note`, `wiki_list`, `wiki_link` |
| **viz** | `build_citation_canvas` |

### 3.2 변경/신규 도구
| Tool | 상태 | 비고 |
|---|---|---|
| `search_papers` | 유지 | 기간 분류 그대로 |
| `get_paper_by_id` | 변경 | 응답에 `contexts` 일부 포함 |
| `read_paper` | 변경 | PDF를 `pdfs/`에 저장 + vault 노트 경로 반환 |
| `get_references_by_citations` | 변경 | `sort=velocity`(기본), `min_velocity=10` 필터 (ADR-014) |
| `get_citations_by_citations` | 변경 | 위 + `exclude_recent_year=True` (SS publicationDate desc 응답 → 최근 1년 SS 측 컷, ADR-014) |
| `download_paper` | **신규(2.2)** | PDF만 다운로드 + vault stub 생성 |
| `get_hf_daily_papers` | **신규(4)** | `date=today, limit=10`. ADR-006 fallback chain (API → HTML paper card 추출). |
| ~~`get_geeknews`~~ | **제거(2026-05-31)** | news.hada.io/rss endpoint가 default-UA를 403 차단, UA 헤더 추가에도 미해결 → 도구·워크플로우에서 제외. |
| `get_citation_contexts` | **신규(3.2)** | 특정 인용의 본문 문맥 (ADR-009 입력). `(citing_id, cited_id)` → snippets[] |
| `get_recommended_papers` | **신규(3.2, D-4)** | SS Recommendations API. `(paper_id, k=10)` → 콘텐츠 유사 추천. 워크플로우 자동 편입 보류. |
| `wiki_read_note` / `wiki_write_note` / `wiki_list` / `wiki_link` | **신규(2.4)** | Obsidian vault CRUD. slug 단순 식별자는 `papers/<id>/index.md` 자동 매핑 |
| `extract_paper_figures` | **신규(2.4)** | 캐시된 PDF에서 figure 추출 → `papers/<id>/figures/fig_<n>.png` (ADR-010) |
| `build_citation_canvas` | **변경(ADR-014)** | `(anchor, ref_groups, cite_groups)` 시그니처. refs → anchor → cites 인과 흐름. Mermaid 응답 + `vault/canvases/<slug>.canvas` 저장 (ADR-005, ADR-014). |

---

## 4. Skill 카탈로그 (요약)

각 SKILL.md는 고정 섹션: `When to invoke` · `Inputs` · `Steps (tool sequence)` · `Output format` · `Failure handling`.

| Skill | 핵심 시퀀스 |
|---|---|
| `research-flow` | search → anchor 선정 → refs·cites(velocity) → contexts 샘플링 → 동적 토픽 산출 → `build_citation_canvas` |
| `paper-ingest` | `get_paper_by_id` → `download_paper` → `read_paper` → 요약 → 인용 분석(ADR-009) → `wiki_write_note` |
| `citation-analysis` | refs/cites edge별로 `get_citation_contexts` + 인용된 논문 초록 fetch → 토픽·요약·`cited_for` 생성 → vault 갱신 |
| `daily-digest` | `get_hf_daily_papers` → 메타 보강 → `wiki_write_note("digests/<date>")` (GeekNews는 2026-05-31 제외) |
| `self-improve` | 세션 회고 입력 → `docs/*` + CLAUDE.md diff → 사용자 확인 → 저장 + changelog |

상세는 각 `.claude/skills/<name>/SKILL.md`에 둔다 (코드와 함께 진화).

---

## 5. 데이터 모델

### 5.1 `papers/<arxiv_id>/index.md` (Obsidian, 폴더형)
[ADR-010](ADR.md#adr-010) 폴더형 레이아웃 — 한 논문 = 한 폴더. 인용 분석은 [ADR-009](ADR.md#adr-009) 동적 토픽.

```
vault/papers/2301.12597/
  index.md
  figures/
    fig_1.png
    fig_2.png
    ...
```

`index.md` frontmatter:
```yaml
---
arxiv_id: 2301.12597
ss_paper_id: 0aefb...
title: "BLIP-2: ..."
authors: [Junnan Li, ...]
year: 2023
venue: ICML
citation_count: 1234
influential_citation_count: 200
citation_velocity: 411.3        # citations / max(1, current_year - pub_year)
topics: [vlm, vision-language, frozen-encoder]   # 본 논문 자체의 토픽 태그 (자유 문자열)
references:                     # ADR-009: list of dynamic-topic edges
  - paper_id: 2106.04560
    topic: "frozen visual encoder reuse"
    abstract_summary: "CLIP은 ..."
    cited_for: "BLIP-2의 frozen ViT 초기화 근거로 인용"
cited_by:                       # 동일 스키마
  - paper_id: 2310.xxxxx
    topic: "Q-Former 후속 변형"
    abstract_summary: "..."
    cited_for: "..."
figures:                        # ADR-010: 모든 figure + PDF caption
  - file: figures/fig_1.png
    caption: "Figure 1: BLIP-2 architecture overview."
  - file: figures/fig_2.png
    caption: "Figure 2: Q-Former pretraining objectives."
ingested_at: 2026-05-30
pdf_path: ../pdfs/2301.12597.pdf
status: read | skim | queued
---
```

본문 구조 (고정):
```markdown
# {title}
## TL;DR
## Key Contributions
## Methods
## Findings
## Figures
![[figures/fig_1.png]]
*Figure 1: BLIP-2 architecture overview.*
## References (by topic)
### {dynamic topic name}
- [[2106.04560-CLIP]] — cited_for 한 줄
## Cited By (top-5 by velocity, by topic)
## Related
- [[topics/<slug>]]
```

### 5.2 다른 노트 타입
- `topics/<slug>.md` — MOC(Map of Content). 자동 갱신 백링크 인덱스.
- `digests/<YYYY-MM-DD>.md` — HF Daily + GeekNews 일일 노트.
- `canvases/<topic>.canvas` — Obsidian Canvas JSON (시각화 출력).
- `_meta/changelog.md` — 자가개선 이력.
- `papers/<arxiv_id>/figures/fig_<n>.png` — ADR-010 멀티모달 자산. Claude는 `Read` tool로 PNG 로드 가능.

---

## 6. 시각화 산출물

두 가지 동시 출력 (→ [ADR-005](ADR.md#adr-005)):

1. **Mermaid graph** — 마크다운에 임베드, GitHub/Obsidian 즉시 렌더.
   ```mermaid
   graph LR
     anchor["BLIP-2 (2023, cited 1234)"]
     anchor --> g1[Model refs]
     anchor --> g2[Data refs]
     g1 --> p1["CLIP (2021)"]
   ```

2. **Obsidian Canvas JSON** — `vault/canvases/<topic>.canvas`. 사용자가 옵시디언에서 카드 자유 배치.

---

## 7. 핵심 알고리즘

### 7.1 Citation Velocity
```
velocity(p) = citation_count(p) / max(1, current_year - publication_year(p))
```
1년차 신생 논문 과대평가 방지를 위해 옵션으로 `(year + 1)` 가산도 허용.

### 7.2 인용 분석 (동적 토픽)
- Semantic Scholar `contexts` API로 각 인용의 본문 문맥 스니펫 fetch.
- 인용된 논문 메타에서 초록을 받아 1-3줄 요약.
- Claude가 둘을 결합해 **자유 문자열 토픽 태그**(예: `"frozen visual encoder reuse"`)와 `cited_for` 1-2줄 노트 생성 (→ [ADR-009](ADR.md#adr-009), [ADR-003](ADR.md#adr-003)).
- 고정 카테고리 없음. 동일 토픽은 vault `topics/<slug>.md` MOC의 backlink로 자연 누적.

---

## 8. 자가개선 하네스 (문서 측)

코드 측 자가개선 메커니즘은 [CLAUDE.md](../CLAUDE.md)의 "자가개선 루프" 섹션 참조. 본 문서가 다루는 부분은 **문서 자체의 진화**.

| 문서 | 갱신 트리거 |
|---|---|
| `docs/PRD.md` | 요구사항이 변할 때만 (드물게) |
| `docs/ARCHITECTURE.md` | 디렉토리/레이어/도구 카탈로그가 바뀔 때마다 코드 변경과 같은 PR에서 |
| `docs/ADR.md` | 새 결정이 발생하면 ADR-N 추가 (기존 ADR은 supersede로 갱신) |
| `docs/PLAN.md` | Phase 체크박스 토글, 다음 액션 갱신 |
| `CLAUDE.md` | 사용자 정정/실패/관습이 누적될 때 `self-improve` 스킬로 |
