---
name: wiki-lint
description: vault 연구 노트를 주기적으로 health-check한다. orphan·깨진 링크·누락 교차참조·stale hub 요약·노트 간 모순을 스캔해 수정 diff를 제안하고, 사용자 승인 후에만 vault에 반영한다. 자동 수정 금지 (항상 승인 게이트).
trigger:
  - "위키 점검"
  - "vault 정리"
  - "노트 모순 찾아줘"
  - "wiki-lint"
inputs:
  - 'scope (string, 선택) — 점검 범위. "all"(기본, 전체 vault) 또는 hub slug 하나(예: "vlm" → 그 hub에 백링크된 논문 묶음만). 대규모 vault에서 토큰 비용을 사용자가 조절하는 손잡이.'
---

## When to invoke
vault에 논문이 어느 정도 쌓여(대략 10편+) 노트 간 정합성이 흐트러질 수 있을 때, 또는 사용자가 명시적으로 점검을 요청할 때. 개별 논문 1편을 새로 넣는 건 `paper-ingest`가 담당 — 본 스킬은 **이미 쌓인 것들의 화해(reconcile)** 전용이다. 단일 노트만 손보면 되는 경우엔 부르지 말 것.

## 발동 원칙
- **자동 수정 금지** — 본 스킬은 *스캔 + diff 제안*까지만. vault 실제 쓰기는 사용자 명시 승인 후에만. (PRD 비목표 "완전 자동 큐레이션" 준수 — 분류·요약 결과는 사용자가 최종 판단.)
- **출처 명시** — 모든 제안은 "어느 노트의 무엇이 왜 문제인가"를 노트 slug로 특정한다. 막연한 "품질 개선" 금지.
- **surgical** — 요청 범위 밖 노트는 건드리지 않는다. 모호하면 keep(수정 제안하지 않음) 쪽으로.
- **vault 본문 격리** — 제안·수정으로 vault에 쓰는 어떤 텍스트에도 내부 메타 식별자(결정 기록 번호·SKILL·ARCHITECTURE·PRD·PLAN 등)를 넣지 않는다. vault는 사용자 연구 영역. 로그는 `_meta/`(시스템 영역)에만.

## 점검 항목 (scan checks)
각 항목은 **제안**만 만든다. 구조적 항목(L1·L2)도 승인 게이트를 거친다.

| # | 항목 | 탐지 | 제안 형태 |
|---|---|---|---|
| L1 | **깨진 wikilink** | 본문 `[[target]]`이 실재 노트로 해석 안 됨 | 대상 노트 생성 or 링크 수정/삭제 |
| L2 | **orphan 논문** | 인바운드 백링크 0 + 어느 hub에도 안 걸림 | 적합 hub에 `[[논문]]` 링크 추가 |
| L3 | **누락 교차참조** | 같은 hub를 공유하는 두 논문이 서로 링크 없음 | 양쪽에 `wiki_link` |
| L4 | **stale hub 요약** | hub 노트 요약/본문이, 지금 백링크된 논문들을 반영 못 함 | hub 요약 재작성 diff |
| L5 | **노트 간 모순** | 같은 hub 논문들 사이 상충 주장(벤치마크 수치·supersede 관계 등) | 모순을 명시하는 한 줄 노트 추가 |
| L6 | **누락 hub** | 여러 논문(≥3)에 반복 등장하는 주제인데 hub 노트 없음 | 신규 hub 후보 제시(승인 시 생성) |
| L7 | **data gap** (제안만) | 특정 주장/수치의 근거 논문이 vault에 없음 | 채울 만한 질문·검색어를 *제안*. 자동 web fetch 금지 — 사용자가 원하면 별도 ingest. |

L5·L6은 비용이 크므로 **같은 hub 클러스터 안으로 한정**하고, scope가 hub 하나면 그 클러스터만 본다.

## Steps (tool sequence)

