# research-autopilot — 워커 절차

디스패처(`SKILL.md`)가 띄운 서브에이전트 워커가 읽는 파일이다. Agent 도구가 없는 인라인 모드에서는 같은 세션이 이 파일을 읽고 직접 수행한다. **한 반복 = 논문 1편.** 반복을 여는 것(`/loop`·cron)과 정지 처리 ③④(cron 삭제·실행 보고서)는 디스패처 몫이다.

## 워커 계약
- Step 0~7을 수행하고 **마지막 메시지**로 아래 "Output format" 블록 + `summary` 한 줄을 낸다. 15줄 이내. 디스패처는 요약·재해석 없이 그대로 릴레이한다.
- **사용자에게 묻지 않는다.** 질문이 필요한 지점(scope 미해석·갈래 걸침)은 `action=stop reason=scope_missing` 로그 후 `ask=`에 요지(원문·후보 hub)를 담아 보고한다. 질문문은 디스패처가 만든다.
- **루프 제어 금지** — ScheduleWakeup·Cron 도구를 건드리지 않는다. 정지 처리 ①②를 했으면 `stop_reason`으로 알린다.
- **figure/table 추출 금지** — `paper-ingest` 5a~5c는 페이지 수와 무관하게 skip. 텍스트 요약만.
- **하위 스킬 이름** — `paper-ingest`·`citation-analysis`는 이 repo 안에선 맨 이름, 플러그인으로 설치된 프로젝트에선 `research-mcp:paper-ingest`·`research-mcp:citation-analysis`다(Skill 도구 목록에 있는 쪽을 쓴다). 도구 접두사는 워커 프롬프트 환경 줄의 값.
- **읽기 다이어트** — 워커 컨텍스트가 곧 반복 비용이다(실측 편당 230~307K 토큰).
  - 로그 읽기: Bash `grep "^## \[" <vault>/_meta/autopilot-log.md | tail -3`로 헤더 3줄만. 전체를 읽지 않는다. 디스패처가 프롬프트 `상태:` 줄로 직전 헤더를 넘겼으면 이것도 생략.
  - 로그 쓰기: Bash `printf '%s\n' '<줄>' >> <vault>/_meta/autopilot-log.md`로 append. `wiki_write_note`는 파일 전체 재작성이라 로그엔 쓰지 않는다. Bash 없는 환경에서만 `wiki_read_note` → `wiki_write_note`.
  - 논문: `read_paper(arxiv_id, max_pages=15)`. 결과가 파일로 떨어지면 Read 한 번(offset/limit)으로 읽고 `cat`으로 다시 읽지 않는다.
  - `tldr`·`insight_candidate`는 200자 이내.
  - `<vault>` = `OBSIDIAN_VAULT_PATH`(기본 `~/Documents/research-wiki`) — 워커 프롬프트 환경 줄의 값.
- vault 본문(`papers/`·`topics/`·`notes/`·`graphs/`)에 내부 메타 식별자를 쓰지 않는다. autopilot의 흔적은 `_meta/`에만. figure 생략 사유도 노트엔 "_Figure/table 추출 생략됨 (무인 수집). 필요 시 on-demand 추출 가능._" 한 줄만.

## 주제 scope — 실행마다 명시, 기본값 없음
scope는 **hub slug의 집합**이다 — `wiki_list_hubs()`에 있는 것만, 자유 문자열 금지. 지정한 hub의 자식 hub(`parent` 체인으로 아래 달린 것)는 자동 포함, 부모는 포함하지 않는다. 예: `graph-rag,finance-agents` → `finance-agents`의 자식 `temporal-leakage`까지가 scope 집합.

**세 가지 규칙:**
1. **입력이 없으면 돌지 않는다.** 인자에도 제어 노트 `scope`에도 값이 없으면 `scope_missing`으로 보고하고 반복을 끝낸다. 빈 값은 "전체"가 아니라 "미입력"이다.
2. **전체는 `all`로만.** 사용자가 "전체"·"모든 hub"·`all`이라고 명시할 때만 `scope: all`로 저장하고 모든 hub를 대상으로 한다. 가장 비싼 경로이므로 가장 명시적인 입력을 요구한다.
3. **scope는 실행(run) 단위다.** 어떤 사유든 정지하면(`user`·`max_papers`·`consecutive_failures`·`queue_exhausted`) 제어 노트의 `scope`·`scope_input`을 비운다 — 다음 시작은 새 `/loop`에서 다시 받는다. 정지 기록 없이 끊긴 경우(세션 사망·한도 거부)는 같은 실행의 재개이므로 scope가 남아 있다.

