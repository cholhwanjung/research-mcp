# ADR — Research MCP

> Architecture Decision Records. 각 ADR은 **불변**이다. 결정이 뒤집히면 새 ADR을 추가하고 기존 ADR의 Status를 `Superseded by ADR-N`으로 갱신한다.

관련 문서: [PRD](PRD.md) · [ARCHITECTURE](ARCHITECTURE.md) · [PLAN](PLAN.md) · [../CLAUDE.md](../CLAUDE.md)

| # | Status | Title |
|---|---|---|
| ADR-001 | Accepted | 단일 MCP 서버 + 모듈 분리 |
| ADR-002 | Accepted | Obsidian vault는 `~/Documents/research-wiki/` (프로젝트 외부) + env 오버라이드 |
| ADR-003 | Accepted | 인용 의도 분류는 Claude 대화 측에서 수행 |
| ADR-004 | Accepted | Citation velocity 정의 = citations / max(1, year_diff) |
| ADR-005 | Accepted | 시각화는 Mermaid + Obsidian Canvas JSON 동시 출력 |
| ADR-006 | Accepted | HF Daily 수집: 비공식 API 우선, HTML 스크래핑 fallback |
| ADR-007 | Superseded by ADR-009 | 인용 의도 카테고리 6종 표준화 |
| ADR-008 | Accepted | 자가개선 트리거는 수동 (`self-improve` 스킬) |
| ADR-009 | Accepted | 인용 분석: 동적 토픽 + 초록 요약 + 컨텍스트 노트 (고정 어휘 없음) |
| ADR-010 | Accepted | 멀티모달 wiki — 모든 figure 추출, 폴더형 노트 레이아웃, PDF caption만 (LLM vision 보류) |
| ADR-011 | Accepted | HTTP 호출에 항상 User-Agent 헤더 첨부 (`research-mcp/0.1`) — 일부 서비스 default-UA 403 방지 |
| ADR-012 | Accepted | GeekNews 소스 제외 — endpoint 지속 403, UA 헤더로도 미해결 (2026-05-31) |
| ADR-013 | Accepted | 테스트 삭제 정책 — 구현 완료 + 사용자 명시 승인 시에만. TDD 룰은 유지 (2026-05-31) |
| ADR-014 | Accepted | research-flow 방향 + velocity 필터 + SS citations endpoint 페이지네이션 (2026-06-04) |
| ADR-015 | Accepted | figure 추출 — caption 매칭된 것만 저장 + LLM이 핵심만 선별 prune. ADR-010 일부 supersede (2026-06-07) |
| ADR-016 | Accepted | vault 폴더·파일명은 title-slug. arxiv_id는 frontmatter 식별자로 보존. ADR-010 명명 부분 supersede (2026-06-07) |
| ADR-017 | Superseded by ADR-018 | figure 추출 — 위치 기반 매칭 + multi-component(`fig_N_a/b/c.png`) 보존 (2026-06-07) |
| ADR-018 | Superseded by ADR-019 | figure·table 영역 crop + page-as-image 옵션 도구 (2026-06-07) |
| ADR-019 | Accepted | figure·table bbox는 Gemini Vision으로 추정. 휴리스틱 전면 삭제 (2026-06-07) |

---

## ADR-001 — 단일 MCP 서버 + 모듈 분리
**Status**: Accepted (2026-05-30)

### Context
요구사항 R3은 "툴끼리의 독립성"을 강조한다. 단순 해석은 데이터 소스별로 MCP 서버를 따로 띄우는 것 (멀티 서버). 그러나 Claude Desktop은 각 서버를 `claude_desktop_config.json`에 등록해야 하므로 설정 관리 비용이 발생한다.

### Decision
**단일 MCP 서버**(`server.py`)에 모든 tool을 등록하되, 코드는 `sources/`, `analysis/`, `wiki/`, `tools/` 디렉토리로 **모듈 분리**한다. `server.py`는 등록만 한다.

### Reasoning
- 단일 사용자, Claude Desktop 1개 환경에서 설정 단순화 우선.
- 모듈 분리만으로도 R3의 "독립성"은 코드 레벨에서 달성됨.
- 향후 서버 분리가 필요해지면 `tools/` 그룹별로 분할 가능 (역방향 호환 깨지지 않음).

### Tradeoffs
- 한 서버 프로세스 — 한 모듈 버그가 전체 영향. 캐치는 tool 레벨 try/except로.
- 멀티 서버였다면 가능한 "특정 데이터 소스만 비활성화"는 환경변수 기반 등록 토글로 대체.

---

## ADR-002 — Obsidian vault 경로
**Status**: Accepted (2026-05-30)

### Context
vault는 본 프로젝트 전용 산출물이 아니라 **사용자의 장기 개인 지식 기록**. 프로젝트 디렉토리 안에 묶으면 다른 LLM 연구 흐름이나 노트를 같이 누적하기 어렵다.

### Decision
기본값: `~/Documents/research-wiki/` (프로젝트 **외부**, 사용자 홈 아래). 환경변수 `OBSIDIAN_VAULT_PATH`로 오버라이드 가능.

### Reasoning
- 프로젝트 외부에 둬야 다른 영역의 wiki와 합쳐 누적 가능 (Karpathy 철학).
- 프로젝트 리포 삭제·재설치 시에도 wiki 무관.
- 절대경로 기본값이라 사용자가 즉시 어디에 누적되는지 인지 가능.

### Tradeoffs
- 프로젝트 외부 = `.gitignore` 무관 (애초에 트래킹 대상 아님).
- 신규 사용자가 `~/Documents/research-wiki/`에 다른 데이터를 두고 있을 위험 — 시작 시 비어있지 않으면 경고만 출력하고 진행.

---

## ADR-003 — 인용 의도 분류 위치
**Status**: Accepted (2026-05-30)

### Context
"특정 논문이 무엇을 위해 인용했는가" 분류는 두 가지 길이 있다.
- (A) tool 내부에서 LLM API 호출 — 결정론적, 캐시 용이, 별도 비용 발생.
- (B) Claude 본 대화에 raw `contexts`만 넘기고 분류 위임 — 매번 다른 결과 가능성, 비용 효율.

### Decision
**(B) Claude 대화 측에서 분류**. tool은 Semantic Scholar `contexts` 필드를 동봉해 제공.

### Reasoning
- 별도 LLM 호출 인프라/키 관리 회피.
- 사용자가 vault에서 분류 결과를 직접 수정 가능 (R2의 "사람이 수정 가능" 요구와 부합).
- 캐시는 raw contexts 수준에서 유효 (분류 결과 캐시는 vault 노트가 담당).

### Tradeoffs
- 분류 일관성은 prompt(=Skill)의 품질에 의존.
- Skill에 분류 기준 명시 필요 → ADR-007의 6종 카테고리.

---

## ADR-004 — Citation Velocity 정의
**Status**: Accepted (2026-05-30)

### Context
"기간 대비 인용수" top-5 정렬을 위해 velocity 지표가 필요하다. 단순 `citations / years_since_pub`은 발표 당해(year_diff=0) 논문에서 0-division 또는 ∞로 발산.

### Decision
```
velocity(p) = citation_count(p) / max(1, current_year - publication_year(p))
```
옵션 플래그 `bias_newcomer=True` 시 `(year_diff + 1)`로 1년차 논문 가산을 추가 완화.

