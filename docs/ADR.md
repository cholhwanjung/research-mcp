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
**Status**: Accepted (2026-05-30)

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
