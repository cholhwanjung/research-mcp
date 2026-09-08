# research-autopilot — 워커 절차

디스패처(`SKILL.md`)가 띄운 서브에이전트가 읽는다. 인라인 모드에선 같은 세션이 직접 수행. **한 반복 = 논문 1편.** 루프 열기와 정지 처리 ⓪③④(열린 start 닫기·cron 삭제·실행 보고서)는 디스패처 몫.

## 워커 계약
- Step 0~7 수행 후 **마지막 메시지**로 "Output format" 블록 + `summary` 한 줄. 15줄 이내. 디스패처는 그대로 릴레이한다.
- **사용자에게 묻지 않는다.** scope가 비어 있을 때만 `action=stop reason=scope_missing` 로그 후 `ask=`. hub에 안 닿는 주제는 묻지 않고 탐색 주제로 등록한다("주제 scope").
- **루프 제어 금지** — ScheduleWakeup·Cron 도구를 건드리지 않는다. 정지 처리 ①②를 했으면 `stop_reason`.
- **figure/table 추출 금지** — `paper-ingest` figure 단계는 페이지 수 무관 skip.
- **도구 로드** — deferred면 워커 프롬프트의 "도구 로드" 줄대로 ToolSearch 한 번에 전부.
- **하위 스킬 이름** — 이 repo에선 `paper-ingest`·`citation-analysis`, 플러그인 설치 프로젝트에선 `research-mcp:` 접두사. Skill 목록에 있는 쪽. 도구 접두사는 워커 프롬프트 환경 줄.
- **읽기 다이어트** — 워커 컨텍스트가 곧 반복 비용이다.
  - 로그 읽기: `grep "^## \[" <vault>/_meta/autopilot-log.md | tail -3`. 디스패처가 `상태:` 줄을 넘겼으면 생략.
  - 로그 쓰기: `printf '%s\n' '<줄>' >> <vault>/_meta/autopilot-log.md`. `wiki_write_note`는 전체 재작성이라 로그엔 안 쓴다(Bash 없는 환경에서만).
  - 논문: `read_paper(arxiv_id, max_pages=15)`. 결과가 파일이면 Read 한 번.
  - `tldr`·`insight_candidate` 200자 이내.
  - `<vault>` = `OBSIDIAN_VAULT_PATH`(기본 `~/Documents/research-wiki`) — 워커 프롬프트 환경 줄.
- vault 본문(`papers/`·`topics/`·`notes/`·`graphs/`)에 내부 메타 식별자 금지. 흔적은 `_meta/`에만. figure 생략 사유는 노트에 "_Figure/table 추출 생략됨 (무인 수집). 필요 시 on-demand 추출 가능._" 한 줄.

## 주제 scope
scope = **hub slug 집합 ∪ 탐색 주제 slug 집합**. hub는 `wiki_list_hubs()`에 있는 것 — 지정 hub의 자식(`parent` 체인)은 자동 포함, 부모는 불포함. 탐색 주제는 제어 노트 `## 탐색 주제`에 등록된 것.

1. **입력 없으면 돌지 않는다** — 인자에도 제어 노트 `scope`에도 없으면 `scope_missing`. 빈 값은 "전체"가 아니다.
2. **전체는 `all`로만** — "전체"·"모든 hub"·`all` 명시 시에만. 등록된 탐색 주제는 `all`에도 포함된다.
3. **실행 단위** — 어떤 사유든 정지하면 `scope`·`scope_input`을 비운다. `## 탐색 주제`는 남는다 — 다음 실행에서 그 slug를 scope에 다시 주면 이어서 탐색. 정지 기록 없이 끊긴 경우는 같은 실행이라 남는다.