### Reasoning
- 0-division 방지.
- 단순/투명한 정의 — 사용자가 결과를 검증 가능.

### Tradeoffs
- 분기 가중치(예: 첫해 2배)나 분야별 정규화는 미반영. 필요 시 ADR-N로 후속 결정.

---

## ADR-005 — 시각화 산출물
**Status**: Accepted (2026-05-30)

### Context
요구사항 R1은 "Liner 스크린샷처럼" 카드 그래프 UI를 원함. 기술 선택지: Mermaid · Obsidian Canvas · D3/web · GraphViz.

### Decision
`build_citation_canvas` tool은 **Mermaid graph (텍스트)** + **Obsidian Canvas JSON 파일** 두 가지를 동시에 생성·반환한다.

### Reasoning
- Mermaid: Claude Desktop 답변에서 즉시 렌더 가능 (대화 중 빠른 확인).
- Canvas JSON: Obsidian에서 사용자가 카드 재배치/주석 가능 (영구 저장 + 편집).
- 둘 다 텍스트 포맷 → git diffable, 재현 가능.

### Tradeoffs
- 웹 기반 인터랙티브 viz는 미지원 (R3·R5의 단순함 우선).

---

## ADR-006 — HF Daily Papers 수집 방식
**Status**: Accepted (2026-05-30)

### Context
Hugging Face는 Daily Papers의 공식 안정 API를 제공하지 않는다.

### Decision
`sources/hf_daily.py`는 fallback chain:
1. `https://huggingface.co/api/daily_papers` (비공식, 응답 형식 변경 위험)
2. `https://huggingface.co/papers?date=YYYY-MM-DD` HTML 스크래핑

응답 캐시는 1일 TTL.

### Reasoning
- 비공식 API가 깨지면 자동으로 스크래핑으로 우회 → 다운타임 최소화.
- 1일 캐시로 같은 날짜 반복 호출 시 rate limit 회피.

### Tradeoffs
- 비공식 엔드포인트가 어느 날 사라질 위험 — fallback이 있어 graceful degrade.
- HTML 구조 변경 시 스크래핑 코드 유지보수 필요 → CLAUDE.md에 "HF DOM 변경 감지 시 self-improve 호출" 규칙 추가 후보.

---