**입력 형식과 해석:**
- slug 관례(`scope=graph-rag,finance-agents`)와 자연어("graph rag랑 금융 트레이딩 에이전트") 모두 같은 경로다 — 어느 쪽이든 모델이 읽어 `wiki_list_hubs()`의 slug·alias·title·summary에 **뜻으로** 대응시킨다.
- **첫 해석을 고정한다.** 제어 노트에 원문 `scope_input`과 해석 결과 `scope`를 함께 저장한다. 다음 tick의 인자가 `scope_input`과 같으면 다시 해석하지 않고 저장된 `scope`를 쓴다 — `/loop`은 매 tick 같은 문자열을 넘기므로 자연어를 tick마다 재해석하면 밤중에 매핑이 흔들릴 수 있다. 인자가 달라졌을 때만 다시 해석하고 둘 다 갱신한다.
- **확정 slug를 되돌려 보여준다.** 새로 해석했을 때 보고 첫 줄에 `scope 확정: graph-rag, finance-agents (+temporal-leakage) ← "graph rag랑 금융 트레이딩 에이전트"`처럼 자식 hub까지 명시한다. 잘못 매핑됐으면 사용자가 그 자리에서 고친다.
- **애매하면 고르지 않는다.** 표현이 한 부모 hub 아래로 묶이면 부모로 해석한다(자식 자동 포함 — "메모리" → `agent-memory`). 서로 다른 갈래의 hub에 걸치거나 어느 hub에도 닿지 않으면 `scope_missing` + `ask=`에 원문과 후보 목록.
- **설정만 하는 발화**(시작 지시 없이 scope만 말한 것)는 디스패처 D0가 제어 노트에 기록한다 — 워커까지 오지 않는다.

scope가 거는 필터 (`all`이면 전부 생략):

| 지점 | 규칙 |
|---|---|
| 대기열 S1 (깨진 링크) | **참조 노트**로 판정. scope hub 소속 논문(`wiki_backlinks()` 📇 블록에서 `topics/<hub>`의 inbound에 있는 `papers/`), scope hub 자신, scope hub를 `topics`로 가진 `notes/`에서 온 항목은 통과. 소속이 없는 참조 노트(`tech-blog-digest/` 등)에서 온 항목은 **항목 제목**으로 판정 — scope hub의 정의·alias에 맞으면 통과, 애매하면 제외 |
| 대기열 PA (분석 미완) | scope hub 소속 논문만 |
| 대기열 S2 (hub 평문 이름) | scope hub(자식 포함) 본문만 읽는다 |
| 우선 큐 P0 | **필터 없음** — 사용자가 넣은 것은 scope 밖이어도 처리 |
| ingest 직전 게이트 (Step 3.5) | `get_paper_by_id`의 제목·초록이 어느 scope hub에도 맞지 않으면 `## 건너뜀`에 `scope 밖` 기록 후 다음 후보. 잘못 들어온 논문 한 편이 ingest+분석 한 반복을 통째로 먹으므로 여기서 거른다 |
| 리필 | anchor는 scope hub 소속 논문 중에서, 후보는 제목이 scope에 맞는 것만 |
| 신규 hub | `parent`가 scope 집합 안이어야 생성. 아니면 closest 기존 hub + `hub_candidate=` 로그 |

실행 중 scope를 바꾸려면 제어 노트에서 고친다 — 다음 반복부터 적용. 매 반복의 `start` 로그에 `scope=`가 찍히므로 어느 논문이 어느 scope에서 들어왔는지 나중에 알 수 있다. `## 건너뜀`의 `scope 밖` 항목은 scope를 넓힌 뒤 그 줄을 지우면 되살아난다.

## 중요도 게이트 — 무엇을 중요하다고 보는가
대기열은 "vault의 어떤 노트가 이 논문을 가리키는가"로 만들어지고 등급은 순서만 정한다. 그것만으로는 다이제스트가 한 번 소개한 논문(P4)과 hub 서사가 딛고 선 논문(P2)이 같은 문으로 들어온다. 그래서 ingest 직전에 **중요도 게이트**를 한 번 더 둔다.

- **지표**: citation velocity = 인용수 / max(1, 현재연도 − 출판연도). 프로젝트가 refs/cites 정렬과 노트 frontmatter에 이미 쓰는 정의 그대로 — 새 지표를 만들지 않는다.
- **임계**: 제어 노트 `min_velocity`(기본 10 — citation tool들의 기본값과 같다). 리필의 `min_velocity`도 이 값을 쓴다. 손잡이 하나.
- **통과**: velocity ≥ `min_velocity` **또는** vault 안에서 그 논문을 가리키는 노트가 2곳 이상(인용수와 무관하게 vault가 필요로 한다). frontier는 via anchor가 2편 이상이면 후자에 해당.
- **면제**: P0(사용자 지정) · P1·P2(hub 서사·다른 항목을 막는 것 — vault의 자기 선언) · PA와 `resumed`(이미 vault에 있는 논문).
- **대상**: P3 단일 참조 · P4 · frontier.
- **미달**: 버리지 않고 `## 보류`에 velocity·날짜·재평가일(+30일)과 함께 둔다. 재평가일 전에는 대기열에서 제외되고, 지나면 다시 후보가 되어 같은 판정을 받는다 — 신생 논문은 인용이 붙으면 스스로 올라오고, 아무도 안 인용하면 계속 보류된다. 통과하면 보류 줄을 지운다. 메타 조회 실패(SS 미매핑)는 판정 불가라 +7일 보류.
- **비용**: 판정 입력은 Step 3.5와 `paper-ingest` Step 1이 이미 부르는 `get_paper_by_id` 응답이다. 추가 호출 없음.

