---
name: self-improve
description: 세션 회고를 입력으로 프로젝트 문서(CLAUDE.md / docs/*) diff를 제안하고, 사용자 승인 후 저장 + vault changelog에 기록한다.
trigger:
  - "self-improve"
  - "회고 반영해줘"
  - "이번 세션 정리해서 룰로 만들어"
inputs:
  - corrections (list[string], 선택) — 본 세션 사용자 정정/실패/관습 항목. 미지정 시 Claude가 직전 대화를 회고.
---

## When to invoke
세션을 닫기 전, 같은 사용자 정정이 **2회 이상** 누적되었거나 새 결정 후보가 발견되었을 때.
1회성 정정은 부르지 말 것 — 노이즈가 룰로 굳는다.

## 발동 원칙
- **사용자 정정 2회 = 문서로 승격** (1회는 보류).
- **자동 갱신 금지** — 본 스킬은 *diff 제안*까지만. 저장은 사용자 명시 승인 후.
- **출처 명시** — 모든 diff는 "왜"가 회고 항목과 연결돼야 한다.

## 어느 문서에 갈지

| 변경 종류 | 대상 |
|---|---|
| 요구사항 자체 | `docs/PRD.md` |
| 구조/카탈로그 변경 | `docs/ARCHITECTURE.md` (코드 PR과 동시) |
| 새 결정 (이유 + 트레이드오프) | `docs/ADR.md` (결정 기록 추가) |
| 진행 상태 토글 / 다음 액션 | `docs/PLAN.md` |
| 디렉토리 한정 규칙 | `{dir}/CLAUDE.md` |
| 전체 작업 관습 | 루트 `CLAUDE.md` |

## Steps

| # | 동작 | 도구 |
|---|---|---|
| 1 | 회고 입력 수집 (사용자 정정·반복 실패·새 패턴) | (LLM) — corrections 미지정 시 직전 대화 스캔 |
| 2 | 항목별 분류 — 위 표 기준으로 대상 문서 매핑 | (LLM) |
| 3 | 각 항목에 대해 **승격 자격** 검사: 2회 이상? 1회면 보류 표시 | (LLM) |
| 4 | 대상 문서 현재 내용 조회 | `wiki_read_note` (vault 외 docs는 직접 Read 가능) |
| 5 | diff 제안 — 추가/수정 라인을 명시. 새 결정 기록이면 다음 순번 자동 추정. | (LLM) |
| 6 | **사용자에게 diff 보여주고 승인 요청** | (대화) |
| 7 | 승인된 항목만 저장 | `wiki_write_note` (vault) / Edit (docs/*, CLAUDE.md) |
| 8 | changelog 항목 append → `vault/_meta/changelog.md` | `wiki_read_note("_meta/changelog")` + `wiki_write_note(...)` |

## changelog 형식 (vault/_meta/changelog.md)

```markdown
# Changelog

## 2026-05-31 12:34 UTC

**Summary**: 작업 시작 전 결정 확정 패턴을 워크플로우에 명시.

**Files**:
- CLAUDE.md (워크플로우 절 라인 추가)
- docs/ADR.md (새 결정 기록 추가)

**회고 출처**: 사용자 정정 2건 — "생각한 내용은 문서에 반영하지 말고 나랑 상의", "권장대로 가줘".
```

## Output format (사용자 응답)

```
🪞 self-improve 회고
   회고 항목: {N} (승격 자격 {K} / 보류 {N-K})

승격 자격 항목:
[1] {요약}  → {대상 문서}
    diff:
    ```diff
    + ...
    ```
[2] ...

승인하시면 저장 + changelog 기록합니다.
```

## 결정 기록 후보 처리 (특별 케이스)

새 결정 기록 후보는 단순 추가가 아니다:
1. 기존 결정 목록에서 충돌(supersede) 후보 확인.
2. supersede면 옛 기록에 `Superseded by ...` 라인만 추가 (본문 불변).
3. 새 기록에 Context / Decision / Reasoning / Tradeoffs 네 섹션 모두 채움.

## Failure handling
- 사용자가 diff를 거부 → 항목을 changelog에 "rejected" 상태로 기록 (다음 세션에서 같은 정정이 또 오면 재판단 용이).
- 저장 중 디스크 권한 오류 → 사용자에게 vault 경로 확인 안내.
- changelog read 실패 → 처음 호출이면 헤더(`# Changelog`)만 가진 새 파일 생성.

## 후속 호출 제안
- 자가개선 누적이 잦으면: `/loop` 스킬로 야간 자동 회고 (옵션).
- 큰 구조 변경이면: 같은 PR에서 `docs/ARCHITECTURE.md`도 갱신.