## ADR-007 — 인용 의도 카테고리 표준
**Status**: Superseded by [ADR-009](#adr-009) (2026-05-30)

### Context
인용 분류 결과의 일관성을 위해 카테고리 어휘를 고정한다.

### Decision
6종으로 시작: `model · data · method · benchmark · comparison · discussion`.
- `model` — 모델 아키텍처 참고
- `data` — 데이터셋·전처리 참고
- `method` — 학습/추론 기법 참고
- `benchmark` — 평가 지표/태스크 참고
- `comparison` — 베이스라인/대조군
- `discussion` — 관련 연구 언급, 향후 작업

### Reasoning
- 6종은 인지 부담이 낮고 분류 정확도가 높음.
- 부족 시 ADR-N으로 확장.

### Tradeoffs
- 분야별로 부족할 수 있음 (예: 이론 분야의 "proof technique").
- "Other"는 두지 않음 — 분류 실패 시 명시적으로 빈 그룹.

---

## ADR-008 — 자가개선 트리거
**Status**: Accepted (2026-05-30)

### Context
CLAUDE.md / docs/* 갱신을 자동(cron)으로 할지, 수동(스킬 호출)으로 할지.

### Decision
Phase 1~6 동안은 **수동만** — 사용자가 `self-improve` 스킬을 명시적으로 호출.
야간 `/loop` 자동화는 본 결정의 후속(다른 ADR)으로 검토.

### Reasoning
- 자동 갱신은 잘못된 학습을 누적할 위험.
- 사용자 승인이 들어가야 문서 신뢰도가 유지됨.

### Tradeoffs
- 사용자가 잊으면 문서가 드리프트.
- 완화책: 매 Phase 종료 시 `self-improve` 호출을 PLAN.md 체크리스트에 강제 포함.

---

## ADR-009 — 인용 분석: 동적 토픽 + 초록 + 컨텍스트
**Status**: Accepted (2026-05-30). [ADR-007](#adr-007)을 supersede.

### Context
ADR-007은 6종 고정 카테고리(`model/data/method/benchmark/comparison/discussion`)로 시작했다. 그러나 사용자 목표는 "어떤 **연구 흐름** 속에서 이 연구가 나왔는지"를 파악하는 것이며, 흐름의 어휘는 분야(VLM·RLHF·diffusion 등)·시기·앵커 논문마다 다르다. 고정 어휘는 그 흐름의 결을 짓밟는다.

### Decision
인용 분석은 카테고리 분류가 아니라 **요약 + 맥락 노트** 산출이다. 각 인용 edge에 대해 다음 셋을 LLM이 생성한다:

1. **abstract_summary** — 인용된 논문 초록의 1-3줄 요약.
2. **cited_for** — 본문(`contexts`)에서 어떤 맥락으로 이 논문을 끌어왔는지 1-2줄 노트.
3. **topic** — 위 둘에서 LLM이 추출한 **자유 문자열 태그** (예: `"frozen visual encoder reuse"`, `"two-stage pretraining"`). 어휘 사전 강제 없음.

vault의 `topics/` MOC가 backlink로 동일 토픽을 자연 누적 → 사후 통합/리네임 가능.

### Reasoning
- "연구 흐름 시각화"라는 R1의 의도와 정합. 고정 어휘는 시각화 결과를 평준화시킨다.
- Karpathy wiki 철학(원자성·자연 누적)과 부합.
- ADR-003(분류는 Claude 대화 측)의 자연스러운 귀결 — Claude가 자유 토픽까지 생성.

### Tradeoffs
- 동일 개념에 다른 태그(`"frozen encoder"` vs `"frozen visual backbone"`)가 누적될 수 있음.
  → 완화: vault `topics/<slug>.md`를 사용자가 직접 통합·리네임 (Obsidian rename 시 backlink 자동 갱신).
- "이 논문은 모든 인용에 X 카테고리로 분류" 같은 단순 집계는 불가 → 시각화는 토픽 클라우드/유사 토픽 클러스터링으로 대체.

### 데이터 모델 영향
- `ARCHITECTURE.md` §5.1 frontmatter의 `ref_groups`/`cited_by_groups`(고정 dict 형) → **list of {paper_id, topic, abstract_summary, cited_for}** 로 변경.

---

## ADR-010 — 멀티모달 wiki (figure 추출)
**Status**: Accepted (2026-05-30). 추출 범위는 [ADR-015](#adr-015), 폴더 명명은 [ADR-016](#adr-016), 매칭 알고리즘은 [ADR-017](#adr-017)로 부분 supersede.

### Context
[PRD R2](PRD.md#3-핵심-요구사항) Karpathy LLM wiki를 **멀티모달 knowledge base**로 확장한다. 논문의 architecture diagram·plot·algorithm box는 텍스트 요약만으로는 보존이 부족 — 이미지 자체를 vault에 누적해야 후속 세션에서 시각 정보를 다시 활용할 수 있다.

### Decision
**1. 추출 범위**: PDF 내 **모든 raster figure 추출** (필터링 없음). 중요도 판단은 검색·조회 시점에 LLM이 동적으로 수행 — atomicity 철학과 정합.

**2. vault 레이아웃**: 한 논문 = 한 폴더.
```
vault/papers/<arxiv_id>/
  index.md            # 노트 본문 (기존 papers/<id>.md 위치)
  figures/
    fig_<n>.png       # 추출 순서대로 1-base
```

**3. 캡션·맥락**: 본 ADR은 **PDF 텍스트의 caption만 자동 파싱** (예: "Figure 1: ..."). LLM vision으로 시각 설명 생성은 보류 (비용·복잡도 우선) — 필요 시 후속 ADR에서 도입.

**4. 멀티모달 액세스**: Claude는 vault note에서 `![[figures/fig_1.png]]` 링크를 통해 이미지 경로를 얻고, `Read` tool로 PNG를 로드해 시각 분석. 별도 도구 추가 불필요.

**5. Phase**: Phase 2 `paper-ingest` 워크플로우에 sub-step 추가 — figure 추출은 PDF 텍스트 추출과 같은 호출에서 처리.

### Reasoning
- "모두 추출"은 휴리스틱 누락 위험을 제거 + Karpathy 원자성 철학 부합.
- 폴더형 레이아웃은 논문 단위 관리(삭제·아카이브·이전)를 깔끔하게.
- LLM vision 보류는 비용·구현 단순성 우선 — caption만으로도 검색 가능성 일부 확보. 캡션이 빈약한 figure는 사용자가 vault에서 직접 보충 가능.
- 멀티모달 액세스는 기존 `Read` tool + Obsidian 이미지 임베드로 충분.

### Tradeoffs
- 저장 용량: 논문당 ~5MB 추가 (figure 평균 ~200KB × 20-30장). vault가 외부 디렉토리(`~/Documents/research-wiki/`)라 디스크 압박 미미.
- caption이 "Architecture overview." 처럼 짧으면 검색력 부족 — 후속 ADR에서 LLM vision 보강 가능 (이 ADR을 supersede 안 함, **확장**).
- 벡터 그림(PDF 내부 vector 객체)은 기본 raster 추출에서 누락 가능. 후속 작업으로 페이지 영역 렌더링 fallback 추가 가능.

### 구현 영향
- `wiki/figures.py` (Phase 2 신설) — pymupdf로 figure + caption 추출.
- `ARCHITECTURE.md` §5.1 frontmatter에 `figures: [{file, caption}]` 필드 추가.
- 기존 `papers/<id>.md` 평면 레이아웃은 본 ADR로 폐기 (Phase 2 시작 시 적용; 1.4까지는 vault 미사용이라 마이그레이션 무관).

---

## ADR-011 — HTTP User-Agent 헤더 의무화
**Status**: Accepted (2026-05-31)

### Context
`news.hada.io/rss`가 default Python aiohttp UA에 HTTP 403 Forbidden을 반환. Phase 4 자동화의 직접 원인이고, 다른 RSS/HTML 서비스에서도 같은 차단이 일어날 가능성이 높다.

### Decision
`core/http._default_headers`가 모든 호출에 `User-Agent: research-mcp/0.1 (+...)`를 자동 첨부. SS API key와 같은 layer.

### Reasoning
- 봇 차단 우회의 표준 관행.
- 단일 진입점(`_default_headers`) 변경으로 모든 source/tool이 일괄 혜택.
- SS API key는 host 일치 시만 첨부 → UA는 항상 첨부로 정책 분리.

### Tradeoffs
- UA 값이 식별 가능한 문자열 — 서비스 측에서 별도 rate limit 적용 가능. 발생 시 UA 회전 또는 ADR-N로 재검토.

---

## ADR-012 — GeekNews 소스 제외
**Status**: Accepted (2026-05-31), Supersedes part of R4(PRD)

### Context
GeekNews(`news.hada.io/rss`)는 3차 reconnect 후에도 HTTP 403 지속. URL 변경(`feedburner → news.hada.io/rss`), Atom 1.0 파서 추가, UA 헤더 첨부(ADR-011) 모두 미해결. 같은 IP에서 잠시 작동했다가 차단된 패턴 — IP rate limit 또는 cloud-based bot detection 의심.

### Decision
GeekNews 관련 코드·테스트·skill step·문서 일괄 제거. `daily-digest` skill은 HF Daily만 사용.

### Reasoning
- 3회 재시도 후에도 차단 → CLAUDE.md "도구 한계 대응" 룰 (2회 이상 실패 시 진단·제안)을 사용자가 명시 결정으로 진행.
- 다른 한국어 IT 뉴스 소스(예: news.ycombinator.com Korean tagged, dev.to)는 별도 ADR로 검토 가능.
- 임의 우회(브라우저 자동화, IP 회전) 금지 — 비용 대비 가치 낮음.

### Tradeoffs
- R4 데이터 소스 4종 → 3종으로 축소. 한국어 IT 트렌드 수집 채널 1개 손실.
- 후속에서 RSS 대신 다른 endpoint 발견 시 새 ADR로 재도입 가능 (본 ADR은 supersede 안 함).

### 구현 영향
- 삭제: `sources/geeknews.py`, `tests/test_sources_geeknews.py`
- 수정: `tools/feed_tools.py` (get_geeknews 함수·register 제거), `tests/test_tools_feed.py`/`test_tools_viz.py`/`test_tools.py` (회귀 카운트 조정), `.claude/skills/daily-digest/SKILL.md` (HF Daily-only), `docs/PRD.md`/`docs/ARCHITECTURE.md`/`docs/PLAN.md` (소스 목록 갱신)
- MCP tool: 16 → **15**

---

## ADR-013 — 운영 단계 진입 후 테스트 삭제 정책
**Status**: Accepted (2026-05-31)

### Context
Phase 0-6 전체 완료 + 240 unit + 6 smoke tests PASS 검증 후 운영 단계 진입. 사용자 멘탈 모델: "한 번 테스트가 끝난 코드를 남겨두는 것은 잔재". 그러나 [TDD 하드 룰](../CLAUDE.md)은 *구현 전* RED→GREEN을 강제하는 별개 결정.

### Decision
- **TDD 룰은 유지** — 다음 구현 시 반드시 테스트를 *먼저* 작성하고 RED→GREEN 거친다.
- **테스트 삭제는 두 조건 모두 만족 시에만**:
  1. 해당 구현이 *완료* 상태 (Phase 또는 sub-step closed).
  2. 사용자가 *명시 승인* (자동/임의 삭제 금지).
- 본 ADR과 동시에 `tests/` 디렉토리 전체 삭제 적용 — 사용자 명시 승인 (본 세션 2회 정정).

### Reasoning
- TDD는 *작성 시점*의 검증력 확보 도구 — 작성 직후엔 자산.
- 운영 정착 후 회귀 안전망이 코드 외 (ADR · changelog · 실 운영)로 이동 → 테스트가 자산에서 잔재로 전환되는 시점이 *반드시* 존재.
- "사용자 명시 승인"으로 임의 삭제는 차단 — 자가개선 사이클의 ADR-008 거버넌스와 정합.

### Tradeoffs
- 회귀 발견 지연 가능 — 다음 변경 시 RED→GREEN 재적용으로 복원.
- 발표 KPI "240 tests PASS"가 *과거 사실*로만 남음 — 표현은 "TDD red→green 사이클 검증 후 정리"로 조정.
- 본 ADR 자체가 향후 같은 결정 반복 시 *근거*가 됨 — sub-step 단위 정리에서도 적용 가능.

### 구현 영향
- 삭제: `tests/` 전체 (33 파일 — 240 unit + 6 smoke + conftest.py + __pycache__).
- 수정: `pyproject.toml`의 `[tool.pytest.ini_options]` 섹션 제거, `dev = ["pytest>=8.0"]` → `dev = []`.
- CLAUDE.md TDD 하드 룰에 "삭제는 사용자 명시 승인 시" 한 줄 보강.
- 다음 구현부터 새 테스트 작성 → 같은 사이클 (RED → GREEN → 완료 → 사용자 승인 시 정리).

---

## ADR-014 — research-flow 인과 방향 + velocity 필터 + SS citations 페이지네이션
**Status**: Accepted (2026-06-04)

### Context
실 사용 단계 (BLIP-2 anchor)로 검증한 결과 세 가지 문제가 동시에 드러남:

1. **viz 방향** — `build_mermaid` / `build_canvas_json`이 `groups` 단일 인자만 받아 references와 citations를 같은 화살표 방향(`anchor → group → paper`)으로 그렸다. 사용자는 "BLIP-2가 인용한 논문 → BLIP-2 → BLIP-2를 인용한 논문" 인과 흐름을 원함.
2. **velocity 노이즈** — citation 결과에 발표 1년 이내 인용수 0~1인 논문 다수 포함. 노이즈 비율 높음.
3. **SS citations 호출 비용** — SS `/paper/{id}/citations` endpoint는 **publicationDate 내림차순**으로 응답 (캐시 검증: BLIP-2 citations 첫 200건 모두 2026년 인용수 0). 의미 있는 논문(velocity 큰)은 페이지 깊은 곳에 있어, velocity 필터를 클라이언트 측에서만 적용하면 페이지 9개를 모두 fetch해야 함.

### Decision
세 가지를 한 묶음으로 처리:

**1. viz 시그니처 분리**
- `build_mermaid(anchor, ref_groups, cite_groups, direction)`, `build_canvas_json(anchor, ref_groups, cite_groups)`.
- Mermaid: refs는 `paper → group → anchor`, cites는 `anchor → group → paper`.
- Canvas: refs는 anchor 왼쪽 (x < 0), cites는 오른쪽 (x > 0). edge `fromNode/toNode`도 인과 방향.
- `build_citation_canvas` MCP tool도 같은 시그니처로 갱신.

**2. velocity 필터**
- `render_sorted_list`에 `min_velocity: float = 0.0` 인자 추가. velocity 모드일 때만 적용.
- `get_references_by_citations`, `get_citations_by_citations` 두 tool 모두 `min_velocity=10.0` 기본값 + `sort="velocity"` 기본값.

**3. SS citations endpoint 페이지네이션**
- `fetch_network_papers`에 `publication_date_or_year: str | None = None` 인자 추가. SS swagger의 `publicationDateOrYear` 파라미터로 전달.
- `get_citations_by_citations`는 `exclude_recent_year=True` (기본)일 때 `:<current_year-1>`를 자동 적용 → SS 측에서 최근 1년 신생 논문 제거. min_velocity≥10과 정합 (1년 미만 누적 시간 부족).
- `fetch_network_papers` 요청 필드를 **light** (`paperId,title,year,citationCount,externalIds`)로 축소. 무거운 메타(authors/venue/influentialCitationCount/url)는 페이지네이션 단계에서 제외. 필요 시 호출측이 `/paper/batch`로 보강.
- `get_references_by_citations` 기본 `max_fetch` 200 → 500 (references는 보통 100 이내라 한 페이지로 충분).
- `get_citations_by_citations` 기본 `max_fetch` 200 → 1000.

### Reasoning
- **시그니처 분리**가 surgical하다 — 단일 `groups`에 kind 필드를 끼우는 변종보다 명시적. 호출측(skill, viz_tools)도 자연스럽게 두 인자를 분리해서 LLM이 그룹핑 단계에서 refs/cites를 독립적으로 처리하도록 강제.
- velocity 10은 보수적 임계값 — "발표 후 1년에 인용 10건" 또는 "5년에 50건" 정도. 분야 평균보다 높지만 압도적 영향력 논문에만 좁히지 않음. 기본값일 뿐이고 사용자가 매번 override 가능.
- SS API 응답 정렬 분석은 캐시 데이터로 직접 검증 (`.cache/06fb47f...` BLIP-2 citations: 첫 entry부터 200번째까지 모두 2026년). swagger `publicationDateOrYear` 파라미터가 가장 정확한 해결책.
- light fields로 응답 크기가 줄어 페이지당 네트워크 시간 단축. authors/venue가 필요해지면 후속 ADR에서 batch 보강 단계 도입.

### Tradeoffs
- **viz 시그니처 변경은 호환성 깨짐** — 기존 호출자(외부에서 본 tool을 직접 호출하던 사용자)는 갱신 필요. surgical 원칙에 따라 deprecation alias는 두지 않음 (단일 사용자, 외부 의존 없음).
- **`exclude_recent_year=True`는 신생 연구를 놓침** — 발표 직후 폭발적 인용을 받는 논문은 1년 동안 보이지 않는다. 사용자가 명시적으로 `exclude_recent_year=False, min_velocity=0`으로 전환 가능. SKILL.md drill-down 옵션에 명시.
- **light fields는 author/venue 누락** — render 결과에 "-"로 표시. 필요 시 top_k 결정 후 batch 보강 (현 ADR 범위 밖, 후속 확장).
- **`publicationDateOrYear` 캐시 키 분리** — 같은 anchor라도 필터 다르면 다른 캐시 entry. 디스크 부담 미미.

### 구현 영향
- `analysis/viz.py` — 새 시그니처. ADR-005 supersede 아님 (확장).
- `analysis/ranking.py` — `min_velocity` 인자 추가.
- `sources/semantic_scholar.py` — `publication_date_or_year` + light fields.
- `tools/citation_tools.py` — 두 tool 모두 기본값 변경, `get_citations_by_citations`에 `exclude_recent_year` 인자.
- `tools/viz_tools.py` — 시그니처 동기화.
- `.claude/skills/research-flow/SKILL.md` — 8 step 갱신, drill-down 옵션에 신생 포함 모드 추가.
- 회귀 테스트 25 PASS (`tests/test_analysis_viz.py`, `test_tools_viz.py`, `test_analysis_velocity_filter.py`, `test_sources_ss_fetch.py`).

### 보강 (2026-06-04, isInfluential 통합)
사용자 제안 검토 결과 #2(isInfluential 활용)만 채택. velocity가 잡지 못하는 강한 영향력 신호 (분야가 좁아 카운트 누적이 느린 후속, 1년 차 핵심 인용 등)를 SS 자체 산출 시그널로 보강.

- `fetch_network_papers`의 fields에 `isInfluential` 추가. entry top-level의 `isInfluential`은 paper dict의 `is_influential` 키로 주입.
- `render_sorted_list`의 velocity 필터를 OR 조건으로 확장:
  `velocity >= min_velocity OR is_influential is True`.
- 표시 시 영향력 인용은 줄 머리에 `★` 표시 (시각 식별).
- count 정렬 모드는 회귀 없음 (필터 자체가 velocity 모드 한정).
- 회귀 테스트 31 PASS (+6, `tests/test_is_influential.py`).

사용자 제안 #1(중간 sampling)은 거부 — 이미 `publicationDateOrYear=:<year-1>` 필터로 신생 컷팅, sampling은 정확도 손실. #3(max_fetch=1000 검증)은 light fields 응답 크기가 작아 1 페이지 부담 미미, 현재 값 유지.

---

## ADR-015 — figure 추출 범위 축소: caption 필터 + LLM 선별
**Status**: Accepted (2026-06-07). [ADR-010](#adr-010)의 "모든 raster figure 추출" 결정을 부분 supersede.

### Context
ADR-010은 "PDF 내 모든 raster figure 추출 (필터링 없음)"을 결정 — 휴리스틱 누락 위험 제거가 동기였다. 운영 단계에서 BLIP-2(arXiv:2301.12597)로 검증한 결과, 25개 figure 중 다수가 다음 두 부류 노이즈:

1. **caption 없는 항목** — journal 양식 헤더·로고·페이지 장식. PDF 텍스트에 "Figure N:" 패턴이 없으므로 의미 부재가 거의 확실.
2. **caption 있지만 보조 figure** — "Examples of training images", 부록의 sample grid 등. 논문의 핵심 주장과는 무관.

저장된 figure가 vault 노트 본문에 모두 임베드되면 시각적 노이즈도 누적된다.

### Decision
**1. 자동 필터 (코드)** — `wiki/figures.py`의 `extract_figures`가 caption 매칭된 figure만 디스크에 저장. caption 없는 raster는 skip하고 counter는 그대로 증가시켜 이후 image의 caption alignment를 유지.

**2. LLM 선별 (skill)** — 새 MCP tool `prune_paper_figures(arxiv_id, keep)`로 후처리. `paper-ingest` skill의 step 4를 4a(extract) → 4b(LLM 판단) → 4c(prune)로 분할. LLM은 caption 텍스트만 보고 "핵심 architecture / 결과 plot" 인지 판단해 keep set 결정. 기준은 SKILL.md "Figure 선별 가이드"에 명시.

**3. frontmatter / body** — 4c 이후 남은 figure만 frontmatter `figures: [...]`와 body `## Figures` 섹션에 반영. 폴더형 레이아웃(ADR-010 §2)은 유지.

### Reasoning
- caption 없는 figure는 매우 높은 확률로 노이즈 — 코드 측 자동 필터가 false-positive 제거에 충분히 보수적.
- 핵심 figure 선별은 의미 판단 → ADR-003 정합 (분류는 Claude 대화 측). 고정 어휘 휴리스틱은 분야마다 다르므로 LLM 추론에 위임.
- 두 단계로 분리해 변경 영향을 최소화 — `extract_paper_figures`는 후방 호환 (caption 필터만 추가), 새 prune tool은 surgical 한 신규.
- 사용자 검토 여지는 그대로 — vault에서 `keep`된 figure도 사후 삭제 가능. SKILL.md 가이드는 false-negative 최소화 (모호하면 keep).

### Tradeoffs
- **caption 정규식 누락 위험** — `_CAPTION_RE`가 잡지 못하는 형식(예: "Fig. 1.", "FIGURE 1")은 silent drop. 운영 중 빈도가 높아지면 정규식 확장 또는 후속 ADR.
- **LLM 선별의 false negative** — 핵심 figure를 drop 판정하면 vault 노트 정보 손실. 완화: 가이드의 "모호하면 keep" + 사용자 검토.
- **counter alignment 유지로 fig_1 / fig_3 처럼 비연속 번호 발생** — caption 매칭 정확성을 위해 의도된 부작용. 사용자 인지가 필요하면 후속에서 renumber 옵션 추가 가능.
- ADR-010이 "모든 figure 추출은 atomicity 철학 정합"이라 명시했으나, 운영 데이터로 "모든 raster ≠ 의미 있는 figure"가 드러남 — atomicity는 의미 단위로 재정의.

### 구현 영향
- `wiki/figures.py` — `_has_caption` helper + `extract_figures`에 caption 없으면 skip 추가.
- `tools/pdf_tools.py` — 신규 `prune_paper_figures(paper_id, keep)` MCP tool. 총 MCP tool 16 → **17**.
- `.claude/skills/paper-ingest/SKILL.md` — step 4 분할 + Figure 선별 가이드 섹션 추가.
- `docs/ARCHITECTURE.md` §3 카탈로그 갱신.
- 회귀 테스트 43 PASS (+12, `tests/test_wiki_figures_caption_filter.py`, `tests/test_tools_pdf_prune.py`).

---

## ADR-016 — vault 폴더·파일명을 title-slug로 변경
**Status**: Accepted (2026-06-07). [ADR-010](#adr-010) §2 "폴더형 레이아웃 — `vault/papers/<arxiv_id>/`" 부분 supersede.

### Context
ADR-010은 폴더명을 arxiv_id (예: `2301.12597`)로 정함 — 식별자 안정성이 동기였다. 운영 단계에서 두 가지 문제:

1. **사람 가독성** — 폴더 트리·Obsidian graph view에서 arxiv_id는 의미를 전달하지 않음. 사용자가 vault를 둘러볼 때 매번 `index.md`를 열어 title을 확인해야 함.
2. **grep / agent 검색 효율** — `papers/2301.12597/` 식의 폴더명은 fuzzy / semantic 검색에 도움 안 됨. `papers/blip-2/`는 키워드 자체로 매칭.

### Decision
**vault 폴더 + 노트 파일 경로의 식별자는 title-slug**로 한다. arxiv_id는 **frontmatter에 보존**해 식별자 역할 유지.

- 폴더: `vault/papers/<title-slug>/index.md`, `figures/`, `canvases/<title-slug>.canvas`.
- title-slug 규약: `core.slug.slugify_title(title)`. 콜론 이전 부분, ASCII 정규화, 소문자, 영숫자·하이픈만, 최대 80자.
- arxiv_id는 frontmatter `arxiv_id:` 필드. PDF는 `pdfs/<arxiv_id>.pdf` 그대로 (PDF는 식별자 안정성이 더 중요).
- 호환 도구: `wiki.vault.resolve_paper_by_arxiv_id(arxiv_id) -> Path | None` — frontmatter scan으로 역방향 매핑. `tools.wiki_tools._resolve_slug`가 입력이 arxiv_id 형식이면 자동 호출 (기존 호출자 무변경).

### Reasoning
- ADR-010의 "폴더형 = atomicity"는 폴더 명명과 독립. atomicity는 유지.
- 사람·grep 친화는 [CLAUDE.md "프로젝트 원칙 — 에이전트 가독성"](../CLAUDE.md)의 "헤더는 내용 명명" 원칙과 정합.
- arxiv_id의 안정성은 frontmatter에서 100% 보장됨 — 폴더명에서 사라져도 의미 손실 없음.
- wiki_tools의 자동 lookup은 외부 호출자(citation-analysis 등)의 변경 없이 ADR을 적용하는 surgical 접근.

### Tradeoffs
- **title 변경 시 rename 부담** — 논문 title이 사후 바뀔 일은 드물지만 발생 시 폴더 rename + wikilink 갱신 필요. Obsidian rename은 wikilink 자동 갱신.
- **slug 충돌 가능성** — 두 논문의 콜론 앞 부분이 동일하면 (예: "GPT-4 Technical Report" vs "GPT-4 System Card") 같은 slug. 완화: 충돌 감지 시 `<slug>-<year>` 또는 `<slug>-<arxiv_id_suffix>` 보강. 본 ADR은 단순 케이스만 다루고 충돌 처리는 후속 ADR.
- **arxiv 외 식별자** — DOI·SS sha 입력은 frontmatter scan으로 매칭 안 됨. paper-ingest의 step 1에서 arxiv_id로 정규화 후 진행하는 패턴 강제.

### 구현 영향
- `core/slug.py` 신설 — `slugify_title`, `is_arxiv_id` 헬퍼.
- `wiki/vault.py` — `paper_dir`/`paper_note_path` 시그니처 의미 변경 (slug), `resolve_paper_by_arxiv_id` 추가.
- `wiki/figures.py` — `extract_for_paper(arxiv_id, vault_slug)` 인자 추가 (legacy fallback 유지).
- `tools/pdf_tools.py` — `extract_paper_figures(paper_id, slug)`, `prune_paper_figures(paper_id, keep, slug)` 인자 추가.
- `tools/wiki_tools.py` — `_resolve_slug`에 arxiv_id 형식 자동 lookup.
- `.claude/skills/paper-ingest/SKILL.md` — slugify_title step 추가, frontmatter에 `slug` 필드.
- `.claude/skills/citation-analysis/SKILL.md` — `build_citation_canvas` slug 인자가 title-slug.
- `docs/ARCHITECTURE.md` 갱신.
- 회귀 테스트 75 → 85 PASS (+10, slug helper + resolve + figures slug + wiki_tools arxiv lookup).

---

## ADR-017 — figure 추출 위치 기반 매칭 + multi-component 보존
**Status**: Superseded by [ADR-018](#adr-018) (2026-06-07).

### Context
ADR-015 도입 후 BLIP-2(arXiv:2301.12597) 운영 검증 시 figure ↔ caption 매칭이 완전히 어긋남을 확인. 원인:

| 가정 (이전 알고리즘) | 실제 BLIP-2 PDF |
|---|---|
| 한 figure = 한 raster image | Fig 1·2·3·6·7은 2~4개 sub-image, **Fig 4는 13개 sub-image 격자** |
| extraction 순서(counter) = figure 번호 | 페이지마다 image 개수가 들쭉날쭉이라 counter ≠ figure N |
| 모든 figure는 raster | **Fig 5는 vector plot** — raster 추출 자체에 잡히지 않음 |

진단 prototype 결과: image bbox(`page.get_image_bbox`)와 caption 위치(`page.search_for("Figure N:")`)를 같은 페이지 안에서 비교하면 BLIP-2의 figure 1~4·6·7을 100% 정확히 분류 가능. Fig 5는 vector이므로 raster 영역에선 영영 추출 불가 (page-as-image 도입 시 해소될 알려진 한계).

### Decision
**1. 위치 기반 매칭** — `extract_figures`를 다음 순서로 재작성:
- (a) PDF에서 `Figure N:` 캡션의 (`page_idx, y_top`) 수집.
- (b) 모든 raster image의 (`page_idx, bbox`) 수집 (xref dedup 유지).
- (c) 각 image에 대해 **같은 페이지**의 caption만 매칭 후보로. caption이 image 바로 아래(`caption_y >= img_y1 - tol`)면 그 중 가장 가까운 것, 없으면 같은 페이지 caption 중 최단거리. 같은 페이지에 caption 없으면 `None` → drop.

**2. multi-component 보존** — 한 figure에 여러 sub-image가 매칭되면 등장순(페이지, y0)으로 정렬해 `fig_<N>_a.png`, `fig_<N>_b.png`, `fig_<N>_c.png`… 식 letter suffix로 저장. 단일 sub-image도 `_a` 붙여 명명 일관성 유지. 모든 sub-image는 같은 caption을 공유.

**3. ADR-015 보존** — caption 매칭이 None이면 저장 skip. 매칭은 있어도 caption 텍스트가 비어 있으면 skip (`_has_caption`).

**4. paper-ingest skill 갱신** — step 5b "LLM 선별" 기준을 **figure 번호 단위**로 명시. 같은 N의 모든 sub-image는 묶어 keep/drop 결정.

### Reasoning
- 위치 기반 매칭은 PDF 구조의 표준 시그널(image bbox, caption text rectangle)을 활용 — heuristic 아님.
- multi-component 격자(Fig 4 13장)는 LLM이 의미 단위로 사고하기 적합. 한 caption = 한 의미.
- letter suffix는 figure 번호와 인덱스를 분리해 grep에서 `fig_4_` prefix로 동일 figure 묶음 검색 용이.
- ADR-015 caption 필터는 그대로 — journal noise 차단은 새 알고리즘에서도 유효.

### Tradeoffs
- **vector-only figure는 여전히 추출 불가** (Fig 5 같은). 사용자 결정 (2026-06-07): page-as-image는 도입 안 함, 이 한계는 알려진 tradeoff로 수용. 필요 시 후속 ADR에서 페이지 영역 clip 렌더링(`page.get_pixmap(clip=...)`) 도입 가능.
- **caption 위치를 본문 인용 vs 실제 캡션으로 구분 못 함** — `Figure N:` 형식이 본문에 등장하면 첫 매칭이 본문 인용에 잡힐 가능성. 완화: `setdefault`로 첫 등장만 사용, 본문 인용은 보통 `Figure N` (콜론 없음)이라 정규식이 잡지 않음. 실 PDF에서 빈도 낮음.
- **한 페이지에 figure 여러 개 + image 다수**: image 위치와 caption 위치의 nearest 매칭이 잘못된 묶음을 만들 가능성. 완화: caption이 image 아래에 있는 케이스를 우선. 잘못된 묶음이 발견되면 사용자가 vault에서 직접 정리 가능.
- **`fig_N_*` 파일명 변경**은 후방 호환 깨짐 — 외부 wikilink가 `![[figures/fig_1.png]]` 같은 직접 임베드를 갖고 있으면 끊김. 사용자 vault는 단일 사용자라 영향 제한적.

### 구현 영향
- `wiki/figures.py` — `_parse_caption_text`, `_parse_caption_locations`, `_assign_figure_number`, `_letter_suffix` helper + `extract_figures` 재작성.
- `.claude/skills/paper-ingest/SKILL.md` — step 5b 가이드 "같은 figure 번호의 모든 sub-image는 묶어 결정".
- `docs/ARCHITECTURE.md` §5.1 figures 예시 갱신.
- 회귀 테스트 75 → 80 PASS (+5 신규, 기존 2 fixture 갱신).
- BLIP-2 vault 재구축 검증 (caption ↔ image 정합 확인).

---

## ADR-018 — figure·table 영역 crop + page-as-image 옵션 도구
**Status**: Superseded by [ADR-019](#adr-019) (2026-06-07).

### Context
ADR-017(위치 기반 + multi-component sub-image)로 BLIP-2를 재추출한 결과 매칭은 정확해졌지만 **시각적 의미가 깨졌다**. 한 figure가 13개 sub-image로 흩어져 vault note의 ## Figures가 격자 그대로의 시각 의미를 잃는다. Fig 2(Q-Former) 같은 figure는 sub-image bbox union이 너무 좁아 (75×100pt) 화살표·텍스트 라벨·박스 frame이 누락. **human perception은 sub-image가 아니라 "한 figure = 한 그림"** 단위.

추가로 ADR-017은 table을 다루지 않는다. table은 PDF에서 vector text라 raster sub-image가 없어 caption 위치 기반 영역 crop 외엔 방법이 없다.

### Decision
**1. figure: 영역 crop (한 figure = 한 PNG)**
- `wiki/figures.py` 재작성. caption rectangle을 기준으로 column-aware 영역 추정:
  - sub-image bbox union이 페이지 너비의 1/3 미만이면 학술 2-column 가정 → 좌/우 column 영역으로 확장.
  - bbox union 폭이 1/3 이상이면 full-width.
  - sub-image가 전혀 없는 vector-only figure(BLIP-2 Fig 5 같은 ablation plot)도 caption 위쪽 일정 거리(`_CAPTION_Y_REACH=380pt`)를 휴리스틱으로 잡아 추출.
- 파일명 `fig_<N>.png` (suffix 없음). `pix.save(out_dir/file)` with `dpi=150`.
- ADR-017의 `fig_<N>_<letter>.png` 명명은 폐기.

**2. table: 영역 crop (신설)**
- `wiki/tables.py` 신설. `Table N:` caption rectangle을 페이지에서 찾고 caption + 그 아래 `_CAPTION_Y_REACH=260pt` 영역을 페이지 너비 margin 안으로 crop.
- 파일명 `table_<N>.png`.
- `vault/papers/<slug>/tables/` 디렉토리에 저장 (figures와 분리).

**3. page-as-image 옵션 도구 (신설)**
- `tools/pdf_tools.py`에 `render_paper_page(paper_id, page, slug, dpi)` MCP tool 추가. 페이지 1장을 통째로 PNG로 렌더 → `papers/<slug>/pages/page_<n>.png`.
- figure crop이 잡지 못한 케이스(복잡한 layout, 수식 위주 페이지)나 추후 ColPali 스타일 retrieval 활용을 위한 보조 도구. 자동 호출 안 함 — 사용자가 명시 요청 시.

**4. prune 도구 동기화**
- `prune_paper_figures` 시그너처 유지 — 파일명만 `fig_<N>.png` 단순화로 호출 입력이 더 간결해짐 (figure 단위 결정).
- 신규 `prune_paper_tables(paper_id, keep, slug)` 추가.

**5. paper-ingest skill 갱신**
- step 5a: `extract_paper_figures` + `extract_paper_tables` 둘 다 호출.
- step 5b: LLM 선별 (figure + table 각각, 핵심만).
- step 5c: prune (figure + table 각각).

### Reasoning
- **human perception** — figure는 sub-component의 합이 아니라 의미 단위 1장. 영역 crop이 자연스럽다.
- **vector-only figure 회수** — ADR-010이 명시한 "벡터 그림 누락" tradeoff가 일부 해소. 휴리스틱이라 100%는 아니지만 raster-only 추출보다 모든 figure 케이스에서 우월.
- **table 처리 통일** — figure와 같은 caption 기반 영역 crop이라 코드 패턴 일관. 두 모듈을 공통 헬퍼로 추상화하지 않은 이유는 차이가 있다 (figure는 raster bbox로 column 추정 가능, table은 caption 위치만으로 휴리스틱).
- **page-as-image는 도구로만 노출** — Karpathy LLM Wiki 패턴을 깨지 않음. 자동 호출 안 함이라 wiki note는 여전히 atomic markdown 중심.

### Tradeoffs
- **휴리스틱 잘못 잡힘 가능** — 페이지에 figure 두 개가 인접해 영역이 겹치거나, full-page figure에서 본문이 같이 잡히는 경우. 사용자가 vault에서 직접 crop된 PNG를 확인하고 필요 시 prune 또는 page-as-image로 대체. BLIP-2 검증 결과 7개 figure 모두 의미 단위 보존.
- **저장 크기 증가** — sub-image 한 장(수 KB)보다 영역 crop(수십~수백 KB)이 크다. 그러나 vault 한 논문당 figure 5-10개 × ~100KB = 1MB 수준. 사용자 vault가 외부(`~/Documents/research-wiki`)라 디스크 압박 미미.
- **table 정확도** — caption 위/아래 layout이 학술지마다 다양. 휴리스틱(caption 위 6pt + 아래 260pt)이 대다수 케이스 커버하지만 outlier 있을 수 있음. 필요 시 후속 ADR로 text blocks 기반 정밀화.
- **ADR-017 테스트 deprecation** — `tests/test_wiki_figures_position_match.py` 5개 케이스가 의미 무효화. ADR-013 준수해 삭제 대신 `pytest.mark.skip`로 보존. 새 검증은 `test_wiki_figures_region_crop.py`.

### 구현 영향
- `wiki/figures.py` — 영역 crop 재작성. `_figure_clip` column-aware 헬퍼.
- `wiki/tables.py` — 신설.
- `tools/pdf_tools.py` — `extract_paper_tables`, `prune_paper_tables`, `render_paper_page` 신설. **MCP tool 17 → 20**.
- `.claude/skills/paper-ingest/SKILL.md` — step 5 figure + table 분기.
- `docs/ARCHITECTURE.md` — 카탈로그·디렉토리·§5.1 figures/tables 트리 갱신.
- 회귀 테스트 80 → 95 PASS (+15: region_crop 5, tables 6, visuals 9 중 일부 등). ADR-017 테스트 5개 skip.
- BLIP-2 vault 재구축 검증.

### 보강 (2026-06-07, 파일명에 caption 슬러그)
`fig_<N>.png` / `table_<N>.png`은 사람·grep 친화에서 부족 — 번호만으로는 의미를 알 수 없다. `core.slug.slugify_caption`을 활용해 파일명을 확장:
- `fig_<N>_<caption-slug>.png` 예: `fig_1_overview-of-blip-2s-framework.png`
- `table_<N>_<caption-slug>.png` 예: `table_2_comparison-with-sota-vqa.png`
- ADR-016 (vault 명명 = 사람 가독성) 정신의 확장.

prune tool은 후방 호환을 위해 `keep` 입력을 두 가지로 매칭:
- **number 기반** `keep=["fig_1", "fig_3"]` → `fig_<N>_*.png` 매칭 (LLM이 매번 긴 슬러그를 외울 필요 없음).
- **정확 매칭** `keep=["fig_1_overview-...png"]` → 완전 일치.

회귀 테스트 95 → 108 PASS (+13: `test_slug_caption.py` 8, `test_prune_number_match.py` 5).

---

## ADR-019 — figure·table bbox는 vision model로 추정
**Status**: Accepted (2026-06-07). [ADR-018](#adr-018) supersede. ADR-017 supersede 흐름 연장.

### Context
ADR-018 column-aware 휴리스틱(`_figure_clip` / `_table_clip`)을 BLIP-2(arXiv:2301.12597)로 운영 검증한 결과:

- **figure 5/5 케이스 중 4건 실패**:
  - Fig 2 (Q-Former architecture): narrow column 추정 실패 → figure 좌측 절반만.
  - Fig 4 (qualitative grid 13장): 위쪽 절반만 잡음.
  - Fig 5 (vector-only ablation): raster sub-image 0개 → full-page-width 휴리스틱이 같은 페이지의 Table 3를 잘못 잡음.
  - Fig 7 (VQA architecture): 페이지 13 상단 빈 영역 잡음.
- **table 9/9 케이스 중 8건 실패**: BLIP-2가 ICML caption-below-table layout인데 `_table_clip`은 caption 위치를 기준으로 *아래쪽* 260pt만 잡아 본문을 가리킴.

같은 입력을 Gemini 2.5 Pro에 `[ymin, xmin, ymax, xmax]` × 0-1000 정규화 prompt로 보낸 결과 figure/table 모두 시각 의미 단위로 정확히 분류됨. token 사용량 평균 in 490 + out 60, 모두 `confidence="high"`. 비용 figure/table 1건당 ~$0.005, BLIP-2 한 편 (16건) ≈ $0.08.

### Decision
**휴리스틱 코드 전면 삭제**. figure/table bbox는 Gemini Vision으로 추정한다.

**1. `wiki/vision.py` 신설** — 공통 vision 호출 모듈.
- `_build_prompt(caption, kind)` — Google spatial 관례 (0-1000 정규화 [ymin, xmin, ymax, xmax]) 명시.
- `_parse_to_bbox(text)` — JSON 응답 파싱.
- `_to_pt(bbox_1000, page_w, page_h)` — 정규화 → PDF pt 변환.
- `estimate_bbox(page_png, caption, page_w, page_h, kind="figure"|"table") -> tuple | None` — 최상위 호출, 1회 retry.

**2. `wiki/figures.py` / `wiki/tables.py` 재작성**
- 휴리스틱 헬퍼 (`_collect_sub_image_bboxes`, `_figure_clip`, `_table_clip`, `_CAPTION_Y_REACH`, `_PAGE_MARGIN`) **완전 삭제**.
- `_parse_caption_text`, `_parse_caption_pages`만 유지 — vision 호출 대상 페이지 식별용.
- `extract_figures` / `extract_tables` 내부: 각 caption의 페이지를 PNG 렌더 → `estimate_bbox` 호출 → 결과 `Rect`로 `get_pixmap(clip=...)`. 실패(None)는 skip.

**3. `core/config.py`**
- `_load_dotenv()` 추가 — 프로젝트 root `.env` 자동 로드.
- `GEMINI_MODEL` 상수 (기본 `gemini-2.5-pro`).
- `GOOGLE_API_KEY` 검사는 `wiki.vision._get_client()`에서 호출 시점에 명시적 RuntimeError.

**4. 테스트 정책**
- `tests/conftest.py`에 autouse fixture `_mock_vision_estimate`: `estimate_bbox`를 dummy(페이지 중앙 80%)로 monkeypatch. 모든 테스트가 실 API 호출 없이 동작.
- 휴리스틱 단위 테스트 — 이미 ADR-017 sub-image 테스트가 `pytest.mark.skip`로 보존. 새 휴리스틱 테스트는 추가 안 함 (코드 자체 삭제).
- `tests/test_wiki_vision.py` 신설 — prompt / 파싱 / 좌표 변환 단위 11 case.

**5. `tools/pdf_tools.py`** — 시그너처 무변경 (`extract_paper_figures`, `prune_paper_figures`, `extract_paper_tables`, `prune_paper_tables`, `render_paper_page`). 내부 알고리즘만 교체. `render_paper_page`는 ADR-018에서 옵션 도구로 도입, 본 ADR에서도 유지 (휴리스틱 fallback 아닌, 시각 보존 용도).

### Reasoning
- **휴리스틱이 학회 layout 다양성을 다루지 못함** — caption 위치(위/아래), column 수, vector vs raster 등 결정 가능한 시그널이 부족.
- **vision model은 의미 단위 인식** — caption 텍스트로 어떤 요소를 잡아야 하는지 자연 추론.
- **fallback 보존은 surgical 위반** — 한 번에 둘 다 유지하면 유지보수 부담·코드 복잡. 사용자가 명시적으로 "전면 삭제" 결정.
- **Google 관례 prompt 명시가 결정적** — 자연어 prompt(첫 실험)은 IoU 0.06-0.44, 관례 명시 후 0.15-0.57. 시각 검증으로는 모든 케이스에서 휴리스틱 우월.

### Tradeoffs
- **외부 API 의존** — `GOOGLE_API_KEY` 필수. 미설정 시 RuntimeError로 명시 실패.
- **네트워크 + 비용 + 지연** — 논문 1편 (figure 5-10 + table 5-10) ≈ $0.05-0.10, ~30-90초.
- **결정론 손실** — 같은 PDF를 두 번 호출해도 미세 차이 가능. 그러나 BLIP-2 운영 검증으로 confidence=high 일관.
- **not_found 케이스 존재** — BLIP-2 9 table 중 Table 2가 prompt 응답 형식 미스로 not_found. retry로 일부 해소, 영구 실패 시 해당 항목 skip (사용자가 vault에서 확인).
- **vendor lock-in 일부** — Gemini API 의존. `wiki/vision.py` 인터페이스를 모듈로 분리해 추후 Claude / OpenAI 등 provider 교체는 한 파일 수정으로 가능 (실험 스크립트의 `BboxEstimator` ABC 패턴 참고).
- **`page-as-image` 도구(render_paper_page)는 유지** — vision으로도 잡지 못하는 케이스의 보조 수단.

### 구현 영향
- 신설: `wiki/vision.py`, `tests/test_wiki_vision.py`.
- 재작성: `wiki/figures.py`, `wiki/tables.py` (휴리스틱 헬퍼 삭제).
- 갱신: `core/config.py` (.env 로드 + GEMINI_MODEL), `pyproject.toml` (`google-genai>=1.0`), `tests/conftest.py` (vision mock fixture).
- 무변경: `tools/pdf_tools.py` 시그너처, `.claude/skills/paper-ingest/SKILL.md` 흐름 (vision 호출은 내부 구현).
- ADR-018 supersede. ADR-017은 ADR-018 → ADR-019 supersede 체인.
- 회귀 테스트 119 PASS + 5 skipped (+11 신규 vision, -5 figures_position_match 이미 skip).
- BLIP-2 vault 재구축으로 검증.

---

## 부록 A — 리스크 레지스터

ADR은 "결정"이지만 리스크는 모니터링 대상. 본 절은 변경 가능.

| 리스크 | 영향 | 대응 |
|---|---|---|
| HF Daily 비공식 API 불안정 | daily-digest 중단 | ADR-006 fallback |
| Semantic Scholar rate limit | citation 그래프 지연 | core/cache.py + 지수 백오프, contexts는 상위 5 edge만 샘플링 |
| 자동 인용 그룹핑 오분류 | vault 노트 신뢰도 저하 | 사용자 vault에서 직접 수정 가능 (R2와 부합) |
| Obsidian vault 동시 쓰기 | 노트 손상 | 단일 사용자 가정. 충돌 시 `*.conflict-<ts>.md`로 보존 |
| PDF 저장 용량 폭증 | 디스크 압박 | `pdfs/` gitignore, `vault_status`에 사용량 노출, 수동 prune 가이드 |
| Skill↔Tool 책임 경계 흐려짐 | 직교성 붕괴 | ARCHITECTURE §3.1 카테고리 룰을 CLAUDE.md에 강제 |