해석: slug·자연어 모두 `wiki_list_hubs()`의 slug·alias·title·summary와 `## 탐색 주제`에 **뜻으로** 대응. 한 부모 아래로 묶이면 부모(자식 포함, "메모리" → `agent-memory`), 여러 hub에 걸치면 전부 포함. **어느 hub·탐색 주제에도 안 닿는 부분은 탐색 주제로 등록한다 — 묻지 않는다**: `- <slug> — <정의 한 줄> · query: "<arXiv 검색어(영어)>" · parent: <가장 가까운 hub|-> · members: [] · seeded: -`. slug는 hub 규약(영문 kebab). **첫 해석을 고정** — `scope_input`과 `scope`를 함께 저장, 다음 tick 인자가 `scope_input`과 같으면 재해석 없이 저장된 `scope`. 새로 해석했을 때만 보고 첫 줄에 `scope 확정: graph-rag (+temporal-leakage) · 탐색(신규): ts-forecasting-agents (parent finance-agents) ← "원문"`.

탐색 주제는 `topics/` 노트가 아니다 — vault엔 아무것도 만들지 않는다. **`members` ≥ 3이 되면 hub로 승격**(Step 4c′). 승격 전 소속 논문은 closest 기존 hub(보통 parent)로 태그되고 `members`에만 기록된다.

필터 (`all`이면 S0 외 전부 생략):

| 지점 | 규칙 |
|---|---|
| S1 (깨진 링크) | **참조 노트**로 판정 — scope hub 소속 논문(📇 블록에서 `topics/<hub>` inbound의 `papers/`), scope hub 자신, scope hub를 `topics`로 가진 `notes/`에서 온 항목은 통과. 소속 없는 참조 노트(`tech-blog-digest/` 등)는 **항목 제목**으로 판정 — 애매하면 제외 |
| PA | scope hub 소속 논문만 |
| S2 (hub 평문 이름) | scope hub(자식 포함) 본문만 읽는다 |
| S0 (seed) | `## 탐색 주제` 중 `members: []`·`seeded: -`인 것만 ("seed" 절) |
| P0 우선 큐 | **필터 없음** |
| Step 3.5 게이트 | 제목·초록이 어느 scope hub의 정의·alias에도, 어느 탐색 주제의 정의·query에도 맞지 않으면 `## 건너뜀`에 `scope 밖` |
| 리필 | anchor는 scope 소속 논문(탐색 주제 `members` 포함), 후보는 제목이 scope hub 정의·alias 또는 탐색 주제 정의에 맞는 것만 |
| 신규 hub | `parent`가 scope 집합 안이어야 생성. 아니면 closest 기존 hub + `hub_candidate=`. **`explore: true`면** 후보가 `scope_input`의 의도 안에 들 때 탐색 주제로 등록(실행당 `max_topics`까지, query는 그 주제의 영어 검색어) — 다음 반복에 seed |

실행 중 변경은 제어 노트에서 — 다음 반복부터. `## 건너뜀`의 `scope 밖`은 줄을 지우면 되살아난다. 탐색 주제 줄을 지우면 탐색 중단(이미 들어온 논문은 남는다).

## seed — 탐색 주제 부트스트랩 (S0)
탐색 주제는 vault 참조가 없어 S1·S2·PA로 잡히지 않는다. 한 번만 외부에서 씨를 뿌리고, 그 뒤는 리필(인용 이웃)이 이어받는다.
1. 대상: `## 탐색 주제` 중 `members: []`이고 `seeded: -`인 것. 한 반복에 하나.
2. `search_papers(query, max_results=20)` → arXiv ID 목록(survey는 도구가 이미 제외).
3. vault 기수록(`wiki_read_note(arxiv_id)`)·`## 건너뜀`·`## 보류` 제외 → 남은 것에 `get_paper_by_id`의 `Velocity` → `min_velocity` 이상만(미달은 `## 보류` +30일).
4. velocity 내림차순 상위 10건을 `## frontier`에 `- <arxiv_id> — <title> · vel <v> · via seed:<topic>`으로. 탐색 주제 줄 `seeded: <오늘>`. `action=refill source=S0 topic=<slug> added=N` 로그.
5. 0건이면 `seeded: <오늘> (0건)` — 재시도하지 않는다. 아침에 query를 고치고 `seeded: -`로 되돌리면 다시 seed.