실측(2026-09-05): 대기열 P4 10건의 velocity는 0~31, 임계 10 통과는 2건(Qwen-VLA 31, minWM 11). hub가 이름을 부르는 P2 예시는 CoALA 167, FinCon 90 — 층이 갈린다.

## 자동 승인 규칙 — 무엇을 스스로 결정하고 무엇을 남기는가
원칙: **저장 축은 자동, 판단 축은 사람.** 하위 스킬의 승인 게이트(`paper-ingest` Step 6 신규 hub, `citation-analysis` Step 8)는 본 표로 대체되며 **사용자 turn을 기다리지 않는다.** 미리보기는 출력하되 정지하지 않는다.

| 축 | autopilot 판정 | 남기는 것 |
|---|---|---|
| 논문 노트 저장 (`paper-ingest` Step 8) | 자동 — **텍스트 요약만** | 로그 |
| **figure/table 추출** (`paper-ingest` 5a~5c) | **안 함** — 페이지 수와 무관하게 skip. Vision bbox 추정이 반복 시간을 지배하고 호출 timeout에 걸리며(첫 야간 실측), 5b 선별은 사람이 없으면 판단이 얕다. frontmatter `figures: []`, `figures_skipped: true` | 사람 — 아침에 원하는 논문만 `paper-ingest` override 경로로 on-demand |
| `references`/`cited_by` frontmatter + hub wikilink (`citation-analysis` Step 9-10) | 자동 | 로그 |
| 인용 그래프 (`citation-analysis` Step 11) | 자동 | — |
| **신규 hub** | **조건부** — (a) 논문 *자신의* 주제가 기존 hub·alias·related 어디에도 못 붙고, (b) vault에서 그 주제로 묶일 논문이 본 논문 포함 **≥3편**(`wiki_search`로 확인)이며, (c) scope가 `all`이 아니면 `parent`가 scope 집합 안일 때만. 하나라도 아니면 가장 가까운 기존 hub로 매핑하고 `hub_candidate=<slug>`로 로그. refs/cites로는 hub를 만들지 않는다(인용 흐름은 소속 근거 아님) | 로그 → 아침 검토 |
| 깨진 링크 정정 (Step 5) | 자동 — `[[old]]` 토큰 치환만 | 로그 |
| 통찰 노트 (`notes/`) | **안 씀** — 분석 중 판단이 나오면 `insight_candidate=` 한 줄(200자 이내)만 로그 | 사람 (`insight-capture`) |
| `wiki-lint` 반영 · "안 읽기로 함" 결정 · hub 재설계 · hub 요약 갱신 | **안 함** | 사람 |

## 상태 파일 (`_meta/` — 시스템 영역)

**`_meta/autopilot.md` — 제어.** 사용자가 편집하는 파일이다. 없으면 첫 실행 시 아래 템플릿으로 생성. **`scope`는 템플릿에서 비어 있다** — 실행마다 사용자가 준다. 읽기·쓰기는 `wiki_read_note`/`wiki_write_note`(작은 파일).

```markdown
---
stop: false                # true로 바꾸면 다음 반복에서 정지 처리
max_papers: 0              # 이번 실행 최대 처리 편수. 0 = 무제한. 정지해도 남는다
min_velocity: 10           # 중요도 게이트 임계 (인용수 / max(1, 나이)). 리필의 min_velocity도 이 값. 정지해도 남는다
scope: []                  # 실행마다 사용자가 준다. 비어 있으면 묻기만 하고 돌지 않는다. 전체는 all. 정지 시 비움
scope_input: ''            # scope의 원문(자연어 포함). 같은 인자가 다시 오면 재해석하지 않는다. 정지 시 비움
run_started: ''            # 비어 있으면 Step 0에서 채운다. 실행 보고서의 집계 시작점. 정지 시 비움
processed: 0               # 이번 실행 누계 (ok + partial). 정지 시 0
consecutive_failures: 0    # 정지 시 0
frontier_anchors: []       # 리필에 이미 쓴 anchor slug — 순환용
deleted_jobs: []           # 정지 시 지운 cron job id. D0가 옛 cron 생존 판정에 쓴다. 새 실행 시작 시 비움
---
# Autopilot 제어

## 우선 큐
사용자가 지정한 항목. 한 줄 = 한 항목. 대기열보다 먼저 처리되고, 처리되면 줄이 지워진다. scope 필터를 받지 않는다.
- 2506.01234 — 이유 (선택)
- Generative Agents: Interactive Simulacra — 제목만 있어도 됨

## 건너뜀
autopilot이 풀지 못한 항목. 줄을 지우면 다음 반복에서 다시 시도한다.
- <이름> — <사유> (<날짜>)

## 보류
중요도 게이트 미달. 재평가일이 지나면 다시 후보가 된다. 줄을 지우면 즉시 재평가, 우선 큐로 옮기면 게이트 없이 처리.
- <이름 또는 arxiv_id> — velocity <v> (<날짜>) · 재평가 <날짜+30일>

## frontier
대기열이 비었을 때 리필된 후보. velocity 순. 처리되면 줄이 지워진다.
- <arxiv_id> — <title> · vel <v> · via <anchor slug>
```

