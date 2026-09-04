---
name: research-autopilot
description: 무인 축적 루프의 한 반복(논문 1편). vault에서 대기열을 유도해 최우선 미수록 논문 1편을 ingest → citation-analysis → hub 판정 → 깨진 링크 정정까지 자동 승인으로 수행하고 `_meta/autopilot-log`에 기록한다. 대기열이 비면 vault 중심 논문의 인용 이웃에서 frontier를 리필한다. `/loop /research-autopilot`으로 반복 호출 — 사용자가 명시적으로 멈출 때까지.
trigger:
  - "autopilot"
  - "밤새 논문 쌓아줘"
  - "무인 ingest 루프"
  - "research-autopilot"
inputs:
  - 'max_papers (int, 선택) — 이번 실행(루프 전체)에서 처리할 최대 논문 수. 기본 0 = 무제한. `_meta/autopilot.md` frontmatter로도 지정.'
---

## When to invoke
사용자가 자리를 비운 사이(밤새) vault를 계속 채우고 싶을 때. 본 스킬은 **한 반복 = 논문 1편**만 처리하고 끝난다. 반복은 `/loop`이 연다 — 스킬 안에서 while 루프를 돌리지 않는다.

부르지 말 것:
- 특정 논문 1편을 지금 넣는 것 → `paper-ingest`.
- 대기열을 보기만 하는 것 → `reading-queue`.
- 정합성 점검·hub 요약 갱신 → `wiki-lint` (autopilot은 lint를 반영하지 않는다).

## 시작·정지 (운용)

```
시작   /loop /research-autopilot         동적 self-pacing (권장). 한 반복이 끝나면 최소 지연(60초)으로 다음 반복 예약
       /loop 30m /research-autopilot     고정 간격. 이전 반복이 안 끝났으면 다음 tick은 밀린다(겹치지 않음). 7일 후 자동 만료

정지   채팅으로 "autopilot 멈춰"          → 루프 종료 (동적: ScheduleWakeup stop / 고정: CronDelete)
       _meta/autopilot.md 의 stop: true  → 다음 반복 시작 시 종료 (Obsidian에서 편집)
       세션 종료                          → 루프는 세션에만 산다

전제   세션이 살아 있어야 한다 — Mac 잠자기 방지(예: caffeinate -dimsu), 데스크톱 앱 유지
```

동적 모드에서 반복을 마칠 때: 정지 조건이 아니면 `delaySeconds=60`으로 같은 프롬프트를 재예약한다(기다릴 외부 상태가 없다 — 작업 자체가 pacing). 정지 조건이면 `stop`으로 루프를 끝내고 사유를 응답에 적는다.

## 자동 승인 규칙 — 무엇을 스스로 결정하고 무엇을 남기는가
원칙: **저장 축은 자동, 판단 축은 사람.** 하위 스킬의 승인 게이트(`paper-ingest` Step 6 신규 hub, `citation-analysis` Step 8)는 본 표로 대체되며 **사용자 turn을 기다리지 않는다.** 미리보기는 출력하되 정지하지 않는다.

| 축 | autopilot 판정 | 남기는 것 |
|---|---|---|
| 논문 노트 저장 (`paper-ingest` Step 8) | 자동 | 로그 |
| `references`/`cited_by` frontmatter + hub wikilink (`citation-analysis` Step 9-10) | 자동 | 로그 |
| 인용 그래프 (`citation-analysis` Step 11) | 자동 | — |
| **신규 hub** | **조건부** — (a) 논문 *자신의* 주제가 기존 hub·alias·related 어디에도 못 붙고, (b) vault에서 그 주제로 묶일 논문이 본 논문 포함 **≥3편**(`wiki_search`로 확인)일 때만. 둘 중 하나라도 아니면 가장 가까운 기존 hub로 매핑하고 `hub_candidate=<slug>`로 로그. refs/cites로는 hub를 만들지 않는다(인용 흐름은 소속 근거 아님) | 로그 → 아침 검토 |
| 깨진 링크 정정 (Step 5) | 자동 — `[[old]]` 토큰 치환만 | 로그 |
| 통찰 노트 (`notes/`) | **안 씀** — 분석 중 판단이 나오면 `insight_candidate=` 한 줄만 로그 | 사람 (`insight-capture`) |
| `wiki-lint` 반영 · "안 읽기로 함" 결정 · hub 재설계 · hub 요약 갱신 | **안 함** | 사람 |

