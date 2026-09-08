---
name: insight-capture
description: 여러 논문을 가로질러 얻은 종합 판단을 vault `notes/<slug>.md`에 저장한다. 기본은 한 줄 후보 제시, 사용자가 고르면 초안 → 승인 후 저장.
trigger:
  - "이 통찰 저장"
  - "방금 논의 위키에 남겨줘"
  - "notes에 정리"
  - "(위임) wiki-lint가 L4·L5·L7 판단을 넘길 때"
inputs:
  - 'focus (선택) — 통찰의 초점. 없으면 세션 대화에서 후보 추출'
---

## When to invoke
세션에서 여러 논문을 비교·종합해 얻은 판단을 영구화할 때 — 논문 요약은 축적되지만 가로지르는 통찰은 대화와 함께 사라진다. 단일 논문 요약은 `paper-ingest`, 정합성 점검은 `wiki-lint`, 프로젝트 문서는 `self-improve`.

## hub 본문 vs 통찰 노트
| | hub 본문 | 통찰 노트 |
|---|---|---|
| 성격 | 분야의 **현재 상태** | **시점이 박힌 판단** |
| 갱신 | 교체됨 | 누적 — 틀려도 남음 |

판별 질문: *반년 뒤 이 서술이 틀리게 됐을 때, 그런 판단을 했었다는 사실이 남아야 하는가?* 남아야 하면 통찰 노트.

## 모드
- **후보 제시** (기본 — 위임·대화 중 판단 발생 시): 한 줄 후보 + 근거 노트 + 발견 경로. **초안을 쓰지 않는다.** 사용자가 반응 없으면 그대로 넘어간다.
- **초안 작성** (사용자가 후보를 고르거나 focus 지정): 아래 Steps.

## 원칙
- 자동 저장 금지 — diff 승인 후에만 `wiki_write_note`.
- 통찰 문장마다 근거 논문을 `[[링크]]`. vault에 근거 없는 일반론은 "열린 질문"으로.
- 한 노트 = 한 통찰. 여럿이면 분할. 실제 쓰인 논문만 링크.
- 노트에 내부 메타 식별자를 넣지 않는다.

## Steps

| # | 동작 | 도구 |
|---|---|---|
| 1 | focus 확정 | (대화) |
| 2 | 근거 노트 탐색 | `wiki_search(focus)` |
| 3 | hub 1-3개 매핑 | `wiki_list_hubs()` |
| 4 | (필요 시) 논문 주장 확인 | `wiki_read_note(slug)` |
| 5 | 초안 — frontmatter + body | (LLM) |
| 6 | diff → **승인 요청** | (대화) |
| 7 | 저장 | `wiki_write_note("notes/<slug>", fm, body)` |
| 8 | 교차링크 — 관련 hub·근거 논문 ↔ 통찰 | `wiki_link` |

## Frontmatter / Body
```yaml
type: insight
created: {YYYY-MM-DD}
sources: ["[[blip-2]]", "[[flamingo]]"]   # 실제 인용한 논문만
topics: ["[[VLM]]"]                       # hub slug 단독
tags: []
```
```markdown
# {통찰 제목}
## 통찰            ← 한두 문단, 각 주장에 [[근거]] 인라인
## 근거 (논문별)   ← - [[slug]] — 뒷받침하는 부분 한 줄
## 열린 질문       ← vault에 근거 논문이 없는 질문 (paper-ingest 후보)
## Related         ← [[hub]]
```
slug는 통찰을 요약한 title-slug (예 `frozen-encoder-reuse-tradeoff`). arxiv_id 없음.

## Output
- 후보 모드: 번호 붙인 한 줄 후보(근거 `[[노트]]` 외 k편 · 발견 경로) + "남길 번호를 말하면 초안을 쓴다". 설명을 붙이면 초안이 된다 — 한 줄로.
- 초안 모드: focus · 근거 후보 · hub 매핑 · 노트 diff · 교차링크 제안 → 승인 요청.

## Failure handling
- `wiki_search` 0건 → 근거가 vault에 없음. web fetch 금지. (a) 열린 질문으로 남기고 저장 (b) `paper-ingest` 먼저 — 사용자에게 선택.
- 단일 논문 범위로 판명 → 그 논문 노트에 넣도록 안내하고 중단.
- 쓰기 실패 → 경로·권한 안내. `wiki_link` 대상 없음 → skip + 알림.