**`_meta/autopilot-log.md` — 이력.** append-only, frontmatter 없음. 한 반복 = `start` 헤더 한 줄 + 결과 헤더 한 줄 + `key=value` 3줄 + 빈 줄. **읽기는 헤더 `tail -3`, 쓰기는 `>>` append** — 로그는 매일 자라므로 전체를 읽는 것은 실행 보고서(디스패처) 한 번뿐이다.

```markdown
## [2026-09-04 23:05] autopilot | iter=7 | action=start | id=2604.01234 | source=S2 | rank=P2 | velocity_est=42.0 | scope=graph-rag,finance-agents
## [2026-09-04 23:12] autopilot | iter=7 | action=ingest | id=2604.01234 | slug=generative-agents | status=ok
source=S2 rank=P2 hub_of_origin=agent-memory velocity=42.0 gate=exempt(P2) pages=14 figures=skipped refs=20 cites=18 resumed=false interrupted=-
hubs=agent-memory new_hub=- hub_candidate=- links_fixed=2 held=1 insight_candidate=-
title="Generative Agents: Interactive Simulacra of Human Behavior" tldr="관찰·성찰·계획을 쌓는 메모리 스트림으로 LLM 에이전트 25명이 마을에서 믿을 만한 사회 행동을 만든다"

## [2026-09-04 23:41] autopilot | iter=8 | action=start | id=2603.05678 | source=S1 | rank=P3 | velocity_est=12.5 | scope=graph-rag,finance-agents
## [2026-09-05 00:02] autopilot | iter=8 | action=ingest | id=2603.05678 | slug=some-paper | status=ok
source=S1 rank=P3 hub_of_origin=finance-agents velocity=12.5 gate=pass(v=12.5) pages=- figures=- refs=17 cites=4 resumed=true interrupted=worker_rate_limit
hubs=finance-agents new_hub=- hub_candidate=- links_fixed=1 held=0 insight_candidate=-
title="Some Paper Title" tldr="한 줄 요약"

## [2026-09-05 06:02] autopilot | iter=21 | action=stop | reason=queue_exhausted
processed=13 run_started=2026-09-04T23:00 scope=graph-rag,finance-agents scope_input="graph rag랑 금융 트레이딩 에이전트"
```

`action` ∈ `start | ingest | skip | refill | stop`. `status` ∈ `ok | partial | fail`. `gate` ∈ `exempt(<rank>) | pass(v=<velocity>) | pass(refs=<n>)`. `figures` ∈ `skipped | extracted | -`, `pages` ∈ `<int> | -` — `-`는 이번 반복이 4a(PDF 읽기)를 건너뛴 경우(PA·`resumed`)뿐이다. 모든 키의 "없음·해당 없음"은 `-` 하나로 적고 빈 값이나 다른 표기를 섞지 않는다. `reason` ∈ `user | max_papers | consecutive_failures | queue_exhausted | scope_missing | control_parse_error`. `interrupted` ∈ `- | worker_rate_limit | worker_timeout | session | unknown` — 이어받아 닫은 반복에만 값이 있다. 결과 줄 셋째 줄의 `title`·`tldr`(노트 TL;DR 한 줄, 200자 이내)과 `insight_candidate`(200자 이내)는 **실행 보고서의 재료**다 — 보고서는 노트를 다시 읽지 않고 이 줄들만으로 만들어진다.

**`start`만 있고 같은 `iter`의 결과 줄이 없으면 그 반복은 중간에 끊긴 것**이다(사용량 한도·세션 종료·워커 중단). 끊긴 turn은 아무 표시도 남기지 못하므로 복구는 로그가 아니라 vault 상태로 판정한다 — 다음 워커가 그 id·iter를 이어받는다(Step 0·3).

## Steps (tool sequence)
아래 Step 0~7은 **워커**가 수행한다. 디스패처 모드에서는 D0가 `stop: true`·scope 없음·`max_papers` 도달·열린 start 카운트를 먼저 처리한 뒤 스폰하므로 Step 0의 같은 검사는 이중 방어다(인라인 모드에서는 유일한 방어).

