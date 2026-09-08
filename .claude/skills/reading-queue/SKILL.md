---
name: reading-queue
description: vault가 참조하지만 미수록인 논문을 P1~P4 우선순위로 보여준다. 큐는 저장하지 않고 매번 vault에서 유도 — ingest하면 자동으로 빠진다. 저장은 "안 읽기로 함" 결정뿐.
trigger:
  - "뭐 읽어야 하지"
  - "읽을 논문"
  - "ingest 대기열"
  - "reading queue"
inputs:
  - 'limit (선택, 기본 12)'
  - 'scope (선택) — hub slug 하나로 좁히기'
---

## When to invoke
"이제 뭘 읽지"를 물을 때, ingest 세션 전에 목록이 필요할 때. 논문 추가는 `paper-ingest`, 정합성 점검은 `wiki-lint`.

## 원칙 — 큐를 저장하지 않는다
저장된 목록은 vault와 어긋난다. 매번 유도한다 — ingest되면 깨진 링크가 해소돼 다음 스캔에서 자동으로 빠진다. 저장하는 것은 **"안 읽기로 함"** 결정뿐 (`_meta/reading-queue.md`, 이유와 함께).

## 소스

| # | 소스 | 판정 |
|---|---|---|
| S1 | 깨진 wikilink | 기계적 — `wiki_backlinks()`의 깨진 링크 블록 |
| S2 | hub·통찰 노트 본문이 평문으로 부르는 미수록 논문 | LLM 판정 (아래) |
| S3 | `notes/*.md`의 `## 열린 질문` | 논문 미특정이면 검색어로만 |

**S2 두 번 거르기**: ① vault에 이미 있는가 — **뜻으로 대조**(본문 `HaluMem` vs slug `halumem-memory-hallucination`). 있으면 대기열이 아니라 링크 누락 → `wiki-lint` L8로 넘긴다. ② 논문인가 개념인가 — `MoE`·`BM25`·`SFT` 같은 개념·기법명 제외, 특정 논문 고유명(`Mem0`, `FinCon`)만. 애매하면 제외.

## 우선순위 — 그것의 부재로 무엇이 막혀 있는가

| 등급 | 조건 |
|---|---|
| P1 | hub 서사가 의존 **그리고** 다른 항목(통찰 보류·열린 질문)이 그것 때문에 막힘 |
| P2 | hub 본문이 이름을 부르는데 vault에 없음 |
| P3 | 논문 노트가 `[[X]]`로 참조 |
| P4 | 다이제스트만 언급 |

같은 등급 안에서는 참조 노트 수 순. 여러 소스에 나온 논문은 하나로 합쳐 최고 등급.

## Steps

| # | 동작 | 도구 |
|---|---|---|
| 1 | S1 수집 — 출처가 `papers/`인지 `tech-blog-digest/`인지 기록 (P3/P4) | `wiki_backlinks()` |
| 2 | S2 — hub 본문 읽기 | `wiki_list_hubs()` → `wiki_read_note(hub)` |
| 3 | S3 — 열린 질문 | `wiki_list("notes")` → `wiki_read_note` |
| 4 | S2 판정 | (LLM) |
| 5 | 제외 목록 대조 | `wiki_read_note("_meta/reading-queue")` |
| 6 | P1~P4 부여·정렬 → 출력 | (LLM) |
| 7 | (사용자가 제외 지시 시만) append | `wiki_write_note("_meta/reading-queue", …)` |

## 제외 목록 (`_meta/reading-queue.md`)
```markdown
# Reading Queue — 제외 목록
- BM25 — 개념·기법명이지 논문이 아님
- Mini-o3 — 관심 밖 (2026-09-02)
```
한 줄 = 한 항목. 되살리려면 줄을 지운다.

## Output
후보 수·제외 반영 수 → P1~P4 섹션(항목: 이름 · 막고 있는 것/부르는 hub/참조 논문; P4는 개수만 가능) → `🔗 링크만 누락`(표기 → `[[slug]]`, wiki-lint L8) → `❓ 검색어만`(어느 열린 질문에서) → "제외할 항목이 있으면 이유와 함께".

## Failure handling
- `_meta/reading-queue.md` 없음 → 제외 0건으로 진행, 제외 지시 시 생성.
- S1·S2 모두 0건 → "대기열 비어 있음".
- hub 없음(초기 vault) → S1·S3만.
- `limit` 초과 → 상위만, 나머지는 등급별 개수.
