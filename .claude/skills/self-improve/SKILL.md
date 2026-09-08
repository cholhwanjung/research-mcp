---
name: self-improve
description: 세션 회고(사용자 정정·반복 실패)를 프로젝트 문서(CLAUDE.md / docs/*) diff로 제안하고, 승인 후 저장 + vault changelog 기록. 같은 정정 2회 = 승격.
trigger:
  - "self-improve"
  - "회고 반영해줘"
  - "이번 세션 정리해서 룰로 만들어"
inputs:
  - 'corrections (선택) — 본 세션 정정/실패/관습 목록. 없으면 직전 대화를 회고'
---

## When to invoke
세션을 닫기 전, 같은 정정이 **2회 이상** 누적됐거나 새 결정 후보가 나왔을 때. 1회성 정정은 노이즈 — 부르지 않는다.

## 원칙
- 정정 2회 = 문서로 승격, 1회는 보류.
- 자동 갱신 금지 — diff 제안까지. 저장은 승인 후.
- 모든 diff는 "왜"가 회고 항목과 연결된다.

## 대상 문서
| 변경 종류 | 대상 |
|---|---|
| 요구사항 | `docs/PRD.md` |
| 구조/카탈로그 | `docs/ARCHITECTURE.md` (코드 PR과 동시) |
| 새 결정 (이유·트레이드오프) | `docs/ADR.md` |
| Phase 토글·다음 액션 | `docs/PLAN.md` |
| 디렉토리 한정 규칙 | `{dir}/CLAUDE.md` |
| 전체 관습 | 루트 `CLAUDE.md` |

## Steps

| # | 동작 | 도구 |
|---|---|---|
| 1 | 회고 입력 수집 | (LLM) — corrections 없으면 직전 대화 스캔 |
| 2 | 항목별 대상 문서 매핑 | (LLM) |
| 3 | 승격 자격 검사 (2회 이상?) | (LLM) |
| 4 | 대상 문서 현재 내용 | Read |
| 5 | diff 제안 — 새 ADR이면 다음 번호 추정 | (LLM) |
| 6 | diff → **승인 요청** | (대화) |
| 7 | 승인된 항목만 저장 | Edit |
| 8 | changelog append | `wiki_read_note("_meta/changelog")` → `wiki_write_note` |

**ADR 후보**: 기존 결정과 충돌(supersede)하는지 먼저 확인. supersede면 옛 기록엔 `Superseded by ADR-N` 한 줄만(본문 불변). 새 기록은 Context / Decision / Reasoning / Tradeoffs 네 절.

## changelog (`vault/_meta/changelog.md`)
```markdown
## 2026-05-31 12:34 UTC
**Summary**: 작업 시작 전 결정 확정 패턴을 워크플로우에 명시.
**Files**:
- CLAUDE.md (워크플로우 절)
- docs/ADR.md (ADR-N)
**회고 출처**: 사용자 정정 2건 — "…", "…"
```

## Output
회고 항목 수(승격 K / 보류 N−K) → 승격 항목마다 요약 · 대상 문서 · diff → 승인 요청.

## Failure handling
- diff 거부 → changelog에 rejected로 기록 (다음 세션 재판단용).
- 저장 권한 오류 → 경로 안내. changelog 없음 → `# Changelog` 헤더로 생성.