## 중요도 게이트 (Step 3.6)
- 지표: `get_paper_by_id` 응답의 `Velocity`(인용수/연). 임계: 제어 노트 `min_velocity`(기본 10, 리필도 같은 값).
- 통과: velocity ≥ 임계 **또는** 그 논문을 가리키는 vault 노트 ≥ 2 (frontier는 via anchor ≥ 2).
- 면제: P0 · P1·P2 · PA · `resumed`. 대상: P3 단일 참조 · P4 · frontier · S0 seed(seed 시점에 판정, ingest 시 캐시로 재확인).
- 미달: `## 보류`에 velocity·날짜·재평가일(+30일). 재평가일 전엔 대기열 제외, 지나면 다시 후보. 통과하면 보류 줄 삭제. 메타 조회 실패 → +7일.
- 입력은 Step 3.5의 `get_paper_by_id` 응답 — 추가 호출 없음.

## 자동 승인 규칙
**저장 축은 자동, 판단 축은 사람.** 하위 스킬의 승인 게이트(`paper-ingest` 신규 hub, `citation-analysis` Step 8)는 이 표로 대체 — 미리보기는 내되 정지하지 않는다.

| 축 | 판정 | 남기는 것 |
|---|---|---|
| 논문 노트 저장 | 자동 — 텍스트 요약만 | 로그 |
| figure/table 추출 | **안 함** — `figures: []`, `figures_skipped: true` | 아침 on-demand |
| `references`/`cited_by` + hub wikilink + 인용 그래프 | 자동 | 로그 |
| 신규 hub | 조건부 — (a) 논문 *자신의* 주제가 기존 hub·alias·related에 못 붙고 (b) 그 주제로 묶일 논문이 본 논문 포함 ≥3편(`wiki_search`) (c) `all`이 아니면 `parent`가 scope 안. 하나라도 아니면 closest 기존 hub + `hub_candidate=<slug>`. refs/cites로는 hub를 만들지 않는다 | 로그 → 아침 |
| 깨진 링크 정정 (Step 5) | 자동 — `[[old]]` 토큰 치환만 | 로그 |
| 통찰 노트 | **안 씀** — `insight_candidate=` 한 줄만 | 사람 (`insight-capture`) |
| `wiki-lint` 반영 · "안 읽기" 결정 · hub 재설계·요약 갱신 | 안 함 | 사람 |

## 상태 파일 (`_meta/`)

**`_meta/autopilot.md` 제어** — 사용자가 편집. 없으면 아래 템플릿으로 생성(`scope`는 비어 있다). `wiki_read_note`/`wiki_write_note`.