vault 본문에는 내부 메타 식별자를 쓰지 않는다. autopilot의 흔적은 `_meta/`에만 남는다.

## 상태 파일 (`_meta/` — 시스템 영역)

**`_meta/autopilot.md` — 제어.** 사용자가 편집하는 파일이다. 첫 실행 시 아래 템플릿으로 생성.

```markdown
---
stop: false                # true로 바꾸면 다음 반복에서 멈춘다
max_papers: 0              # 이번 실행 최대 처리 편수. 0 = 무제한
run_started: 2026-09-04T23:00
processed: 0               # 이번 실행 누계 (ok + partial)
consecutive_failures: 0
frontier_anchors: []       # 리필에 이미 쓴 anchor slug — 순환용
---
# Autopilot 제어

## 우선 큐
사용자가 지정한 항목. 한 줄 = 한 항목. 대기열보다 먼저 처리되고, 처리되면 줄이 지워진다.
- 2506.01234 — 이유 (선택)
- Generative Agents: Interactive Simulacra — 제목만 있어도 됨

## 건너뜀
autopilot이 풀지 못한 항목. 줄을 지우면 다음 반복에서 다시 시도한다.
- <이름> — <사유> (<날짜>)

## frontier
대기열이 비었을 때 리필된 후보. velocity 순. 처리되면 줄이 지워진다.
- <arxiv_id> — <title> · vel <v> · via <anchor slug>
```

**`_meta/autopilot-log.md` — 이력.** append-only. 한 반복 = 헤더 한 줄 + `key=value` 줄. `grep "^## \[" _meta/autopilot-log.md | tail`로 밤새 이력을 본다.

```markdown
## [2026-09-04 23:12] autopilot | iter=7 | action=ingest | id=2604.01234 | slug=generative-agents | status=ok
source=S2 rank=P2 hub_of_origin=agent-memory pages=14 figures=5/12 refs=20 cites=18
hubs=agent-memory new_hub=- hub_candidate=- links_fixed=2 insight_candidate=-

## [2026-09-04 23:41] autopilot | iter=8 | action=ingest | id=2603.05678 | slug=- | status=fail
step=4b error="SS 429 백오프 후에도 실패" consecutive_failures=1

## [2026-09-05 06:02] autopilot | iter=21 | action=stop | reason=queue_exhausted
processed=13 run_started=2026-09-04T23:00
```

`action` ∈ `ingest | skip | refill | stop`. `status` ∈ `ok | partial | fail`. `reason` ∈ `user | max_papers | consecutive_failures | queue_exhausted | control_parse_error`.

## Steps (tool sequence)

