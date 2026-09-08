---
name: wiki-lint
description: vault 연구 노트의 정합성을 점검한다 — 깨진 링크·orphan·누락 교차참조·stale hub 요약·모순·누락 hub·gap·링크 안 된 언급·부모 hub 중복 태그. 수정 diff를 제안하고 승인된 것만 반영한다.
trigger:
  - "위키 점검"
  - "vault 정리"
  - "노트 모순 찾아줘"
  - "wiki-lint"
inputs:
  - 'scope (선택) — "all"(기본) 또는 hub slug 하나. 대규모 vault에서 비용을 좁히는 손잡이'
---

## When to invoke
논문이 쌓여(대략 10편+) 노트 간 정합성이 흐트러졌을 때, 또는 명시 요청 시. **이미 쌓인 것의 화해(reconcile)** 전용 — 논문 추가는 `paper-ingest`, 단일 노트 수정이면 부르지 않는다.

## 원칙
- **자동 수정 금지** — 스캔 + diff 제안까지. 쓰기는 사용자 승인 후.
- 모든 제안은 노트 slug로 특정한다. 범위 밖 노트는 건드리지 않고, 모호하면 제안하지 않는다.
- vault에 쓰는 어떤 텍스트에도 내부 메타 식별자를 넣지 않는다. 로그는 `_meta/`에만.

## 점검 항목

| # | 항목 | 탐지 | 제안 |
|---|---|---|---|
| L1 | 깨진 wikilink | `[[target]]`이 실재 노트로 해석 안 됨 | 대상 생성 or 링크 수정/삭제 |
| L2 | orphan 논문 | inbound 0 + 어느 hub에도 안 걸림 | 적합 hub에 링크 |
| L3 | 누락 교차참조 | 같은 hub의 두 논문이 서로 링크 없음 | 양쪽 `wiki_link` |
| L4 | stale hub 요약 | hub 본문이 현재 백링크 논문들을 반영 못 함 | 요약 재작성 diff. **교체되는 문단에 판단이 섞여 있으면 먼저 통찰 후보로 건진다** |
| L5 | 노트 간 모순 | 같은 hub 논문 간 상충 주장(수치·supersede) | 모순 명시 한 줄. **모순/보완 판정 자체는 통찰 후보** |
| L6 | 누락 hub | ≥3편에 반복되는 주제인데 hub 없음 | 신규 hub 후보 |
| L7 | data gap | 주장의 근거 논문이 vault에 없음 | 검색어 *제안*만. 자동 fetch 금지. **"이 축이 비어 있다"는 통찰 후보** |
| L8 | 링크 안 된 언급 | hub 본문이 vault 논문을 평문으로만 부름 | `[[slug\|표기]]`로 교체 (표기 유지) |
| L9 | 부모 hub 중복 태그 | 논문이 자식 hub와 그 `parent`에 동시 태그 | 부모 태그 제거 — 계층은 `parent`로 함의. 부모 본문엔 `## 하위 갈래`로 자식 링크 |

- L5·L6은 같은 hub 클러스터 안으로 한정.
- L8 대조는 **뜻으로** — 본문은 축약(`HaluMem`), slug는 부제 포함(`halumem-memory-hallucination`). 문자열만 보면 실재 노트를 미수록으로 오판한다. hub 본문을 새로 쓸 때(L4 포함)도 vault 논문은 반드시 링크, vault에 없는 이름은 평문으로 두고 L7 후보.

## Steps

| # | 동작 | 도구 |
|---|---|---|
| 1 | scope 확정 (기본 all) | — |
| 2 | hub 목록 | `wiki_list_hubs()` |
| 3 | 링크 그래프 1콜 — inbound·고아·깨진 링크·표기 불일치 | `wiki_backlinks()` |
| 4 | 본문이 필요한 노트만 읽기 — hub 본문(L4·L8), L5·L7 대상 논문. **L1·L2·L3은 step 3만으로 판정** | `wiki_read_note` (선별) |
| 5 | L1~L9 판정 → 항목별 diff | (LLM) |
| 6 | 리포트 + diff → **승인 요청** | (대화) |
| 7 | 승인된 항목만 반영 | `wiki_link` / `wiki_write_note` |
| 8 | 로그 append | `wiki_read_note("_meta/lint-log")` → `wiki_write_note` |

**step 3 응답 읽기**: `⚠️ 깨진 링크` → L1 · `✏️ 표기 불일치` → L1 하위(링크는 살아 있음, 우선순위 낮음) · `🕳️ 고아 노트` → L2 후보(`tech-blog-digest/`·`research-autopilot/`·`_meta/`는 제외) · `📇 backlink` → L2·L3 입력. `tech-blog-digest/`의 깨진 링크는 미수록 논문이다 — 지우지 말고 L7 후보로.

**대규모 vault**: L4/L5는 hub 클러스터 단위(📇의 inbound로 대상 선별). 버거우면 `scope`를 hub 하나로 나눠 돌린다. 2회 좁혀도 안 되면 일부를 건너뛰고 추정하지 말고 멈춰서 도구 보강을 제안한다.

**통찰 후보 (L4·L5·L7)**: 판단이 나오면 `insight-capture` 후보 제시 모드로 — 한 줄 후보 + 근거 노트 + 발견 경로, 초안은 쓰지 않는다. 사용자가 안 고르면 `lint-log` deferred에만. L4로 hub 본문을 교체할 땐 지워지는 문단을 먼저 읽는다. hub 본문(현재 상태) vs 통찰(시점 박힌 판단)의 경계는 `insight-capture` 기준.

## lint 로그 (`_meta/lint-log.md`)
```markdown
## [2026-07-07] lint | scope=all | 제안 7 · 승인 5
**Applied**:
- L2 orphan: papers/blip-2 → topics/vlm 링크 추가
**Rejected**:
- L5 모순: blip-2 vs flamingo VQA 수치 — 보류(측정 조건 다름)
**Deferred (data gap)**:
- L7: Q-Former 후속 변형 없음 → "q-former variants 2024"
```
헤더는 `grep "^## \[" lint-log.md | tail -5`로 읽는다.

## Output
스캔 규모(논문·hub·링크) · 발견 건수 L1~L9별 · 항목마다 `[Lx] slug → 제안 + diff` · "승인할 번호를 알려달라".

## Failure handling
- hub 없음(초기 vault) → L1·L6만. `wiki_backlinks`가 빈 vault → 0건 보고 종료.
- 컨텍스트 초과 우려 → scope를 hub 하나로 좁히도록 안내.
- 쓰기 실패 → 경로·권한 안내, 부분 반영 지점 명시. 로그 없음 → `# Lint Log` 헤더로 생성.