```markdown
---
stop: false                # true면 다음 반복에서 정지
max_papers: 0              # 0 = 무제한. 정지해도 남는다
min_velocity: 10           # 중요도 게이트·리필 임계. 정지해도 남는다
scope: []                  # 실행마다 사용자가 준다. 전체는 all. 정지 시 비움
scope_input: ''            # scope 원문. 같으면 재해석 안 함. 정지 시 비움
run_started: ''            # Step 0에서 채움. 보고서 집계 시작점. 정지 시 비움
processed: 0               # 이번 실행 누계 (ok+partial). 정지 시 0
consecutive_failures: 0    # 정지 시 0
frontier_anchors: []       # 리필에 쓴 anchor slug (순환)
deleted_jobs: []           # 정지 시 지운 cron id. 새 실행 시작 시 비움
explore: false             # true면 실행 중 발견한 hub 후보도 의도 안이면 탐색 주제로 (실행당 max_topics)
max_topics: 3              # explore로 편입할 탐색 주제 상한 (실행당)
---
# Autopilot 제어

## 우선 큐
사용자 지정. 한 줄 = 한 항목. 대기열보다 먼저, 처리되면 줄 삭제. scope 필터 없음.
- 2506.01234 — 이유 (선택)
- Generative Agents: Interactive Simulacra — 제목만도 됨

## 건너뜀
autopilot이 풀지 못한 항목. 줄을 지우면 재시도.
- <이름> — <사유> (<날짜>)

## 보류
중요도 미달. 재평가일 지나면 다시 후보. 줄 삭제 = 즉시 재평가, 우선 큐로 옮기면 게이트 없이.
- <이름 또는 arxiv_id> — velocity <v> (<날짜>) · 재평가 <날짜+30일>

## frontier
대기열이 비었을 때 리필된 후보와 탐색 주제 seed. velocity 순. 처리되면 줄 삭제.
- <arxiv_id> — <title> · vel <v> · via <anchor slug|seed:<topic>>

## 탐색 주제
scope의 자연어 중 hub에 없는 주제. 워커가 등록하고 seed한다. members ≥ 3이면 hub로 승격. 줄을 지우면 탐색 중단.
- <slug> — <정의 한 줄> · query: "<arXiv 검색어>" · parent: <hub|-> · members: [] · seeded: -
```

**`_meta/autopilot-log.md` 이력** — append-only, frontmatter 없음. 한 반복 = `start` 헤더 + 결과 헤더 + `key=value` 3줄 + 빈 줄. 읽기는 헤더 `tail -3`, 쓰기는 `>>`.

```markdown
## [2026-09-04 23:05] autopilot | iter=7 | action=start | id=2604.01234 | source=S2 | rank=P2 | velocity_est=42.0 | scope=graph-rag,finance-agents
## [2026-09-04 23:12] autopilot | iter=7 | action=ingest | id=2604.01234 | slug=generative-agents | status=ok
source=S2 rank=P2 hub_of_origin=agent-memory velocity=42.0 gate=exempt(P2) pages=14 figures=skipped refs=20 cites=18 resumed=false interrupted=-
hubs=agent-memory topic=- new_hub=- hub_candidate=- links_fixed=2 held=1 insight_candidate=-
title="Generative Agents: …" tldr="관찰·성찰·계획을 쌓는 메모리 스트림으로 …"

## [2026-09-05 06:02] autopilot | iter=21 | action=stop | reason=queue_exhausted
processed=13 run_started=2026-09-04T23:00 scope=graph-rag,finance-agents scope_input="graph rag랑 금융 트레이딩 에이전트"
```

enum — `action` ∈ `start|ingest|skip|refill|stop` · `source` ∈ `P0|S1|S2|S0|PA|F` · `rank` ∈ `P0|P1|P2|P3|P4|P5|-`(P5 = seed) · `topic` ∈ `<탐색 주제 slug>|-` · `status` ∈ `ok|partial|fail` · `gate` ∈ `exempt(<rank>)|pass(v=<velocity>)|pass(refs=<n>)` · `figures` ∈ `skipped|extracted|-` · `pages` ∈ `<int>|-`(`-`는 PDF를 안 읽은 PA·`resumed`) · `reason` ∈ `user|max_papers|consecutive_failures|queue_exhausted|scope_missing|control_parse_error` · `interrupted` ∈ `-|worker_rate_limit|worker_timeout|session|user_stop|consecutive_failures|unknown`(이어받아 닫은 반복에만). 없음·해당 없음은 전부 `-`. 셋째 줄 `title`·`tldr`·`insight_candidate`(200자)는 실행 보고서의 재료 — 보고서는 노트를 다시 읽지 않는다.

**`start`만 있고 결과 줄이 없으면 끊긴 반복** — 복구는 로그가 아니라 vault 상태로 판정한다(Step 0·3).

## Steps