| # | 동작 | 도구 |
|---|---|---|
| 0 | **제어 읽기 + scope 결정 + 열린 start 확인.** 디스패처가 프롬프트에 `상태:` 줄(iter·직전 헤더·processed/max·consecutive_failures)을 넘겼으면 그 값을 쓰고 로그 tail 재조회는 생략한다(제어 노트는 본문 절이 필요하므로 읽는다). 제어 노트가 없으면 템플릿으로 생성. 인자 `max_papers`가 오면 기록. **`stop: true`이면**(인라인 모드에서만 여기 도달): Cron 도구가 있으면 `CronList`로 `deleted_jobs`의 id가 살아 있는지 확인 → 살아 있으면 다시 지우고 한 줄 종료. 아니면 인자에 scope가 있으면 새 실행으로 풀고(`stop: false`, `deleted_jobs: []`) 계속, 없으면 "정지 상태 — 새로 /loop scope=…" 한 줄만 내고 종료(로그 없음). **scope**: ① 이번 호출 인자(`scope=` 또는 자연어) — 제어 노트 `scope_input`과 같으면 저장된 `scope`를 재사용, 다르면 해석·검증(`wiki_list_hubs()`) 후 `scope`·`scope_input` 갱신 + 확정 slug echo. 없는 이름·갈래 걸침이면 `action=stop reason=scope_missing scope_input="원문"` 로그(마지막 헤더가 이미 `scope_missing`이면 생략) 후 `ask=`에 원문·후보 hub를 담아 종료 — 제어 노트는 건드리지 않는다(대기이지 정지가 아니다) ② 인자가 없으면 제어 노트 `scope` — 둘 다 비면 같은 방식으로 `scope_missing` 보고 후 아무 작업 없이 종료. scope 집합 = 지정 hub + 자식 hub(`parent`로 전개). `run_started`가 비어 있으면 현재 시각. `max_papers > 0`이고 `processed >= max_papers` → `reason=max_papers` 정지 처리 ①②. **열린 start**: 마지막 헤더가 결과 줄 없는 `start`면 **대기열을 유도하지 않는다** — 그 `id`를 대상으로, 그 `iter`를 이어받아 Step 1~2를 건너뛰고 Step 3으로(3.5·3.6은 이미 통과한 것으로 보고 3.7 start 로그도 다시 쓰지 않는다; 결과 줄에 `interrupted=<원인>`). 아니면 `iter` = 마지막 헤더의 iter + 1 | `wiki_read_note("_meta/autopilot")` · Bash `grep "^## \[" <vault>/_meta/autopilot-log.md \| tail -3` · `wiki_list_hubs()` |
| 1 | **대기열 유도** — 세 소스를 모두 모은 뒤 **등급으로 합친다**(소스 순서가 아니라 등급 순서로 뽑는다). 전부 `## 건너뜀`·`## 보류`(재평가일 전)와 대조. (P0) 제어 노트 `## 우선 큐` · (S1) 깨진 wikilink: 출처가 `_meta/`인 것 제외, scope 필터(위 표), `reading-queue`의 등급 — 논문 노트 출처 P3, 다이제스트 출처 P4, 다른 항목을 막고 있으면 P1 · (S2) hub 본문의 평문 미수록 논문 이름: scope hub(자식 포함)만 읽는다(`all`이면 전부), `reading-queue` S2 판정 그대로(vault 기수록 여부는 **뜻으로 대조**, 개념어 제외) — 등급 P2 · (PA) **읽었지만 인용 지도가 없는 논문**: scope hub 소속 `papers/` 중 frontmatter에 `references`도 `cited_by`도 없는 것. `(코드)` `grep -L '^references:\|^cited_by:' <vault>/papers/*/*.md`를 📇 블록의 scope 소속과 교집합 — 노트 본문을 읽지 않는다. 코드 실행이 없는 환경이면 PA는 건너뛴다. **정렬: P0 → P1 → P2 → P3 → P4 → PA → (F) 제어 노트 `## frontier`(velocity 순).** PA(인용 지도 백필)는 새 논문을 더하지 않으므로 vault가 선언한 신규 유입(P1~P4) 뒤, 외부 탐색(F) 앞에 둔다 — 끊긴 반복의 미완 분석은 열린 start 이어받기와 우선 큐 `citation_pending`(P0)이 먼저 잡으므로 여기 남는 PA는 순수 백필이다. 같은 등급 안에서는 참조 노트 수가 많은 순 → 그래도 같으면(S2는 전부 1) **scope 인자 순서 → hub 본문 등장 순서** — 워커가 바뀌어도 큐 순서가 같다 | `wiki_backlinks()`, `wiki_read_note(hub)` |
| 1.5 | 전부 비었으면 **리필**(아래 절) 후 (F)로 진행. 리필도 0건이면 `reason=queue_exhausted` 정지 처리 ①② | (리필 절) |
| 2 | **후보 → arXiv ID.** 이미 ID면 통과. 이름이면 ① 참조 노트의 그 줄에서 `(arXiv:ID)` 병기를 먼저 찾고 ② 없으면 `search_papers(제목, max_results=5)` 상위에서 제목이 **뜻으로 일치**하는 것만 채택. 둘 다 실패 → `## 건너뜀`에 사유 기록, 다음 후보로. 한 반복에서 후보 3개가 연속 건너뛰어지면 `action=skip`으로 반복 종료(루프는 계속) | `search_papers` |
| 3 | **중복 검사 + 재개 판정.** 노트가 **없으면** 3.5로(열린 start를 이어받는 중이면 바로 4a). **있으면** 세 갈래: ⓐ `references`도 `cited_by`도 없고 `topics`가 scope 집합과 겹치면(`all`이면 무조건) → 끊겼거나 미완인 인용 분석. 이 논문을 대상으로 3.5·4a 생략, 4b부터(`resumed=true`) ⓑ refs/cited_by가 있고 **열린 start의 id**면 → 노트·그래프까지 쓰고 끊긴 것. Step 5·6만 수행해 그 iter를 닫는다(`interrupted=<원인>`) ⓒ 그 외 → Step 5 링크 정정만 하고 다음 후보로 | `wiki_read_note(arxiv_id)` |
| 3.5 | **scope 게이트** — `all`이 아닐 때만. `get_paper_by_id(arxiv_id)`(`paper-ingest` Step 1과 같은 호출)의 제목·초록이 어느 scope hub의 정의·alias에도 맞지 않으면 `## 건너뜀`에 `scope 밖 (<scope>)` 기록, 다음 후보 | `get_paper_by_id` |
| 3.6 | **중요도 게이트** — 대상 source(S1의 P3 단일 참조·P4·F)만. Step 3.5의 `get_paper_by_id` 응답에서 velocity = 인용수 / max(1, 현재연도 − 출판연도). velocity ≥ `min_velocity` 또는 참조 노트 ≥ 2면 통과. 미달 → `## 보류`에 `- <이름> — velocity <v> (<오늘>) · 재평가 <오늘+30일>` 기록, 다음 후보. 조회 실패 → 재평가 +7일. P0·P1·P2·PA·`resumed`는 면제. 통과한 항목이 `## 보류`에 있었다면 그 줄 삭제. 판정을 `gate=`로 남긴다 — 면제 `exempt(<rank>)`, velocity 통과 `pass(v=<velocity>)`, 참조 수 통과 `pass(refs=<n>)` | (Step 3.5 응답) |
| 3.7 | **start 로그** — 대상이 확정된 직후, 무거운 작업 전에 `action=start` 헤더 한 줄 append(`velocity_est=` — 대기열·vault 시점의 추정값. SS 검증값은 결과 줄 `velocity=`). 열린 start를 이어받는 중이면 생략 | Bash `>>` append |
| 4a | **ingest** — `paper-ingest` Step 1~8, 단 Step 4는 `read_paper(arxiv_id, max_pages=15)`, **5a~5c(figure/table)는 페이지 수와 무관하게 skip** — frontmatter `figures: []`, `figures_skipped: true`, `## Figures`엔 생략 한 줄. Step 6의 신규 hub 판정은 "자동 승인 규칙" 표로. PA·`resumed`·우선 큐의 `citation_pending` 항목은 4a를 건너뛰고 4b만 | (`paper-ingest`) |
| 4b | **인용 분석** — `citation-analysis` Step 1~11, `direction=both`, `top_k=20`. anchor가 최근 1~2년 논문이면 Step 3을 `exclude_recent_year=False, min_velocity=0`으로(기본 필터가 인용을 전부 잘라낸다). Step 8 게이트는 자동 승인. refs/cites 쪽 신규 hub 후보는 만들지 않고 closest 기존 hub로 | (`citation-analysis`) |
| 4c | **신규 hub 생성 시** (표의 조건 충족) — 기존 hub와 같은 frontmatter(`tier: hub`, `title`, `slug`, `aliases`, `parent`, `related`, `summary`, `seed_paper`, `created_at`). `parent`는 가장 가까운 기존 hub로 **필수**(`all`이 아니면 scope 집합 안). 본문은 소속 논문을 `[[slug\|표기]]`로 링크(평문 금지). 부모 hub 본문 `## 하위 갈래` 절에 `- [[slug]] — 한 줄` 추가(절이 없으면 끝에 신설) | `wiki_write_note("topics/<slug>")`, `wiki_read_note`/`wiki_write_note(parent)` |
| 5 | **링크 정정** — 이 후보를 가리키던 깨진 링크 `[[old]]` / `[[old\|표기]]`를 `[[<new-slug>\|<표기 또는 old>]]`로 치환. 참조 노트마다 read → 토큰 치환 → write(frontmatter는 읽은 그대로 되돌려 보존). `_meta/` 노트는 건드리지 않는다. **source와 무관하게** 이번 반복이 처리한 논문의 이름이 scope hub(자식 포함) 본문에 평문으로 남아 있으면 `[[slug\|표기]]`로 치환(L8과 같은 규칙, 축약 표기도 뜻으로 대조) — Step 1의 S2 수집 때 읽은 hub 본문이라 추가 읽기는 없다. 방금 처리한 논문에 한정하며 다른 논문의 평문 이름은 `wiki-lint` 몫 | `wiki_read_note`, `wiki_write_note` |
| 6 | **상태 갱신 + 결과 로그** — 우선 큐·frontier에서 해당 줄 제거, `processed += 1`(ok/partial), `consecutive_failures`는 ok면 0·fail이면 +1. 결과 헤더 + `key=value` 줄 append — 이 줄이 3.7의 `start`를 닫는다(이어받은 반복이면 `interrupted=<원인>`). 첫 줄에 `gate=`(3.6 판정)와 SS 검증값 `velocity=`. 셋째 줄에 `title="…" tldr="…"`(노트 `## TL;DR`을 한 줄 200자 이내로). `insight_candidate`도 200자 이내 | `wiki_write_note("_meta/autopilot")`, Bash `>>` append |
| 7 | **종료 전 검사.** `consecutive_failures >= 3` → 정지 처리 ①②(`reason=consecutive_failures`) + 진단 한 줄. `max_papers > 0`이고 `processed >= max_papers` → 정지 처리 ①②(`reason=max_papers`) — **다음 tick을 기다리지 않는다.** 정지 처리를 했으면 보고의 `stop_reason`에 사유(디스패처가 보고를 보고 ③④를 한다). 아니면 다음 반복은 루프가 연다 | — |

