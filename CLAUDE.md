# CLAUDE.md

Research MCP. 작업 시작 전 본 파일 + 관련 docs 절을 먼저 읽는다.

## 문서 위치
- [docs/PRD.md](docs/PRD.md) — 요구사항 R1-R5, 비목표
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 레이어·디렉토리·tool/skill 카탈로그·데이터모델
- [docs/ADR.md](docs/ADR.md) — 결정 ADR-001~008 (불변, supersede만)
- [docs/PLAN.md](docs/PLAN.md) — Phase 진행 / 현재 상태 / 다음 액션
- `<디렉토리>/CLAUDE.md` — 디렉토리별 세부 규칙. **존재 시 본 파일보다 우선**.

## 작업 원칙 (Karpathy 4계명)
1. **Think first** — 가정 명시. 해석이 여럿이면 사용자에게 선택권. 헷갈리면 멈추고 질문.
2. **Simplicity** — 요청 범위 밖 기능·추상화·에러 처리 금지. 200줄이 50줄로 가능하면 다시 쓴다.
3. **Surgical** — 인접 코드 "개선" 금지. dead code는 언급만. 본인 변경으로 생긴 고아만 정리.
4. **Goal-driven** — 작업을 검증 가능한 성공기준으로 변환. 다단계는 `[단계 → verify]` 형식.

## 프로젝트 원칙 — 에이전트 가독성
모든 산출물(LLM wiki / 피드백 / 하네스 / 로그 / 본 문서들)은 LLM·에이전트가 읽기 좋게 관리한다.
- **구조 우선** — 산문보다 frontmatter·표·리스트·JSON. 키는 안정적 식별자(ADR-N, R1-R5, Phase-N).
- **원자성** — 한 파일/섹션 = 한 개념. Karpathy wiki 철학(페이지 통째로 cache hit).
- **명시 링크** — 암묵적 참조 금지. `[[wikilink]]` 또는 `[docs/X.md#anchor]`.
- **로그·하네스** — `key=value` 또는 JSON, grep 가능. 자유 텍스트 로그 금지.
- **헤더는 내용 명명** — 문학적 제목 금지. 첫 30자에 의미 노출.

## 하드 룰 (위반 = PR 차단)
- **레이어 단방향**: `sources → analysis → wiki → tools → skills`. 역방향 import 금지.
- **Tool 직교성**: 한 tool = 한 카테고리 ([ARCHITECTURE §3.1](docs/ARCHITECTURE.md#31-카테고리-직교성-룰)). 두 개 걸치면 분할.
- **외부 fetch는 `core/cache.py` 경유** 필수. TTL은 `core/CLAUDE.md` 정의.
- **ADR 본문 불변**. 결정 변경은 새 ADR-N 추가, 기존은 `Superseded by ADR-N` 라벨만.
- **출력 언어**: 사용자 응답 한국어 기본. frontmatter 키·코드 식별자 영어.
- **TDD**: 구현 코드보다 **테스트를 먼저** 작성 (Red → Green). 사후 테스트 금지 — 사후 작성은 테스트가 코드의 실제 동작에 끼워맞춰져 검증력을 잃는다. **테스트 삭제는 구현 완료 후 사용자 명시 승인 시에만** — 자동/임의 삭제 금지 ([ADR-013](docs/ADR.md#adr-013)).

## 자가개선 — 어디에 쓰나
| 변경 종류 | 대상 |
|---|---|
| 요구사항 자체 | `docs/PRD.md` |
| 구조/카탈로그 변경 | `docs/ARCHITECTURE.md` (코드 PR과 동시) |
| 새 결정 (이유 + 트레이드오프) | `docs/ADR.md` (ADR-N 추가) |
| Phase 토글 / 다음 액션 | `docs/PLAN.md` |
| 디렉토리 한정 규칙 | `<dir>/CLAUDE.md` |
| 전체 작업 관습 | 본 파일 |

발동 조건: 같은 사용자 정정 2회 = 문서로 승격. 자동 갱신 금지 — `self-improve` 스킬로 사용자 승인 후 저장 ([ADR-008](docs/ADR.md#adr-008)).

## 도구 한계 대응 (자가개선 연장)
기존 도구가 같은 오류로 **2회 이상** 실패하거나 의도와 다른 결과를 낼 때:
- **우회 금지** — 임의로 web search 등 다른 도구로 대체하지 않는다. 우회는 도구 모음의 결손을 코드 밖에 숨겨 영원히 남긴다.
- **진단** — 원인을 구조적으로 명명한다. 예: "arxiv PDF 50MB+ timeout", "SS API 429 후 재시도 없음", "큰 PDF는 청크 로드 미지원".
- **제안** — 사용자에게 (a) 새 도구가 필요한가 vs (b) 기존 도구 보강인가를 물어 결정받고, 결정은 `docs/ADR.md` 새 ADR 후보로 등록.
- **외부 도구 대체는 사용자 사전 동의 필수**.

안티패턴(금지): `read_paper`가 큰 PDF에서 실패 → 임의로 web search로 동일 정보 수집.

## 워크플로우 (harness 5단계)
1. **탐색** — PRD → ARCHITECTURE → ADR 순으로 관련 절 확인.
2. **토의** — 모호하면 사용자 질문. `Proposed` ADR이 막으면 강행 금지.
3. **단계 설계** — `docs/PLAN.md` 현 Phase 하위로 분해, 각 단계에 verify 명시.
4. **실행** — 코드 + 관련 문서 동시 PR. 변경된 모든 줄이 사용자 요청에 매핑되는지 자가검증.
5. **회고** — 정정/실패가 있었으면 `self-improve` 호출 후 마감.

## 변경 로그
- 2026-05-30: 초안 + Karpathy 4계명 + 100줄 이하 압축. 세부 규칙은 디렉토리별 CLAUDE.md로 이관 예정.
- 2026-05-30: "프로젝트 원칙 — 에이전트 가독성" 추가 (구조·원자성·명시 링크·구조화 로그·내용 명명 헤더).
- 2026-05-30: 하드 룰에 TDD 추가 (테스트 먼저, 구현 나중 — Red → Green).
- 2026-05-30: "도구 한계 대응" 섹션 추가. 우회 금지, 진단·제안, 외부 도구 대체엔 사용자 동의 필수. 자가개선 철학의 연장.
- 2026-05-31: Phase 0-6 전체 완료. 16 MCP tool + 5 skill + `/harness` command. 운영 단계 진입.
- 2026-05-31: TDD 하드 룰 보강 — 테스트 삭제는 구현 완료 + 사용자 명시 승인 시에만 (ADR-013). `tests/` surgical 정리, `pyproject.toml`의 pytest 설정 제거. TDD 룰 자체는 유지 — 다음 구현 시 RED→GREEN 재적용.