| # | 동작 | 도구 |
|---|---|---|
| 0 | **제어 읽기 + scope + 열린 start.** 디스패처의 `상태:` 줄이 있으면 로그 tail 생략(제어 노트는 본문 절이 필요해 읽는다). 제어 노트 없으면 템플릿 생성. 인자 `max_papers` 기록. **`stop: true`**(인라인 모드에서만 도달): Cron 도구가 있으면 `CronList`로 `deleted_jobs` id 생존 확인 → 살아 있으면 다시 지우고 종료. 아니면 인자에 scope가 있으면 새 실행(`stop: false`, `deleted_jobs: []`), 없으면 "정지 상태 — 새로 /loop scope=…" 한 줄 종료(로그 없음). **scope**: ① 인자 — `scope_input`과 같으면 저장된 `scope` 재사용, 다르면 해석·검증 후 갱신 + 확정 slug echo. hub에 안 닿는 부분은 `## 탐색 주제`에 등록하고 그 slug를 `scope`에 넣는다 ② 인자 없으면 제어 노트 `scope` — 둘 다 비면 `action=stop reason=scope_missing` 로그(직전 헤더가 이미 `scope_missing`이면 생략) + `ask=` 종료 — 제어 노트는 안 건드린다. `run_started` 비면 현재 시각. `max_papers > 0`이고 `processed >= max_papers` → `reason=max_papers` 정지 ①②. **열린 start**: 마지막 헤더가 결과 줄 없는 `start`면 대기열을 유도하지 않고 그 `id`·`iter`를 이어받아 Step 3으로(3.5·3.6은 통과로 보고 3.7도 생략, 결과 줄에 `interrupted=<원인>`). 아니면 `iter` = 마지막 + 1 | `wiki_read_note("_meta/autopilot")` · `grep … \| tail -3` · `wiki_list_hubs()` |
| 1 | **대기열 유도** — 세 소스를 모아 **등급 순**으로 합친다. 전부 `## 건너뜀`·`## 보류`(재평가일 전)와 대조. (P0) `## 우선 큐` · (S1) 깨진 wikilink — `_meta/` 출처 제외, scope 필터, 등급은 `reading-queue` 기준(논문 노트 출처 P3, 다이제스트 P4, 다른 항목을 막으면 P1) · (S2) hub 본문의 평문 미수록 논문 — scope hub만(`all`이면 전부), `reading-queue` S2 판정(뜻으로 대조, 개념어 제외), P2 · (PA) 읽었지만 인용 지도 없는 논문 — scope 소속 `papers/` 중 `references`도 `cited_by`도 없는 것: `grep -L '^references:\|^cited_by:' <vault>/papers/*/*.md` ∩ 📇 scope 소속(본문 안 읽음; 코드 실행 없는 환경이면 PA 생략). · (S0) `## 탐색 주제` 중 `members: []`·`seeded: -`인 것이 있으면 이번 반복에 하나 seed("seed" 절) — 결과는 `## frontier`의 `via seed:<topic>` 항목, 등급 **P5**. **정렬 P0 → P1 → P2 → P3 → P4 → P5(seed) → PA → (F) `## frontier`의 나머지(velocity 순).** 같은 등급은 참조 노트 수 → scope 인자 순 → hub 본문 등장 순 | `wiki_backlinks()`, `wiki_read_note(hub)`, (S0) `search_papers`·`get_paper_by_id` |
| 1.5 | 전부 비면 **리필** 후 (F). 리필도 0건이면 `reason=queue_exhausted` 정지 ①② | (리필 절) |
| 2 | **후보 → arXiv ID.** ID면 통과. 이름이면 ① 참조 노트 그 줄의 `(arXiv:ID)` ② `search_papers(제목, max_results=5)`에서 제목이 **뜻으로 일치**하는 것만(저자·연도 다르면 불채택). 실패 → `## 건너뜀`, 다음 후보. 3개 연속 건너뜀이면 `action=skip`으로 반복 종료 | `search_papers` |
| 3 | **중복 검사 + 재개 판정.** 노트 **없으면** 3.5로(이어받는 중이면 4a). **있으면** ⓐ refs·cited_by 없고 `topics`가 scope와 겹침(`all`이면 무조건) → 3.5·4a 생략, 4b부터(`resumed=true`) ⓑ refs/cited_by 있고 **열린 start의 id** → 노트·그래프까지 쓰고 끊긴 것, Step 5·6만으로 닫는다(`interrupted=`) ⓒ 그 외 → Step 5 링크 정정만, 다음 후보 | `wiki_read_note(arxiv_id)` |
| 3.5 | **scope 게이트** (`all` 아닐 때) — `get_paper_by_id`의 제목·초록이 어느 scope hub 정의·alias에도, 어느 탐색 주제 정의·query에도 안 맞으면 `## 건너뜀`에 `scope 밖 (<scope>)` | `get_paper_by_id` |
| 3.6 | **중요도 게이트** — 위 절. 판정을 `gate=`로 | (3.5 응답) |
| 3.7 | **start 로그** — 대상 확정 직후, 무거운 작업 전. `velocity_est=`는 대기열 시점 추정값. 이어받는 중이면 생략 | `>>` |
| 4a | **ingest** — `paper-ingest`, 단 `read_paper(max_pages=15)`, figure/table 단계 skip(`figures: []`, `figures_skipped: true`, `## Figures` 생략 한 줄), 신규 hub는 자동 승인 규칙. PA·`resumed`·`citation_pending`은 4a 생략 | (`paper-ingest`) |
| 4b | **인용 분석** — `citation-analysis` `direction=both`, `top_k=20`. anchor가 최근 1~2년이면 `exclude_recent_year=False, min_velocity=0`. Step 8 자동 승인. refs/cites 쪽 신규 hub 없음(closest 기존 hub) | (`citation-analysis`) |
| 4c | **신규 hub 생성** (조건 충족 시) — 기존 hub와 같은 frontmatter(`tier: hub`, `title`, `slug`, `aliases`, `parent`, `related`, `summary`, `seed_paper`, `created_at`). `parent` 필수(`all` 아니면 scope 안). 본문의 소속 논문은 `[[slug\|표기]]`. 부모 hub `## 하위 갈래`에 `- [[slug]] — 한 줄`(절 없으면 신설) | `wiki_write_note("topics/<slug>")`, parent read/write |
| 4c′ | **탐색 주제 소속·승격** — 이 논문 자신의 주제가 어느 탐색 주제와 맞으면 그 줄 `members`에 slug 추가(`topic=<slug>`). `members` ≥ 3이면 hub 생성: 4c와 같은 frontmatter(`parent`는 탐색 주제의 parent, `-`면 root; `seed_paper`는 첫 member), 본문에 members를 `[[slug\|표기]]`로, 각 member에 `wiki_link(member, <slug>)`, parent `## 하위 갈래` 갱신, 탐색 주제 줄에 `승격 <오늘>`, `new_hub=<slug>`. slug가 같으므로 scope 집합은 변하지 않는다. **`explore: true`**이고 이 논문의 주제가 어느 hub·탐색 주제에도 안 붙으며(`hub_candidate`) `scope_input`의 의도 안이면, 실행당 `max_topics`까지 탐색 주제로 등록(members에 이 논문) — 다음 반복에 seed | `wiki_write_note("_meta/autopilot")`, `wiki_write_note("topics/<slug>")`, `wiki_link` |
| 5 | **링크 정정** — 이 논문을 가리키던 `[[old]]`/`[[old\|표기]]`를 `[[<slug>\|<표기 또는 old>]]`로. 참조 노트마다 read → 토큰 치환 → write(frontmatter 보존). `_meta/`는 제외. source 무관하게 scope hub 본문에 이 논문 이름이 평문으로 남아 있으면 `[[slug\|표기]]`(축약 표기도 뜻으로 대조) — 방금 처리한 논문에 한정, 다른 논문은 `wiki-lint` 몫 | `wiki_read_note`, `wiki_write_note` |
| 6 | **상태 갱신 + 결과 로그** — 우선 큐·frontier에서 해당 줄 제거, `processed += 1`(ok/partial), `consecutive_failures` ok면 0·fail이면 +1. 결과 헤더 + `key=value` 3줄 append(이어받은 반복이면 `interrupted=`). `gate=`·검증 `velocity=`·`topic=`(4c′ 소속이면 slug)·`title`·`tldr`·`insight_candidate` | `wiki_write_note("_meta/autopilot")`, `>>` |
| 7 | **종료 검사** — `consecutive_failures >= 3` → 정지 ①②(`consecutive_failures`) + 진단 한 줄. `max_papers` 도달 → 정지 ①②(`max_papers`) — 다음 tick을 기다리지 않는다. 정지했으면 `stop_reason` | — |