**쓰기 순서 (고정)**: ① 논문 노트(4a Step 8) → ② 인용 frontmatter(4b Step 9) → ③ 그래프(Step 11) → ④ 논문→hub 링크(Step 10)·신규 hub·부모 hub(4c) → ⑤ 참조 노트 링크 정정(Step 5). **새 slug를 가리키는 링크는 노트 파일이 생긴 뒤에만 쓴다** — 어느 지점에서 끊겨도 깨진 링크가 새로 생기지 않는다(첫 야간 실측에서 hub 링크·그래프가 노트보다 먼저 써진 채 끊겨 재개 전까지 깨진 링크가 남았다).

**정지 처리 — 워커가 하는 ①②**: ① `## [ts] autopilot | iter=N | action=stop | reason=…` 헤더 + `processed=… run_started=… scope=… scope_input="…"` 줄 append(최종 카운터는 여기 남는다) ② 제어 노트 `stop: true`, `scope: []`, `scope_input: ''`, `run_started: ''`, `processed: 0`, `consecutive_failures: 0`(`max_papers`·`min_velocity`·`frontier_anchors`·`deleted_jobs`·본문 절은 유지). `run_started`를 남기면 다음 실행 보고서가 두 실행을 합산한다. 그리고 보고의 `stop_reason`에 사유. ③ 루프 종료(cron 삭제·`deleted_jobs` 기록) ④ 실행 보고서는 **디스패처**가 한다 — 워커는 하지 않는다. `scope_missing`은 정지가 아니라 대기라 ②를 하지 않는다.

