# PLAN — Research MCP 진행 상황

> Phase별 마이그레이션 체크리스트. **이 문서는 갱신 빈도가 높다** — Phase 완료 시마다 체크박스 토글 + "Next Action" 갱신.

관련 문서: [PRD](PRD.md) · [ARCHITECTURE](ARCHITECTURE.md) · [ADR](ADR.md) · [../CLAUDE.md](../CLAUDE.md)

---

## 현재 상태

- **현재 Phase**: **전체 완료 (Phase 0-6).** 운영 단계 진입. 후속 정리: GeekNews 제거 (ADR-012, 2026-05-31).
- **다음 액션**: 실 사용 → 사용자 정정 누적 시 `/self-improve` → ADR/CLAUDE.md 진화.
- **확정 결정 (D-1~D-12 + ADR-011/012)**: PLAN/ARCHITECTURE/ADR에 반영됨. parse_arxiv author/pdf_url 버그는 별도 spawn_task로 분기.
- **운영 환경**: `~/Documents/research-wiki/` 아래 PDF + figures + canvases 누적 중. **15 MCP tool 등록** (16 → 15, GeekNews 제외), **5 skill** (`paper-ingest`, `citation-analysis`, `daily-digest`, `research-flow`, `self-improve`), **1 command** (`/harness`).
- **server.py**: 470 → **21 LoC** (viz_tools register 추가).
- **테스트**: 240 unit PASS + 6 smoke deselected (`-m network`로 명시 실행).
- **인프라**: 디스크 캐시(`.cache/`) 활성, SS API key 자동 첨부(`SS_API_KEY` env), 429 백오프(1→2→4초). SS 호출은 모두 `sources.semantic_scholar.ss_get` 경유.
- **데이터 모델**: `core.models.Paper` (CitationEdge/FigureRef 포함) frontmatter ↔ in-memory 무손실 변환. `citation_tools`는 `sort=count|velocity`, 기본 `max_fetch=200` (D-3 lazy growth).
- **신규 SS 도구**: `get_citation_contexts(citing, cited)` — 본문 인용 문맥 (ADR-009 입력). `get_recommended_papers(paper, k)` — Recommendations API. 후자는 워크플로우 자동 편입 보류 (D-4 합의).
- **동적 토픽 워크플로우 (3.3)**: `analysis.grouping` (Claude 입력 패키지 빌더) + `wiki.linker.vault_backlinks` (D-2) + `citation-analysis` SKILL.md (drill-down UX, D-6). `paper-ingest`에 citation_velocity 채움 + citation-analysis 위임 step 추가.
- **신규 데이터 소스 (4)**: HF Daily Papers (`sources/hf_daily.py`, ADR-006 fallback API→HTML, 1일 TTL) + GeekNews RSS (`sources/geeknews.py`, 6시간 TTL). `daily-digest` skill로 vault `digests/<date>.md` 누적.
- **마지막 업데이트**: 2026-05-30
- **부가 발견 (별도 task로 분기)**: `parse_arxiv`의 정규식 quirk 2건 — `pdf_url` 영구 빈 값 (Phase 1.2 발견) + `authors` 영구 `[]` (Phase 3 직전 arXiv API 문서 대조 시 발견, `<n>` vs `<name>`). 두 버그가 같은 함수 같은 안티패턴(테스트 fixture가 잘못된 정규식에 끼워맞춰짐) → 단일 spawn_task로 묶어 분기. 본 세션은 Phase 3 집중.
- **결정 변경 이력**:
  - ADR-002 Accepted — vault는 `~/Documents/research-wiki/` (프로젝트 외부)
  - ADR-006 Accepted — HF Daily: 비공식 API + HTML fallback
  - ADR-007 Superseded by ADR-009 — 고정 6종 폐기 → 동적 토픽 + 초록 + 컨텍스트

---

## Phase 0 — Planning ✅

- [x] 요구사항 정리 → [PRD](PRD.md)
- [x] 목표 아키텍처 설계 → [ARCHITECTURE](ARCHITECTURE.md)
- [x] 결정 사항 문서화 → [ADR](ADR.md)
- [x] CLAUDE.md 초안 → [../CLAUDE.md](../CLAUDE.md)
- [x] 사용자 확인: ADR-002 / ADR-006 / ADR-009(ADR-007 supersede)