**쓰기 순서 (고정)**: ① 논문 노트 → ② 인용 frontmatter → ③ 그래프 → ④ 논문→hub 링크·신규 hub·부모 hub → ⑤ 참조 노트 링크 정정. **새 slug를 가리키는 링크는 노트 파일이 생긴 뒤에만** — 어디서 끊겨도 깨진 링크가 새로 생기지 않는다.

**정지 처리 ①② (워커)**: ① `## [ts] autopilot | iter=N | action=stop | reason=…` + `processed=… run_started=… scope=… scope_input="…"` append ② 제어 노트 `stop: true`, `scope: []`, `scope_input: ''`, `run_started: ''`, `processed: 0`, `consecutive_failures: 0`(`max_papers`·`min_velocity`·`frontier_anchors`·`deleted_jobs`·본문 절 유지) → 보고 `stop_reason`. 워커는 자기 반복을 닫은 뒤에만 ①②를 하므로 열린 start를 남기지 않는다. `scope_missing`은 대기 — ②를 하지 않는다.

## 리필 — 대기열이 비었을 때
다음 논문은 새 검색어가 아니라 **vault가 중심으로 삼은 논문의 인용 이웃**에서 — 사용자 관심(vault 구조) × 외부 중요도(velocity).
1. anchor — 📇 블록에서 inbound 최다 `papers/` 3편(`all` 아니면 scope hub inbound 논문 중). `frontier_anchors`에 있는 것은 건너뛰어 순환(다 썼으면 비우고 처음부터).
2. anchor마다 `arxiv_id`로 `get_citations_by_citations(id, top_k=10, min_velocity=<제어 노트>)` + `get_references_by_citations(id, top_k=10, min_velocity=<같은 값>)`. 최근 1~2년 anchor는 citations에 `exclude_recent_year=False`.
3. 필터 — arXiv ID 있는 것만 → vault 기수록 제외(`wiki_read_note(arxiv_id)`) → `## 건너뜀` 제외 → `all` 아니면 제목이 scope hub 정의·alias에 맞는 것만(애매하면 제외).
4. velocity 내림차순 상위 10건을 `## frontier`에, anchor 3편을 `frontier_anchors`에. `action=refill anchors=a,b,c added=N scope=…` 로그.
5. 0건이면 다음 anchor 3편으로 한 번 더. 그래도 0건 → `queue_exhausted` 정지 ①②.