| # | 동작 | 도구 |
|---|---|---|
| 1 | scope 확정 (기본 "all") | (대화/입력) |
| 2 | hub 목록 fetch | `wiki_list_hubs()` |
| 3 | 대상 노트 목록 수집 — scope="all"이면 `papers`·`topics`, hub면 그 hub 백링크 논문만 | `wiki_list("papers")` + `wiki_list("topics")` |
| 4 | 노트 본문 읽기 — 링크 그래프·frontmatter·주장 추출 (backlink 반환 tool은 없으므로 in-context로 그래프 구성) | `wiki_read_note(slug)` 반복 |
| 5 | L1~L7 판정 → 항목별 제안 diff 생성 (slug로 특정) | (LLM 추론) |
| 6 | **리포트 + diff를 사용자에게 보여주고 승인 요청** | (대화) |
| 7 | 승인된 항목만 반영 — 링크 추가/노트 갱신/신규 hub 생성 | `wiki_link` / `wiki_write_note` |
| 8 | lint 로그 append | `wiki_read_note("_meta/lint-log")` + `wiki_write_note("_meta/lint-log", ...)` |

## 대규모 vault 대응 (Step 4 비용)
backlink을 반환하는 MCP tool이 없어, 링크 그래프는 노트 본문을 읽어 in-context로 구성한다. 노트 수가 많으면 Step 4가 토큰을 많이 쓴다.
- **1차 대응**: `scope`를 hub 하나로 좁혀 그 클러스터만 점검. 여러 번 나눠 돌린다.
- **2회 이상** scope를 좁혀도 전체 점검이 버거우면 — 임의 우회(예: 일부 노트 건너뛰고 추정) 금지. 멈추고 사용자에게 **읽기전용 `wiki_backlinks` 도구 신설**(기존 `linker.vault_backlinks` 노출)을 새 결정 후보로 제안한다.

## lint 로그 형식 (vault/_meta/lint-log.md)
grep 가능한 한 줄 헤더 규약 (`grep "^## \[" lint-log.md | tail -5`로 최근 이력 확인).

```markdown
# Lint Log

## [2026-07-07] lint | scope=all | 제안 7 · 승인 5

**Applied**:
- L2 orphan: papers/blip-2 → topics/vlm 링크 추가
- L4 stale: topics/vlm 요약 갱신 (신규 논문 3편 반영)

**Rejected**:
- L5 모순: blip-2 vs flamingo VQA 수치 — 사용자 보류(측정 조건 다름)

**Deferred (data gap)**:
- L7: Q-Former 후속 변형 논문 vault에 없음 → 검색어 "q-former variants 2024" 제안
```

## Output format (사용자 응답)

```
🩺 wiki-lint — scope={scope}
   스캔: 논문 {P}편 · hub {H}개 · 링크 {L}개
   발견: {N}건 (L1 깨진링크 {a} · L2 orphan {b} · L3 누락참조 {c} · L4 stale {d} · L5 모순 {e} · L6 누락hub {f} · L7 gap {g})

[L2] orphan: papers/{slug}
     → topics/{hub}에 링크 추가 제안
     ```diff
     + - [[papers/{slug}]] — {한 줄}
     ```
[L4] stale: topics/{hub} 요약
     ```diff
     - {옛 요약}
     + {새 요약 — 백링크된 논문 {k}편 반영}
     ```
...

승인하실 항목 번호를 알려주세요 (예: "L2, L4 반영"). 반영 후 _meta/lint-log에 기록합니다.
```

## Failure handling
- Step 2 `wiki_list_hubs`가 "hub 없음" → topics/에 hub가 아직 없는 초기 vault. L2·L3·L4·L5는 skip, L1(깨진링크)·L6(hub 신설 제안)만 수행.
- Step 3 디렉토리 없음(papers/topics 비어 있음) → 점검할 노트 없음. 스캔 결과 0건으로 리포트하고 종료.
- Step 4 노트 다수로 컨텍스트 초과 우려 → "대규모 vault 대응" 절대로. scope를 좁히도록 사용자에게 안내.
- Step 7 `wiki_write_note`/`wiki_link` 실패 → 디스크 권한/vault 경로 확인 안내. 부분 반영됐으면 어디까지 됐는지 명시.
- Step 8 로그 read 실패 → 첫 호출이면 헤더(`# Lint Log`)만 가진 새 파일 생성.

## 후속 호출 제안
- 점검 주기를 자동화하려면 `schedule`/`/loop`로 야간 lint (제안까지만 자동, 반영은 여전히 사용자 승인).
- L7 data gap을 채우려면 제안된 검색어로 `paper-ingest`.
- hub 구조 자체가 흔들리면(누락 hub 다수) hub 재설계는 사용자 판단 영역 — 본 스킬은 후보만 제시.