---

## Phase 1 — 모듈 분리 (≈1일)

기존 `server.py`(470 LoC)를 디렉토리 구조로 분해. 5개 도구 동작은 무변경. TDD red→green 강제 (CLAUDE.md 하드 룰).

### 1.1 core/ 골격 ✅ (2026-05-30)
- [x] `tests/test_core_skeleton.py` 작성 (RED 확인)
- [x] `core/{__init__,http,cache,models,config}.py` 생성 (GREEN, 7 passed)
- [x] `pyproject.toml`: pytest dev-dep 추가, `aiohttp` 명시 의존 추가(잠재 버그 수정), `pythonpath=["."]`
- 결과: `cache.get_or_fetch`는 passthrough stub, `http.get`은 NotImplementedError stub (1.2에서 채움). vault/PDF 경로는 ADR-002대로 외부.

### 1.2 sources/ 분리 ✅ (2026-05-30)
- [x] `tests/test_sources_arxiv.py` (RED, 4 tests)
- [x] `tests/test_sources_ss.py` (RED, SS_BASE + resolve_id 14 케이스 + fetch_network_papers 모킹 3 시나리오)
- [x] `sources/arxiv.py` ← `_parse_arxiv` (GREEN)
- [x] `sources/semantic_scholar.py` ← `SS_BASE` + `_resolve_id` + `_fetch_network_papers` (GREEN)
- [x] `core/http.py` 본문 교체 (NotImplementedError → 실 구현)
- [x] server.py: 함수 본문 제거 + `from sources.*`, `from core.http import get` 추가
- 결과: server.py 470 → 345 LoC. 30 tests PASS. `import server` 검증 OK.
- 부가 발견: `parse_arxiv`의 link 정규식이 `pdf_url`을 절대 추출 못함 → 회귀 테스트로 핀, 수정은 별도 task로 분기.

### 1.3 analysis/ + tools/ 분리 ✅ (2026-05-30)
- [x] `tests/test_analysis_format.py` + `tests/test_analysis_ranking.py` (RED, 20 tests)
- [x] `analysis/format.py` ← `_fmt_paper` (GREEN)
- [x] `analysis/ranking.py` ← `_render_sorted_list` (GREEN)
- [x] `tests/test_tools.py` (RED, 4 tests: 3 register + 1 server)
- [x] `tools/{search,citation,pdf}_tools.py` with `register(mcp)` 패턴 (GREEN)
- [x] [ARCHITECTURE.md](ARCHITECTURE.md) 디렉토리 트리에 `analysis/format.py` 추가
- 결과: server.py 286 → 18 LoC. 54 tests PASS. import alias로 함수 본문 0줄 변경.

### 1.4 server.py 슬림화 + smoke ✅ (2026-05-30)
- [x] `server.py` 18 LoC — `FastMCP(...)` + 3 register 호출만 (≤50 목표 달성)
- [x] `tests/test_server_smoke.py` — 5 tool 각 1회 실 호출, `@pytest.mark.network`
- [x] `pyproject.toml`: `network` marker 등록 + `addopts = "-m 'not network'"` (default skip)
- 회귀 검증: read_paper 통과 → 코드 이전 무회귀. SS 4건은 HTTP 429 (rate limit) → 외부 의존 한계, Phase 3 cache로 해소.

**Phase 1 완료 기준 충족**: Claude Desktop config 무변경, `uv run pytest tests/` 54 PASS + 5 deselected, `import server` OK, 5 tool 모두 `mcp.list_tools()`에 등록.

---

## Phase 2 — Persistence + Wiki (멀티모달, ≈2.5일)

PDF·노트·figure 영속화 + 첫 스킬. 모든 sub-step은 TDD red→green.