frontier는 SS 유래라 vault에서 유도할 수 없어 저장한다. 오래된 항목은 Step 3 중복 검사가 무해화한다.

## Output format (마지막 메시지 — 디스패처가 그대로 릴레이)
```
🤖 autopilot iter {N} — {ingest|skip|refill|stop} · scope: {hub, …|all}
   (새로 해석했을 때만) scope 확정: {slug, …} (+{자식}) ← "{scope_input}"
   {title} (arXiv:{id}) · {rank}/{source}{ · resumed}{ · 이어받음 interrupted={원인}} · vel {v} · hubs: {…}{ · 탐색: {topic}} · new hub: {-|slug}
   TL;DR: {tldr}{ · 통찰 후보: {insight_candidate}}
   링크 정정 {k}건 · 보류 {h}건 · 이번 실행 누계 {processed}편{ / max {max_papers}} · 대기열 잔여 ≈{q} (frontier {f})
   → 다음 tick 대기   |   ⏹ 정지: {reason} — cron 종료, scope·카운터 비움. 재개는 새 /loop
summary iter= action= id= slug= status= hubs= topic= new_hub= hub_candidate= links_fixed= held= processed= queue= frontier= interrupted= stop_reason= ask=
```
정지 시 실행 요약 한두 줄(처리 편수·새 hub·`hub_candidate`·`insight_candidate`·건너뜀(scope 밖)·보류·실패 진단). `scope_missing`이면 `ask=`에 원문과 후보 hub만.

