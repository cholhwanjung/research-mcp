---
name: harness
description: CLAUDE.md "워크플로우 (harness 5단계)"를 명령형으로 실행. 큰 작업·새 Phase 시작·복잡한 결정 분기 때 호출.
---

# /harness — 단계형 작업 실행 (harness_framework 패턴)

[CLAUDE.md §워크플로우](../../CLAUDE.md)의 5단계를 강제. 각 단계 산출이 명확해야 다음으로 진행.

## 입력
- `task`: 사용자가 요청한 작업 (자연어)

## 5단계 (Karpathy 4계명 적용)

### 1. 탐색
- [docs/PRD.md](../../docs/PRD.md) → 관련 요구사항 R# 식별
- [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md) → 관련 레이어/디렉토리/도구 카탈로그 확인
- [docs/ADR.md](../../docs/ADR.md) → 관련 결정 ADR-N, 특히 `Proposed` 상태가 막는지 확인
- 디렉토리별 `<dir>/CLAUDE.md`가 있으면 우선 적용

**산출**: "관련 문서·결정 목록" 한 단락. 없으면 명시 ("새 영역").

### 2. 토의
- 가정을 *명시*. 모호하면 **사용자에게 선택권** (Karpathy 1).
- `Proposed` ADR이 막으면 강행 금지 — 사용자에게 결정 요청.
- 같은 문제에 해석이 여럿이면 비교표로 제시.

**산출**: 가정 리스트 + (필요 시) 사용자 응답 대기.

### 3. 단계 설계
- [docs/PLAN.md](../../docs/PLAN.md) 현재 Phase 하위로 분해. 각 sub-step에 **verify 명시**.
- 형식: `[단계 → verify]`. 예: `[ranking 모듈 추가 → pytest tests/test_ranking.py 5 PASS]`
- TDD 강제: 테스트 sub-step이 구현 sub-step보다 항상 앞에 와야 함 ([CLAUDE.md 하드 룰](../../CLAUDE.md)).

**산출**: TaskCreate로 sub-step 등록.

### 4. 실행
- 코드 + 관련 문서를 **같은 PR**에서. 디렉토리 카탈로그가 바뀌면 ARCHITECTURE.md도 동시.
- Karpathy 2·3·4: 요청 범위 밖 추상화·인접 코드 "개선" 금지. dead code는 언급만.
- 변경된 모든 줄이 사용자 요청에 매핑되는지 *자가검증*.
- 도구 한계 발견 시 — **임의 우회 금지**, 사용자에게 진단·제안 ([CLAUDE.md "도구 한계 대응"](../../CLAUDE.md)).

**산출**: 각 sub-step 완료 → verify 통과 → TaskUpdate.

### 5. 회고
- 사용자 정정·반복 실패·새 패턴이 있으면 **마감 전** `/self-improve` 호출.
- 1회 정정은 보류, 2회 이상은 승격 자격 ([ADR-008](../../docs/ADR.md#adr-008)).
- 산출 변경은 vault `_meta/changelog.md`에 기록.

**산출**: changelog 항목 또는 "회고 없음" 명시.

## 사용 예

```
/harness "Phase 4 진행해줘"
```

→ Step 1: PRD R4/R5 + ARCHITECTURE sources/feed_tools 카탈로그 + ADR-006 확인
→ Step 2: 가정 명시 (HF Daily 비공식 API 사용 + RSS 한 endpoint)
→ Step 3: PLAN.md Phase 4 sub-step → tests/test_sources_hf_daily.py (RED) → sources/hf_daily.py (GREEN) → ... TaskCreate
→ Step 4: 단계별 실행 + verify (pytest)
→ Step 5: 정정 없음 → 회고 skip

## 안티패턴
- 5단계를 줄여 step 4(실행)만 함 — 탐색 누락으로 문서·코드 불일치
- step 3(설계) 없이 바로 코드 → 사후 테스트 끼워맞춤 (TDD 위반)
- step 5(회고) 생략 — 같은 정정이 반복되는데 룰 승격 안 됨