### 2.1 vault 기초 ✅ (2026-05-30)
- [x] `pyproject.toml`: `pyyaml>=6.0` 명시 의존 승격 (transitive로 이미 설치돼 있었음)
- [x] `tests/test_wiki_vault.py` (RED 8 tests) — vault root, ensure_vault, paper_dir, paper_note_path, write/read, list_papers
- [x] `wiki/vault.py` (GREEN) — `core.config.VAULT_PATH` 런타임 참조 (monkeypatch 가능)
- [x] `tests/test_wiki_frontmatter.py` (RED 7 tests) — ADR-009 references / ADR-010 figures round-trip + 한글 보존
- [x] `wiki/frontmatter.py` (GREEN) — `yaml.safe_load`/`safe_dump(allow_unicode=True, sort_keys=False)`
- [x] `tests/test_wiki_linker.py` (RED 8 tests) — `[[target]]` / `[[target|alias]]` 파싱, 백링크, dedup
- [x] `wiki/linker.py` (GREEN) — 정규식 `r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]"`
- 결과: 77 tests PASS (54 + 23). vault root는 `~/Documents/research-wiki/` (ADR-002 default).

### 2.2 PDF persistence ✅ (2026-05-30)
- [x] `tests/test_wiki_pdf_store.py` (RED 5) — `pdf_dir/path/exists/save` + 부모 디렉토리 생성
- [x] `tests/test_sources_arxiv_download.py` (RED 9: 8 normalize 케이스 + 1 sig) + 1 network marker
- [x] `tests/test_tools_pdf_cache.py` (RED 6) — invalid id 거부, 캐시 hit skip, miss 시 다운로드+저장, 두 번째 호출은 캐시 hit
- [x] `wiki/pdf_store.py` (GREEN) — `core.config.PDF_PATH` 런타임 참조
- [x] `sources/arxiv.py`에 `normalize_arxiv_id` + `download_pdf` 추가
- [x] `tools/pdf_tools.py` 재작성: `download_paper` 신설 + `read_paper` cache-aware (디스크 hit 시 다운로드 skip)
- [x] `tests/test_tools.py` 갱신: `download_paper` 등록 검증 (1.3에서 만든 테스트가 6번째 tool 신설을 반영하도록)
- 결과: 97 unit PASS + 2 PDF smoke PASS. SS rate-limit 영향 받지 않는 arxiv 직접 호출 경로 검증.

### 2.3 멀티모달 figure 추출 (ADR-010) ✅ (2026-05-30)
- [x] `tests/test_wiki_figures.py` (RED 7) — pymupdf로 in-memory fixture PDF 생성 (2 figs / empty / no-caption / 폴더 자동생성 / wrapper 경로)
- [x] `wiki/figures.py` (GREEN) — `extract_figures(pdf, out_dir)` + `extract_for_paper(arxiv_id)` 편의 wrapper. `[Figure N: ...]` 정규식 캡션 + xref dedup + CMYK→RGB 자동 변환
- [x] **실 검증**: BLIP-2 PDF에서 25 figure 추출, 모든 caption 매칭 (e.g. fig_1 → "Overview of BLIP-2's framework")
- [ ] frontmatter `figures: [...]` 자동 채움 → Phase 2.4의 paper-ingest skill 책임 (extract_for_paper 반환값을 frontmatter dump_note로 그대로 전달)

### 2.4 wiki tools + paper-ingest skill ✅ (2026-05-30)
- [x] `tests/test_tools_wiki.py` (RED 10) — 4 wiki tool 등록, slug 해석(단순 id → 폴더형 / `topics/x` 경로), round-trip, link 멱등성, server.py 통합
- [x] `tests/test_tools_extract_figures.py` (RED 4) — invalid id, PDF 없음 안내, 캐시된 PDF로 vault 저장, register
- [x] `tools/wiki_tools.py` (GREEN) — `wiki_read_note`, `wiki_write_note(slug, frontmatter, body)`, `wiki_list`, `wiki_link` (sync, register 패턴)
- [x] `tools/pdf_tools.py` 확장 — `extract_paper_figures(arxiv_id)` MCP tool
- [x] `server.py` register 추가 (wiki_tools)
- [x] `.claude/skills/paper-ingest/SKILL.md` — 6 step 시퀀스 + frontmatter 스키마 + 실패 처리 + 후속 호출 제안
- 결과: 118 unit PASS. 새 MCP tool 5종 노출 (read/write/list/link + extract_paper_figures), 총 11 tool.