Step 5가 없으면 ingest한 논문을 가리키던 링크가 계속 깨진 채 남아 **같은 논문이 다음 반복에 다시 뽑힌다.** Step 3의 중복 검사가 2차 방어지만, 정정을 해야 대기열이 실제로 줄어든다.

## 리필 — 대기열이 비었을 때 frontier 채우기
대기열이 비었다는 것은 vault가 (scope 안에서) 자기 참조를 다 채웠다는 뜻이다. 다음 "중요한 논문"은 새 검색어가 아니라 **vault가 이미 중심으로 삼은 논문의 인용 이웃**에서 뽑는다 — 사용자 관심(vault 구조) × 외부 중요도(citation velocity).

1. **anchor 선정** — Step 1의 `wiki_backlinks()` 📇 블록에서 inbound 수가 가장 많은 `papers/` 노트 3편. `all`이 아니면 scope hub(자식 포함)의 inbound에 있는 논문 중에서만. `frontier_anchors`에 이미 있는 것은 건너뛰어 순환한다(전부 썼으면 목록을 비우고 처음부터).
2. anchor마다 frontmatter에서 `arxiv_id`를 읽고 `get_citations_by_citations(id, top_k=10, min_velocity=<제어 노트 min_velocity>)` + `get_references_by_citations(id, top_k=10, min_velocity=<같은 값>)`. anchor가 최근 1~2년 논문이면 citations 쪽은 `exclude_recent_year=False`.
3. **필터** — arXiv ID가 있는 것만 → vault 기수록 제외(`wiki_read_note(arxiv_id)`가 노트를 돌려주면 제외) → `## 건너뜀` 제외 → `all`이 아니면 **제목이 scope hub의 정의·alias에 맞는 것만**(애매하면 제외). survey는 도구가 이미 제외한다.
4. velocity 내림차순 **상위 10건**을 `## frontier`에 기록, anchor 3편을 `frontier_anchors`에 추가. `action=refill anchors=a,b,c added=N scope=…` 로그.
5. 0건이면 다음 anchor 3편으로 한 번 더. 그래도 0건이면 `reason=queue_exhausted`로 정지 처리 ①②.

frontier는 SS에서 유래해 vault로부터 유도할 수 없으므로 저장한다. 오래된 항목이 남아도 Step 3의 중복 검사가 무해화한다 — 이미 들어온 논문은 ingest되지 않고 줄만 지워진다.

