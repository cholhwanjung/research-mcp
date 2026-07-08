---
name: insight-capture
description: 세션 대화에서 여러 논문을 가로질러 종합한 통찰을 vault `notes/<slug>.md` 노트로 저장한다. paper-ingest(논문 1편 요약)와 달리 "논문들을 읽고 논의하며 얻은 종합 판단"을 영속화. 승인 게이트 — 자동 저장 금지.
trigger:
  - "이 통찰 저장"
  - "방금 논의 위키에 남겨줘"
  - "insight 노트로"
  - "notes에 정리"
inputs:
  - 'focus (string, 선택) — 통찰의 초점. 없으면 현 세션 대화에서 후보를 추출해 사용자에게 확인.'
---

## When to invoke
사용자가 세션에서 **여러 논문을 비교·종합해 얻은 판단**(예: "이 방향 논문들은 공통적으로 X를 가정하는데 Y에서 갈린다")을 vault에 영구히 남기고 싶을 때. 논문 ingest·요약은 축적되지만 **논문을 가로지르는 종합 통찰은 대화가 끝나면 소실**된다 — 본 스킬이 그 갭을 메운다.

부르지 말 것:
- 단일 논문 1편 요약 → `paper-ingest`.
- 기존 노트들의 정합성 점검·화해 → `wiki-lint`.
- 프로젝트 문서(작업 관습·구조)의 진화 → `self-improve`.

## 발동 원칙
- **자동 저장 금지** — 초안 diff를 보여주고 사용자 명시 승인 후에만 `wiki_write_note`. (PRD 비목표 "완전 자동 큐레이션" 준수.)
- **출처 명시** — 모든 통찰 문장은 근거 논문 노트를 `[[링크]]`로 특정한다. vault에 근거가 없는 일반론은 통찰로 저장하지 않는다(대신 "열린 질문"으로).
- **원자성** — 한 notes 노트 = 한 통찰(하나의 질문 또는 주장). 통찰이 여럿이면 노트를 분할한다.
- **surgical** — 종합에 실제로 쓰인 논문만 링크. 추측으로 링크를 늘리지 않는다.
- **vault 본문 격리** — notes 노트 본문·헤더·frontmatter 값에 내부 메타 식별자(결정 기록 번호·SKILL·ARCHITECTURE·PRD·PLAN 등)를 넣지 않는다. notes는 사용자 연구 영역이다.

## Steps (tool sequence)

| # | 동작 | 도구 |
|---|---|---|
| 1 | focus 확정 — 사용자 초점 또는 세션 대화에서 통찰 후보 1개 추출 | (대화) |
| 2 | 근거 노트 탐색 — focus 키워드로 vault 내 관련 논문·hub 후보 조회 (전체 로드 대신 관련만) | `wiki_search(focus)` |
| 3 | hub 매핑 — 통찰이 걸릴 안정 hub 1-3개 선택 | `wiki_list_hubs()` |
| 4 | (필요 시) 인용할 논문의 실제 주장 확인 | `wiki_read_note(slug)` |
| 5 | 초안 작성 — frontmatter + body(아래 구조). 통찰 문장마다 `[[근거 논문]]` | (LLM 추론) |
| 6 | **초안 diff를 사용자에게 보여주고 승인 요청** | (대화) |
| 7 | 승인 시 저장 | `wiki_write_note("notes/<slug>", fm, body)` |
| 8 | 교차링크(승인된 것만) — 관련 hub와 근거 논문에서 이 통찰로 양방향 | `wiki_link` |

Step 2에서 `wiki_search`가 근거 논문을 못 찾으면 "Failure handling" 참조.

## Slug 규약
- `notes/<slug>.md`. slug은 통찰을 짧게 요약한 title-slug — 사람·grep 친화. 예: `frozen-encoder-reuse-tradeoff`.
- notes 노트는 arxiv_id를 갖지 않는다(논문이 아님). 근거 논문은 frontmatter `sources`로 링크.

## Frontmatter
> 아래 `#` 코멘트는 본 지침을 읽는 에이전트용 안내이며 실제 vault yaml에는 옮기지 않는다 (vault 본문 격리).

```yaml
type: insight
created: {today}                          # YYYY-MM-DD
sources: ["[[blip-2]]", "[[flamingo]]"]   # 근거 논문 노트 (실제로 인용한 것만)
topics: ["[[topics/vlm]]"]                # 걸리는 안정 hub (wiki_list_hubs 매칭)
tags: []                                  # 자유 태그 (선택)
```

## Body 구조 (고정 헤더)
```markdown
# {통찰 제목}

## 통찰
{한두 문단 — 논문을 가로지르는 종합 판단. 각 주장에 [[근거 논문]] 인라인 링크.}

## 근거 (논문별)
- [[blip-2]] — {이 논문이 뒷받침하는 부분 한 줄}
- [[flamingo]] — {...}

## 열린 질문
- {아직 vault에 근거 논문이 없는 질문 — 후속 paper-ingest 후보}

## Related
- [[topics/vlm]]
```

## Output format (사용자 응답)

```
💡 insight-capture — focus="{focus}"
   근거 후보: {wiki_search 결과 slug 목록}
   hub 매핑: {선택 hub}

저장할 통찰 노트 초안 (notes/{slug}):
```diff
+ ---
+ type: insight
+ sources: ["[[blip-2]]", "[[flamingo]]"]
+ topics: ["[[topics/vlm]]"]
+ ---
+ # {제목}
+ ## 통찰
+ ...
```
교차링크 제안:
- topics/vlm → notes/{slug}
- blip-2 → notes/{slug}

승인하시면 저장 + 교차링크 반영합니다. (수정할 부분 있으면 말씀해 주세요.)
```

## Failure handling
- Step 2 `wiki_search` 0건 → 근거 논문이 vault에 없음. **임의 web fetch 금지.** (a) 통찰만 저장하고 "열린 질문"에 근거 부재를 명시할지, (b) 먼저 `paper-ingest`로 근거를 넣을지 사용자에게 물음.
- 통찰이 단일 논문 범위로 판명 → 그 논문의 paper 노트 본문에 넣는 게 맞다고 안내하고 본 스킬 abort (notes는 "가로지르는" 통찰 전용).
- Step 7 `wiki_write_note` 실패 → 디스크 권한/vault 경로 확인 안내. 부분 반영됐으면 어디까지 됐는지 명시.
- Step 8 `wiki_link` 대상 노트 없음 → 근거 논문이 아직 vault에 없는 경우. 링크 skip하고 사용자에게 알림.

## 후속 호출 제안
- 통찰의 "열린 질문"을 채우려면 제안 검색어로 `paper-ingest`.
- notes가 쌓이면 `wiki-lint`로 통찰↔논문 정합성(근거 논문이 supersede됐는지 등) 점검.