| # | 동작 | 도구 |
|---|---|---|
| 0 | **제어 읽기.** 제어 노트가 없으면 템플릿으로 생성. `stop: true` → `action=stop reason=user` 로그 후 종료. `max_papers > 0`이고 `processed >= max_papers` → `reason=max_papers`. 마지막 로그 헤더가 6시간 이전이면 새 실행으로 보고 `run_started`·`processed`·`consecutive_failures` 초기화 | `wiki_read_note("_meta/autopilot")`, `wiki_read_note("_meta/autopilot-log")` |
| 1 | **대기열 유도** — 아래 순서로, 앞 소스에서 후보가 나오면 뒤 소스는 읽지 않는다. 전부 `## 건너뜀`과 대조. (P0) 제어 노트 `## 우선 큐` → (S1) 깨진 wikilink: 출처가 `_meta/`인 것 제외, `reading-queue`의 P1~P4 등급 + 참조 노트 수로 정렬 → (S2) hub 본문의 평문 미수록 논문 이름: `reading-queue` S2 판정 그대로(vault 기수록 여부는 **뜻으로 대조**, 개념어 제외) → (F) 제어 노트 `## frontier` 위에서부터 | `wiki_backlinks()`, `wiki_list_hubs()`, `wiki_read_note(hub)` |
| 1.5 | 전부 비었으면 **리필**(아래 절) 후 (F)로 진행. 리필도 0건이면 `stop: true` + `reason=queue_exhausted` 로그 후 종료 | (리필 절) |
| 2 | **후보 → arXiv ID.** 이미 ID면 통과. 이름이면 ① 참조 노트의 그 줄에서 `(arXiv:ID)` 병기를 먼저 찾고 ② 없으면 `search_papers(제목, max_results=5)` 상위에서 제목이 **뜻으로 일치**하는 것만 채택. 둘 다 실패 → `## 건너뜀`에 사유 기록, 다음 후보로. 한 반복에서 후보 3개가 연속 건너뛰어지면 `action=skip`으로 반복 종료(루프는 계속) | `search_papers` |
| 3 | **중복 검사.** vault에 이미 있으면 ingest하지 않는다 — Step 5 링크 정정만 하고 다음 후보로 | `wiki_read_note(arxiv_id)` |
| 4a | **ingest** — `paper-ingest` Step 1~8 그대로(대용량 게이트·figure 선별 포함). Step 6의 신규 hub 판정은 "자동 승인 규칙" 표로. 우선 큐 항목에 `citation_pending`이 붙어 있으면 4a는 건너뛰고 4b만 | (`paper-ingest`) |
| 4b | **인용 분석** — `citation-analysis` Step 1~11, `direction=both`, `top_k=20`. Step 8 게이트는 자동 승인. refs/cites 쪽 신규 hub 후보는 만들지 않고 closest 기존 hub로 | (`citation-analysis`) |
| 4c | **신규 hub 생성 시** (표의 조건 충족) — 기존 hub와 같은 frontmatter(`tier: hub`, `title`, `slug`, `aliases`, `parent`, `related`, `summary`, `seed_paper`, `created_at`). `parent`는 가장 가까운 기존 hub로 **필수**. 본문은 소속 논문을 `[[slug\|표기]]`로 링크(평문 금지). 부모 hub 본문 `## 하위 갈래` 절에 `- [[slug]] — 한 줄` 추가(절이 없으면 끝에 신설) | `wiki_write_note("topics/<slug>")`, `wiki_read_note`/`wiki_write_note(parent)` |
| 5 | **링크 정정** — 이 후보를 가리키던 깨진 링크 `[[old]]` / `[[old\|표기]]`를 `[[<new-slug>\|<표기 또는 old>]]`로 치환. 참조 노트마다 read → 토큰 치환 → write(frontmatter는 읽은 그대로 되돌려 보존). `_meta/` 노트는 건드리지 않는다. S2에서 온 후보면 hub 본문의 평문 이름을 `[[slug\|표기]]`로(L8과 같은 규칙) | `wiki_read_note`, `wiki_write_note` |
| 6 | **상태 갱신** — 우선 큐·frontier에서 해당 줄 제거, `processed += 1`(ok/partial), `consecutive_failures`는 ok면 0·fail이면 +1. 로그 append | `wiki_write_note("_meta/autopilot")`, `wiki_write_note("_meta/autopilot-log")` |
| 7 | **종료.** 다음 반복은 루프가 연다. `consecutive_failures >= 3`이면 `stop: true` + `reason=consecutive_failures` + 진단 한 줄을 로그에 남기고 루프를 끝낸다 | — |

Step 5가 없으면 ingest한 논문을 가리키던 링크가 계속 깨진 채 남아 **같은 논문이 다음 반복에 다시 뽑힌다.** Step 3의 중복 검사가 2차 방어지만, 정정을 해야 대기열이 실제로 줄어든다.

## 리필 — 대기열이 비었을 때 frontier 채우기
대기열이 비었다는 것은 vault가 자기 참조를 다 채웠다는 뜻이다. 다음 "중요한 논문"은 새 검색어가 아니라 **vault가 이미 중심으로 삼은 논문의 인용 이웃**에서 뽑는다 — 사용자 관심(vault 구조) × 외부 중요도(citation velocity).