## Failure handling
- **반복 안의 실패는 그 논문만 건너뛴다.** 다른 도구로 우회하지 않는다(web search 금지). `## 건너뜀`과 로그에 사유.
- **끊긴 반복 이어받기** — 열린 `start`면 그 id·iter를 이어받아 노트 유무에 따라 처음부터 / 4b부터 / Step 5·6만으로 닫고 `interrupted=<원인>`(Step 0·3). `consecutive_failures`는 D0가 올리고 성공하면 Step 6에서 0.
- **반복 중 컨텍스트 압축** — 아직 안 쓴 중간 결과가 요약됐으면 추측하지 말고 도구를 다시 부른다(`read_paper`는 디스크, SS는 1주 캐시).
- Step 2 무결과·제목 불일치 → 건너뜀(`arXiv 미해석`).
- S0 `search_papers` 실패(429·timeout) → 이번 반복은 seed 생략, 다음 반복 재시도. 3회 연속이면 탐색 주제 줄에 `seeded: <오늘> (실패)`로 표시하고 멈춘다(아침에 query 수정 후 `seeded: -`). seed 0건은 실패가 아니다.
- Step 3.5 scope 밖 · Step 3.6 미달 → 실패 아님, `consecutive_failures`에 안 센다. 메타 조회 실패로 판정 불가 → 보류 +7일.
- `⏳`(SS 거절·일시 장애)는 없는 논문이 아니다 — 건너뜀·보류에 넣지 않고 `status=fail`(진단 `SS 429`)로 닫고 우선 큐 항목은 남긴다. `❌`만 미매핑. `⏳` 3회 연속이면 `consecutive_failures` 정지가 밤새 헛도는 것을 막는다.
- Step 4a `get_paper_by_id`·PDF 실패 → `paper-ingest` Failure handling, `status=fail`.
- Step 4b SS 429 → `citation-analysis` 백오프·title-only fallback. 그래도 실패면 노트는 남기고 `status=partial`, `## 우선 큐`에 `- <id> — citation_pending` → 다음 반복이 4b만.
- 같은 종류 `fail` 3회 연속 → `reason=consecutive_failures` 정지 ①② + 진단 한 줄(`SS 429 지속`, `arXiv PDF timeout`). 도구 한계는 아침에 사용자가 판단한다.
- 제어 노트 frontmatter 파싱 실패 → 덮어쓰지 않고 `control_parse_error` 정지 ①②. scope에 없는 hub 이름은 파싱 오류가 아니라 `scope_missing`.
- Step 5 토큰 치환 이상이 필요하면 하지 않고 `link_fix_skipped=<slug>` 로그 — `wiki-lint` 몫.
- `wiki_write_note` 실패 → 즉시 정지 ①②, 부분 반영 상태 로그.