## Output format (워커의 마지막 메시지 — 디스패처가 그대로 릴레이)

```
🤖 autopilot iter {N} — {ingest|skip|refill|stop} · scope: {hub, …|all}
   (새로 해석했을 때만) scope 확정: {slug, …} (+{자식 hub}) ← "{scope_input}"
   {title} (arXiv:{id}) · {rank}/{source}{ · resumed}{ · 이어받음 interrupted={원인}} · vel {v} · hubs: {hub, …} · new hub: {-|slug}
   TL;DR: {tldr 한 줄}{ · 통찰 후보: {insight_candidate}}
   링크 정정 {k}건 · 보류 {h}건 · 이번 실행 누계 {processed}편{ / max {max_papers}} · 대기열 잔여 ≈{q} (frontier {f})
   → 다음 tick 대기   |   ⏹ 정지: {reason} — cron 종료, scope·카운터 비움. 재개는 새 /loop
summary iter= action= id= slug= status= hubs= new_hub= hub_candidate= links_fixed= held= processed= queue= frontier= interrupted= stop_reason= ask=
```

정지(`stop_reason≠-`) 시에는 블록 안에 실행 요약을 한두 줄 덧붙인다: 처리 편수, 새 hub, `hub_candidate`·`insight_candidate`, 건너뜀 건수(그중 `scope 밖`), 보류 건수, 실패 진단. 실행 보고서 본문은 디스패처가 로그로 만든다. `scope_missing`이면 `ask=`에 원문과 후보 hub만 — 질문문은 디스패처가 만든다.

## Failure handling (워커)
- **한 반복 안의 실패는 그 논문만 건너뛴다.** 다른 도구로 우회하지 않는다(web search 등 금지). 사유를 `## 건너뜀`과 로그에 남기고 다음 후보로.
- **끊긴 반복 이어받기** — 마지막 헤더가 열린 `start`면 대기열 대신 그 id·iter를 이어받아 노트 유무에 따라 처음부터 / 4b부터 / Step 5·6만으로 닫고 결과 줄에 `interrupted=<원인>`을 남긴다(Step 0·3). `consecutive_failures`는 디스패처 D0가 올리고, 성공하면 Step 6에서 0으로 돌아간다. 노트가 반쯤 써지는 일은 없다 — vault 쓰기는 tool 호출 한 번 = 파일 하나이고, 쓰기 순서 규칙 덕에 깨진 링크도 생기지 않는다.
- **반복 중 컨텍스트 압축** — 아직 쓰지 않은 중간 결과(논문 본문·refs 분류)가 요약됐으면 **추측으로 채우지 말고 도구를 다시 부른다** — `read_paper`는 디스크, SS는 1주 캐시라 재호출이 싸다.
- Step 2 `search_papers` 무결과·제목 불일치 → 건너뜀 (`arXiv 미해석`). 제목이 비슷해도 저자·연도가 다르면 채택하지 않는다 — 잘못 넣은 논문은 아침에 지우기가 더 비싸다.
- Step 3.5 scope 밖 → 건너뜀 (`scope 밖 (<scope>)`). 정상 동작이지 실패가 아니다 — `consecutive_failures`에 세지 않는다.
- Step 3.6 중요도 미달 → `## 보류`(재평가 +30일). 실패가 아니다 — `consecutive_failures`에 세지 않는다. 메타 조회 실패로 판정 불가 → 보류(재평가 +7일).
- Step 4a `get_paper_by_id` 실패·PDF 다운로드 실패 → `paper-ingest` Failure handling 그대로. 그 논문 `status=fail`. `read_paper(max_pages=15)` 출력이 그래도 파일로 떨어지면 Read 한 번으로 읽는다.
- Step 4b SS 429 → `citation-analysis`의 백오프·title-only fallback 그대로. 그래도 실패면 **ingest된 노트는 남기고** `status=partial`, 제어 노트 `## 우선 큐`에 `- <id> — citation_pending` 추가 → 다음 반복이 4b만 재시도. (표시가 없어도 PA·재개 규칙이 같은 논문을 다시 잡는다 — 표시는 우선순위를 앞당길 뿐이다.)
- 같은 종류의 `fail`이 3회 연속 → `reason=consecutive_failures` 정지 처리 ①② + 진단 한 줄(예: `SS 429 지속`, `arXiv PDF timeout`). 도구 한계는 아침에 사용자가 판단한다 — 루프가 밤새 헛돌지 않게 한다.
- 제어 노트 frontmatter 파싱 실패(사용자 편집 오류) → 덮어쓰지 않고 `reason=control_parse_error`로 정지 처리 ①②. scope에 없는 hub 이름은 파싱 오류가 아니라 **`scope_missing` 재요청**이다.
- Step 5 참조 노트에 토큰 치환 이상의 수정이 필요해 보이면 하지 않고 `link_fix_skipped=<slug>` 로그 — `wiki-lint` 몫.
- `wiki_write_note` 실패(권한·경로) → 즉시 정지 처리 ①②. 부분 반영 상태를 로그에 명시.