1. **anchor 선정** — Step 1의 `wiki_backlinks()` 📇 블록에서 inbound 수가 가장 많은 `papers/` 노트 3편. `frontier_anchors`에 이미 있는 것은 건너뛰어 순환한다(전부 썼으면 목록을 비우고 처음부터).
2. anchor마다 frontmatter에서 `arxiv_id`를 읽고 `get_citations_by_citations(id, top_k=10)` + `get_references_by_citations(id, top_k=10)`.
3. **필터** — arXiv ID가 있는 것만 → vault 기수록 제외(`wiki_read_note(arxiv_id)`가 노트를 돌려주면 제외) → `## 건너뜀` 제외. survey는 도구가 이미 제외한다.
4. velocity 내림차순 **상위 10건**을 `## frontier`에 기록, anchor 3편을 `frontier_anchors`에 추가. `action=refill anchors=a,b,c added=N` 로그.
5. 0건이면 다음 anchor 3편으로 한 번 더. 그래도 0건이면 `reason=queue_exhausted`로 정지.

frontier는 SS에서 유래해 vault로부터 유도할 수 없으므로 저장한다. 오래된 항목이 남아도 Step 3의 중복 검사가 무해화한다 — 이미 들어온 논문은 ingest되지 않고 줄만 지워진다.

## Output format (사용자 응답 — 반복마다 짧게)

```
🤖 autopilot iter {N} — {ingest|skip|refill|stop}
   {title} (arXiv:{id}) · {rank}/{source} · hubs: {hub, …} · new hub: {-|slug}
   링크 정정 {k}건 · 이번 실행 누계 {processed}편 · 대기열 잔여 ≈{q} (frontier {f})
   → 다음 반복 예약 (60s)   |   ⏹ 정지: {reason}
```

정지 시에는 실행 요약을 덧붙인다: 처리 편수, 새 hub, `hub_candidate`·`insight_candidate` 목록, 건너뜀 건수, 실패 진단.

## Failure handling
- **한 반복 안의 실패는 그 논문만 건너뛴다.** 다른 도구로 우회하지 않는다(web search 등 금지). 사유를 `## 건너뜀`과 로그에 남기고 다음 후보로.
- Step 2 `search_papers` 무결과·제목 불일치 → 건너뜀 (`reason="arXiv 미해석"`). 제목이 비슷해도 저자·연도가 다르면 채택하지 않는다 — 잘못 넣은 논문은 아침에 지우기가 더 비싸다.
- Step 4a `get_paper_by_id` 실패·PDF 다운로드 실패 → `paper-ingest` Failure handling 그대로. 그 논문 `status=fail`.
- Step 4b SS 429 → `citation-analysis`의 백오프·title-only fallback 그대로. 그래도 실패면 **ingest된 노트는 남기고** `status=partial`, 제어 노트 `## 우선 큐`에 `- <id> — citation_pending` 추가 → 다음 반복이 4b만 재시도.
- 같은 종류의 `fail`이 3회 연속 → `stop: true` + 진단 한 줄(예: `SS 429 지속`, `arXiv PDF timeout`). 도구 한계는 아침에 사용자가 판단한다 — 루프가 밤새 헛돌지 않게 한다.
- 제어 노트 frontmatter 파싱 실패(사용자 편집 오류) → 덮어쓰지 않고 `reason=control_parse_error`로 정지.
- Step 5 참조 노트에 토큰 치환 이상의 수정이 필요해 보이면 하지 않고 `link_fix_skipped=<slug>` 로그 — `wiki-lint` 몫.
- `wiki_write_note` 실패(권한·경로) → 즉시 정지. 부분 반영 상태를 로그에 명시.

## 후속 호출 제안 (아침 검토)
- `grep "^## \[" _meta/autopilot-log.md`로 밤새 이력. `new_hub=`·`hub_candidate=`·`insight_candidate=`가 `-`가 아닌 줄만 골라 본다.
- `wiki-lint` — autopilot은 hub 요약을 갱신하지 않으므로 소속이 늘어난 hub는 L4 stale이 된다. L2 orphan도 함께.
- `reading-queue` — 남은 대기열과 `## 건너뜀` 정리. 안 읽을 것은 `_meta/reading-queue.md`로.
- `insight-capture` — 로그의 `insight_candidate` 중 고를 것이 있으면 초안 모드로.