**완료 기준 충족**: "BLIP-2 ingest" 한 마디로 PDF + 노트(index.md) + figures/*.png 동시 누적. Claude가 후속 세션에서 `Read("vault/papers/.../figures/fig_1.png")`으로 시각 정보 재활용 가능.

---

## Phase 3 — Citation Intelligence (≈3일, 4 sub-step)

velocity·contexts·그룹핑 + cache 인프라. ADR-004/009/003 적용. D-1~D-12 결정 반영.

### 3.0 인프라 보강 (cache + SS key + URL 정정) ✅ (2026-05-30)
**왜 0번**: SS API rate-limit이 Phase 1.4 smoke에서 이미 노출 (HTTP 429). 3.1~3.3은 SS 호출이 폭증 → cache 없으면 직격.

- [x] `tests/test_core_cache_disk.py` (RED 10) — `get_or_fetch` 디스크 캐시 hit/miss, TTL, force_refresh, 직렬화 round-trip, mkdir
- [x] `core/cache.py` (GREEN) — `.cache/<sha256>.json`, JSON 직렬화, mtime 기반 TTL, `force_refresh` 옵션
- [x] `core/http.py` 보강: `_default_headers(url)` 헬퍼 + `RETRY_DELAYS=(1,2,4)` 상수 + 429 응답 시 자동 재시도
- [x] `core/config.py`: `CACHE_DIR` (env `CACHE_DIR` 또는 `.cache/`) + `SS_API_KEY` (env) + `default_cache_dir()` 헬퍼 (D-11)
- [x] `sources/arxiv.py`: `build_pdf_url(id)` 헬퍼 + `download_pdf`가 `.pdf` suffix URL 사용 (D-12)
- [x] `tools/search_tools.py`: arxiv API URL `http://` → `https://` (D-12)
- [x] `sources/semantic_scholar.py`: `ss_get(url, params, ttl)` 헬퍼 노출. `fetch_network_papers`가 cache 경유. `tools/{search,citation}_tools.py`의 SS 호출도 `ss_get`으로 일원화.
- [x] `tests/conftest.py`: autouse fixture로 매 테스트마다 `CACHE_DIR`을 tmp 디렉토리로 격리
- [x] `.gitignore`: `.cache/` 추가

**달성**: 같은 SS 호출 2번 → 두 번째는 0 네트워크, 디스크 hit. SS_API_KEY 설정 시 자동 헤더 첨부 (host 일치 시만). 429 응답엔 RETRY_DELAYS 만큼 백오프 후 재시도. 144 unit PASS.

### 3.1 velocity ranking + Paper dataclass (D-1) ✅ (2026-05-30)
- [x] `tests/test_analysis_velocity.py` (RED 13) — `citation_velocity` 케이스 + `sort_by_velocity` + `render_sorted_list sort='velocity'`
- [x] `analysis/ranking.py` (GREEN): `citation_velocity(paper, current_year, bias_newcomer)`, `sort_by_velocity`, `render_sorted_list`에 `sort` + `current_year` 인자 (ADR-004)
- [x] `tests/test_core_models_paper.py` (RED 8) — Paper / CitationEdge / FigureRef + YAML round-trip
- [x] `core/models.py` (GREEN): `Paper` 전체 확장 + `CitationEdge` + `FigureRef` + `from_frontmatter`/`to_frontmatter` (default 필드 생략)
- [x] `tests/test_tools_citation_sort.py` (RED 6) — `sort=velocity` 옵션 + `max_fetch=200` 기본
- [x] `tools/citation_tools.py` (GREEN): `sort` + `max_fetch=200` + `current_year` 인자 추가 (D-3 lazy growth)
- 결과: 171 unit PASS (+27). 기존 `test_analysis_ranking.py` 회귀 없음 — `sort='count'` 기본 동작 유지.

### 3.2 contexts + recommendations tools ✅ (2026-05-30)
- [x] `tests/test_sources_ss_contexts.py` (RED 5) — paperId/ArXiv 매칭, 페이지네이션, 미발견, bad response
- [x] `sources/semantic_scholar.py`에 `get_contexts(citing_id, cited_id)` + `_cited_identifiers` 헬퍼 (sha/arxiv 둘 다 매칭)
- [x] `tests/test_tools_contexts.py` (RED 4) — `get_citation_contexts` 시그너처/렌더/빈/등록
- [x] `tools/citation_tools.py`에 `get_citation_contexts(citing_id, cited_id)` MCP tool — ADR-009 입력
- [x] `tests/test_tools_recommended.py` (RED 7) — SS_REC_BASE, `recommend_for_paper` URL/빈 응답, 도구 시그너처·렌더·등록
- [x] `sources/semantic_scholar.py`에 `SS_REC_BASE` + `recommend_for_paper(paper_id, k)` (D-4)
- [x] `tools/search_tools.py`에 `get_recommended_papers(paper_id, k=10)` (D-4, 워크플로우 자동 편입은 보류)
- [x] `tests/test_tools.py::test_server_module_registers_all_tools` — 신규 2 도구 회귀 검증 추가
- 결과: 187 unit PASS (+16). 총 11 → **13 MCP tool**. 캐시는 SS_CACHE_TTL=7일로 contexts/recommendations에도 적용.

### 3.3 grouping + citation-analysis skill (ADR-009) ✅ (2026-05-30)
- [x] `tests/test_analysis_grouping.py` (RED 9) — `pack_reference` (id/title/abstract/contexts, truncation, fallback) + `build_classification_prompt` (anchor·refs·세 필드 명시)
- [x] `analysis/grouping.py` (GREEN) — `pack_reference(ref, contexts)` + `build_classification_prompt(anchor_title, packed_refs)` (SoC: 분류는 Claude, 모듈은 입력 패키지만)
- [x] `tests/test_wiki_linker_integration.py` (RED 5) — vault 전체 스캔, 폴더형/평탄형 slug 규약, 파일 형식 필터, backlinks
- [x] `wiki/linker.py` (GREEN) — `_slug_for(md_path)` + `read_vault_notes()` + `vault_backlinks(target)` (D-2)
- [x] `.claude/skills/citation-analysis/SKILL.md` — 8 step 시퀀스 + drill-down UX (D-6: top-20 → "더" 시 1000으로 확장, cache 덕에 0 네트워크) + 실패 처리
- [x] `.claude/skills/paper-ingest/SKILL.md` 갱신 — step 6 (citation_velocity 채움) + step 8 (citation-analysis 위임)
- 결과: 201 unit PASS (+14). vault 통합 backlinks 자동, ADR-009 동적 토픽 워크플로우 완성.

**달성**: "이 논문의 인용 흐름 분석해" 한 마디로 동적 토픽 + 초록 요약 + `cited_for` + wikilink가 vault에 기록되는 워크플로우 설계 완료. cache 덕분에 같은 anchor 재방문 시 SS 0 네트워크. drill-down은 사용자 요청 시 `max_fetch=1000`으로 확장.

### 보류 결정 (Phase 4+ 또는 시기 도래 시)
- D-5 병렬 페이지 fetch — cache가 우선
- D-7 OpenAlex fallback — Phase 4
- D-8/D-9 Multi-agent (Pattern C/D) — Phase 5 / Phase 6

---

## Phase 4 — 신규 데이터 소스 ✅ (2026-05-30)

- [x] `tests/test_sources_hf_daily.py` (RED 5) — fallback chain 모킹 (API 우선, 빈/예외→HTML), default date=today, limit
- [x] `sources/hf_daily.py` (GREEN) — ADR-006 fallback chain. `_fetch_api` raw → `_normalize_api_item` → `_fetch_html` fallback. 1일 TTL cache.
- [x] `tests/test_sources_geeknews.py` (RED 6) — RSS 파싱 (한글), 옵션 author, 빈 입력, days 필터, 기본 days=7, bad response
- [x] `sources/geeknews.py` (GREEN) — RSS 2.0 파서 (RFC 822 pubDate, tz-aware). `fetch_recent(days=7)` + 6시간 TTL cache.
- [x] `tests/test_tools_feed.py` (RED 9) — register·시그너처·렌더·빈 응답·server 통합·15 tool 카운트
- [x] `tools/feed_tools.py` (GREEN) — `get_hf_daily_papers(date, limit=10)` + `get_geeknews(days=7)`
- [x] `server.py`: `feed_tools.register(mcp)` 추가 (server 20 LoC)
- [x] `.claude/skills/daily-digest/SKILL.md` — 5 step (HF + GeekNews → 흐름 요약 → `digests/<date>.md`) + 자동화(`schedule` 결합) 안내

**달성**: "오늘 신착 정리해" 한 마디로 HF + GeekNews 결합 노트가 vault `digests/<YYYY-MM-DD>.md`에 누적되는 워크플로우 완성. HF 비공식 API가 깨져도 HTML fallback으로 graceful degrade.

---

## Phase 5 — 시각화 ✅ (2026-05-31)

- [x] `tests/test_analysis_viz.py` (RED 14) — Mermaid graph direction/anchor/groups/edges, Canvas spec 필드, 직렬화, empty 케이스
- [x] `analysis/viz.py` (GREEN) — `build_mermaid(anchor, groups, direction='LR')` + `build_canvas_json(anchor, groups)` (ADR-005)
- [x] `tests/test_tools_viz.py` (RED 8) — register, server 통합, 시그너처, vault canvases/ 저장, default slug, 16 tool 회귀
- [x] `tools/viz_tools.py` (GREEN) — `build_citation_canvas(anchor, groups, slug, direction)` — Mermaid 응답 + `vault/canvases/<slug>.canvas` 저장
- [x] `server.py`: `viz_tools.register(mcp)` 추가 (server 21 LoC)
- [x] `.claude/skills/research-flow/SKILL.md` — 8 step (search→anchor→refs·cites velocity→contexts→토픽→canvas) + drill-down 확장

**달성**: "VLM 흐름 보여줘" 한 마디로 Mermaid graph (Claude Desktop이 즉시 렌더) + `vault/canvases/<anchor>.canvas` (Obsidian에서 자유 편집) 동시 산출. 노드는 카드 형식 (title·arxiv·year·cited·vel) — Liner 스타일 카드 그래프 충족.

---

## Phase 6 — 자가개선 하네스 ✅ (2026-05-31)

- [x] `.claude/skills/self-improve/SKILL.md` — 8 step (회고 수집 → 문서 매핑 → 승격 자격 검사 → diff 제안 → **사용자 승인** → 저장 → changelog append). ADR-008 거버넌스 명시.
- [x] `vault/_meta/changelog.md` append 절차 — `wiki_read_note("_meta/changelog")` + `wiki_write_note(...)` 조합 (신규 도구 추가 없이 기존 wiki tool 활용, surgical).
- [x] `.claude/commands/harness.md` — CLAUDE.md 워크플로우 5단계(탐색·토의·설계·실행·회고)를 명령형으로. Karpathy 4계명 적용, TDD 강제, 도구 한계 대응 명시.
- [ ] (옵션) `/loop` 야간 자동화는 사용자 결정 시 별도 ADR로 — 본 Phase에서는 보류.
- [ ] (옵션) 첫 self-improve 사이클 실측 — 본 Phase 마감 직후 사용자에게 제안.

**달성**: `/self-improve` 호출 한 마디로 회고 → diff 제안 → 승인 → CLAUDE.md/docs/* 갱신 + vault changelog 기록 사이클이 문서화됨. `/harness` 명령으로 큰 작업 시 5단계 강제 가능. 코드 변경 없이 (skill + command markdown만) Phase 마감.

---

## 누적 예상 작업량

| Phase | 예상 | 완료 |
|---|---|---|
| 0 Planning | - | ✅ |
| 1 모듈 분리 | 1일 | ✅ |
| 2 Persistence+멀티모달 | 2.5일 | ✅ |
| 3 Citation | 2일 | ✅ |
| 4 Sources | 1일 | ✅ |
| 5 Viz | 1일 | ✅ |
| 6 Harness | 0.5일 | ✅ |
| **합계** | **≈7.5일** | |

Phase 1·2가 끝나면 핵심 워크플로우(검색 → ingest → vault 누적)는 이미 동작.

---

## 작업 규칙 (이 문서에 한정)

- Phase 시작 전 [ADR](ADR.md)에서 관련 결정 상태 확인. `Proposed` 상태인 ADR이 막고 있으면 그 ADR 먼저 확정.
- Phase 종료 시 본 문서 체크박스 토글 + "현재 상태" 섹션의 `현재 Phase`·`다음 액션`·`마지막 업데이트` 갱신.
- 새 위험·발견사항은 [ADR 부록 A 리스크 레지스터](ADR.md#부록-a--리스크-레지스터)에 추가.
- 디렉토리/도구 카탈로그 변경은 [ARCHITECTURE](ARCHITECTURE.md)와 같은 PR에서.
