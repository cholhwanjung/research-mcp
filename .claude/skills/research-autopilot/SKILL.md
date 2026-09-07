---
name: research-autopilot
description: 무인 축적 루프의 한 반복(논문 1편)을 디스패처로 돈다 — 게이트 → 서브에이전트 워커(대기열 유도→ingest 텍스트 요약→citation-analysis→hub 판정→깨진 링크 정정, figure/table 미추출, 절차는 `WORKER.md`) → 보고 릴레이. `scope`는 실행마다 필수(없으면 hub 목록과 함께 묻고 돌지 않음, 전체는 `all` 명시). `/loop 10m /research-autopilot scope=…`으로 사용자가 멈출 때까지 반복, 정지 시 실행 보고서를 채팅 + `research-autopilot/<날짜>.md`에.
trigger:
  - "autopilot"
  - "밤새 논문 쌓아줘"
  - "무인 ingest 루프"
  - "research-autopilot"
inputs:
  - 'scope (string, **필수**) — 이번 실행에서 다룰 hub. slug(`scope=graph-rag,finance-agents`)나 자연어 모두 된다(뜻으로 hub에 대응, 자식 hub 자동 포함). 전체는 "all"(또는 "전체")을 명시. 기본값 없음 — 인자에도 제어 노트에도 없으면 묻기만 하고 돌지 않는다.'
  - 'max_papers (int, 선택) — 이번 실행 최대 처리 편수. 기본 0 = 무제한. 제어 노트에 저장되며 정지해도 남는다.'
---

## When to invoke
사용자가 자리를 비운 사이(밤새) vault를 계속 채우고 싶을 때. 본 스킬은 **한 반복 = 논문 1편**만 처리하고 끝난다. 반복은 `/loop`이 연다 — 스킬 안에서 while 루프를 돌리지 않는다.

부르지 말 것: 특정 논문 1편을 지금 넣는 것은 `paper-ingest`, 대기열을 보기만 하는 것은 `reading-queue`, 정합성 점검·hub 요약 갱신은 `wiki-lint`(autopilot은 lint를 반영하지 않는다).

## 시작·정지 (운용)

```
시작   /loop 10m /research-autopilot scope=graph-rag,finance-agents max_papers=10   권장 — 고정 간격 + scope(+예산)를 프롬프트에 고정
       /loop 10m /research-autopilot graph rag랑 금융 트레이딩 에이전트              자연어도 된다 — 첫 tick이 hub로 해석해 확정 slug를 보여주고 고정
       /loop 10m /research-autopilot                                              scope 없음 → 첫 tick이 hub 목록을 보이며 묻는다. 답할 때까지 돌지 않는다
       /loop /research-autopilot scope=…                                          지켜보며 돌릴 때만 — 동적 self-pacing

정지   채팅으로 "autopilot 멈춰"          → 정지 처리 + 루프 종료(cron 삭제)
       _meta/autopilot.md 의 stop: true  → 다음 tick에서 정지 처리 + 루프 종료 (Obsidian에서 편집. 다른 세션에서 멈출 때도 이 길)
       자동 정지(max_papers·큐 소진·연속 실패 3) → 마지막 반복 직후 정지 처리 + 루프 종료. 다음 tick을 기다리지 않는다
       세션 종료                          → 루프는 세션에만 산다

재개   새로 /loop을 건다. scope는 다시 준다 — 정지된 실행의 scope·카운터는 이월되지 않는다 (max_papers·min_velocity는 남는다)

보고   정지 시 자동 — 실행 보고서(들어온 논문 요약·통찰 후보·종합·아침 할 일)를 채팅에 내고 research-autopilot/<날짜>.md 에 저장
       채팅으로 "autopilot 보고"          → 정지하지 않고 현재 실행 기준 보고서만 (파일 저장 없음)

전제   세션이 살아 있어야 한다 — Mac 잠자기 방지(예: caffeinate -dimsu), 데스크톱 앱 유지. 한 vault에 루프는 한 세션만
```

**간격이 10분인 이유.** 한도에 걸린 turn은 거부되고 스킬은 감지할 수 없다. 고정 간격 cron은 창이 풀리면 스스로 재개되지만(동적 모드는 끊긴다) **거부된 tick도 공짜가 아니다** — 그 시점엔 0 토큰이어도 tick 프롬프트(이 파일 전체)가 대화에 남아 회복 첫 turn에 한꺼번에 들어온다(실측: 2시간 18분 대기의 tick 29회 → 71만 토큰). 워커 1회는 5~10분(실측 2026-09-06, n=10, 평균 7.8분)이고 워커 실행 중 tick은 쌓이지 않고 하나만 대기하므로, 10분이면 반복 사이 공백이 몇 분이고 한도 대기 2시간의 tick도 14회 × 이 파일 크기에 그친다. 그래서 이 파일은 디스패처 분량만 두고 워커 절차는 `WORKER.md`에 — **이 파일을 키우지 않는다.**

**cron은 정지 처리에서 지운다.** 살려두면 tick마다 이 파일이 프롬프트로 다시 들어온다(D0는 스폰만 막는다). cron이 살아 있는 경우는 둘뿐이다 — 정지 기록 없이 끊긴 한도 거부와 `scope_missing` 대기. 지운 뒤 `CronList`로 확인하고 지운 id는 제어 노트 `deleted_jobs`에 남긴다 — 삭제가 실패해도 다음 tick의 D0가 id로 알아보고 다시 지운다.

동적 모드일 때만: 정지 조건이 아니면 `delaySeconds=60`으로 같은 프롬프트를 재예약하고, 정지 조건(scope 미입력 포함)이면 `stop`으로 루프를 끝낸다.

## 실행 구조 — 디스패처/워커 (컨텍스트 격리)
한 반복은 논문 본문·refs 메타·hub 본문으로 컨텍스트를 13만~19만 토큰까지 불린다(실측 n=10). 본 세션은 **디스패처만** 하고 Step 0~7은 **워커**(서브에이전트)가 새 컨텍스트에서 수행한다. 본 세션에는 보고 15줄만 남는다.

```
D0 가벼운 게이트 — 스폰 없이 끝낼 수 있는 tick을 먼저 거른다 (읽기 + 작은 쓰기만)
   · wiki_read_note("_meta/autopilot") + Bash: grep "^## \[" <vault>/_meta/autopilot-log.md | tail -3   ← 로그 전체를 읽지 않는다. <vault> = OBSIDIAN_VAULT_PATH(기본 ~/Documents/research-wiki)
   · 마지막 헤더가 결과 줄 없는 start → 끊긴 반복. 제어 노트 consecutive_failures += 1 (워커가 이어받아 닫으면 0). 3이면 정지 처리 · 종료
   · stop: true → 먼저 CronList. 남은 job 중 id가 deleted_jobs에 있으면 옛 cron — 다시 CronDelete하고 "정지 상태 — 옛 cron 정리" 한 줄 · 종료(스폰·로그 없음)
                  그런 id가 없고 인자에 scope가 있으면 진짜 새 /loop — stop: false, deleted_jobs 비우고 계속. scope도 없으면 "정지 상태 — 새로 /loop scope=…" 한 줄 · 종료
                  (cron은 세션 안에만 살므로 이 대조는 같은 세션에서 ③이 실패했을 때만 뜻이 있다. 새 세션이면 deleted_jobs 잔재는 그냥 비운다)
   · 인자에도 노트에도 scope 없음 → 아래 "scope 요청 출력" · 첫 회만 scope_missing 로그(append) · 종료 (제어 노트 그대로, cron 유지 — 답을 기다린다)
   · max_papers 도달 → 정지 처리 · 종료
   · "설정만 하는 발화" / "autopilot 멈춰" → 제어 노트·로그를 직접 갱신 · 종료 (워커 불필요)
   · "autopilot 보고" → 실행 보고서만 만들어 출력 · 종료 (정지 아님, 저장 없음)
D1 워커 스폰 — Agent(subagent_type="general-purpose", run_in_background=false, prompt=아래 워커 프롬프트)
   · 반드시 동기(blocking). 워커가 끝나기 전에 tick이 끝나면 다음 tick이 두 번째 워커를 띄워 두 반복이 같은 vault를 건드린다
D2 워커의 마지막 메시지(보고)를 사용자에게 그대로 릴레이
   · 보고에 ask=가 있으면(scope 미해석) 아래 "scope 요청 출력"으로 감싼다
   · stop_reason이 '-'가 아니면 루프 종료(정지 처리 ③) → ④ 실행 보고서
   · 아니면 동적 모드일 때만 재예약(60초)
```

**워커 프롬프트** (디스패처가 채워 보낸다):
```
research-autopilot 스킬의 한 반복을 워커 모드로 수행하라.
- 지침: 프로젝트의 `.claude/skills/research-autopilot/WORKER.md`(플러그인으로 설치됐으면 그 스킬 폴더의 WORKER.md)를 Read로 읽고 그대로 따른다. (Skill 도구로 research-autopilot을 부르지 않는다 — 그것은 디스패처 본문이다)
- 인자: scope={인자 원문 | "(없음 — 제어 노트 값 사용)"} max_papers={값 | "(없음)"}
- 상태: iter={N} · 직전 헤더="{D0가 읽은 마지막 헤더 1줄}" · processed={p}/{max_papers} · consecutive_failures={c}   ← D0가 읽은 값 그대로. 워커는 로그를 다시 읽지 않는다
- 환경: vault={vault 루트 절대경로} · MCP 도구 접두사={예: mcp__research__} · 오늘={YYYY-MM-DD} · SS 캐시 1주
- 워커 계약: Step 0~7 전부. figure/table 추출 금지. 사용자 질문 금지(필요하면 scope_missing 로그 + ask=). 루프 제어 금지(정지 처리 ①②를 했으면 stop_reason). 로그는 헤더 tail -3만 읽고 >>로 append. read_paper는 max_pages=15.
- 마지막 메시지는 WORKER.md "Output format" 블록 + 다음 한 줄. 15줄 이내:
  summary iter= action= id= slug= status= hubs= new_hub= hub_candidate= links_fixed= held= processed= queue= frontier= interrupted= stop_reason= ask=
```

**인라인 모드 (fallback)**: Agent 도구가 없는 환경(플러그인을 Claude Desktop에서 쓸 때, web 에이전트)에서는 같은 세션이 `WORKER.md`를 읽고 Step 0~7을 직접 수행한다. 동작은 같고 컨텍스트 격리만 없다.

## scope 입력 — 디스패처가 아는 만큼
scope는 **hub slug의 집합**(`wiki_list_hubs()`에 있는 것만, 자식 hub 자동 포함)이며 **실행(run) 단위**다 — 모든 정지에서 비워지고 다음 `/loop`에서 다시 받는다. 정지 기록 없이 끊긴 실행(한도·세션 사망)은 같은 실행이라 남아 있다.
- slug와 자연어는 같은 경로다 — `wiki_list_hubs()`의 slug·alias·title·summary에 **뜻으로** 대응시킨다. 한 부모 hub 아래로 묶이면 부모로(자식 포함), 서로 다른 갈래에 걸치거나 어느 hub에도 닿지 않으면 후보와 함께 묻는다.
- **전체는 `all`("전체")로만.** 빈 값은 "미입력"이지 "전체"가 아니다.
- **첫 해석을 고정한다** — 제어 노트에 원문 `scope_input`과 결과 `scope`를 함께 저장하고, 같은 인자가 다시 오면 재해석하지 않는다(`/loop`은 tick마다 같은 문자열을 넘긴다). 새로 해석했을 때만 `scope 확정: graph-rag, finance-agents (+temporal-leakage) ← "…"`로 되돌려 보여준다.
- **설정만 하는 발화**("오늘은 graph rag랑 금융 에이전트로" — 시작 지시 없음)는 D0가 제어 노트에 기록하고(`stop: false`) 확인 문장만 낸다. 반복은 시작하지 않는다. 그 뒤 인자 없는 `/loop 10m /research-autopilot`이 제어 노트의 scope로 돈다.
- 필터가 걸리는 지점(S1·S2·PA·초록 게이트·리필·신규 hub)은 `WORKER.md` "주제 scope".

**scope 요청 출력** (scope가 없거나 해석 불가일 때 — 디스패처가 낸다):
```
🛑 autopilot — scope가 없어 시작하지 않았습니다
   이번 실행에서 다룰 hub를 골라 주세요 (쉼표로 여러 개, 자식 hub는 자동 포함, 자연어로 말해도 됩니다):
   - finance-agents — {summary} (자식: temporal-leakage)
   - graph-rag — {summary}
   … (wiki_list_hubs 전체, 부모 hub는 자식과 함께 표시){ · 해석 불가였으면: 입력 "{원문}" — 후보: {ask의 후보}}
   모든 hub를 대상으로 하려면 "전체"라고 명시해 주세요. 보통은 관련 hub 몇 개가 맞습니다.
   → 답하시면 그 값으로 이어서 진행합니다. 프롬프트에 고정하려면: /loop 10m /research-autopilot scope=graph-rag,finance-agents
```

## 정지 처리 (모든 사유 공통)
디스패처(D0)·워커(Step 1.5·7) 어느 쪽이 시작하든 같은 절차. ①②는 시작한 쪽이, ③④는 **디스패처**가 한다.
1. 로그 append: `## [ts] autopilot | iter=N | action=stop | reason=…` + `processed=… run_started=… scope=… scope_input="…"` — 최종 카운터는 여기 남는다.
2. 제어 노트 `stop: true`, `scope: []`, `scope_input: ''`, `run_started: ''`, `processed: 0`, `consecutive_failures: 0`(`max_papers`·`min_velocity`·`frontier_anchors`·본문 절은 유지). `run_started`를 남기면 다음 실행 보고서가 두 실행을 합산한다. **카운터는 정지 기록을 경계로 리셋된다** — 시간 기준 리셋은 없다.
3. 루프 종료: 고정 간격이면 `CronList`에서 `/research-autopilot` 프롬프트의 job을 모두 `CronDelete` → 다시 `CronList`로 확인, 남았으면 한 번 더 → 지운 id를 제어 노트 `deleted_jobs`에 기록. 동적이면 `stop`.
4. 실행 보고서(아래 절).

`reason` ∈ `user | max_papers | consecutive_failures | queue_exhausted | control_parse_error`. `scope_missing`은 정지가 아니라 **대기**다 — 로그 한 줄(첫 회)만 남기고 ②③④를 하지 않는다. 채팅 "autopilot 멈춰"도 ①~④. **이미 정지 기록이 있는 상태의 "멈춰"는 로그 없이 ③만.**

## 상태 파일 (`_meta/` — 시스템 영역)
- **`_meta/autopilot.md` 제어** — 사용자가 편집하는 파일. frontmatter `stop`·`max_papers`·`min_velocity`·`scope`·`scope_input`·`run_started`·`processed`·`consecutive_failures`·`frontier_anchors`·`deleted_jobs`, 본문 `## 우선 큐`·`## 건너뜀`·`## 보류`·`## frontier`. 템플릿과 키 설명은 `WORKER.md` "상태 파일"(없으면 워커가 생성).
- **`_meta/autopilot-log.md` 이력** — append-only. 한 반복 = `start` 헤더 1줄 + 결과 헤더 1줄 + `key=value` 3줄. 헤더 문법 `## [YYYY-MM-DD HH:MM] autopilot | iter=N | action=start|ingest|skip|refill|stop | …`. **D0는 헤더 3줄(`grep "^## \[" … | tail -3`)만 읽고, 전체는 실행 보고서 때 1회만 읽는다.** 마지막 헤더가 `action=start`면 그 반복은 끊긴 것이다.

## 실행 보고서 — 정지 시 (또는 "autopilot 보고" 요청 시)
정지 처리 ④에서 **디스패처**가 만든다. 재료는 로그뿐이다 — `_meta/autopilot-log.md`를 이때 한 번 전체로 읽어 `run_started` 이후 항목의 `title`·`tldr`·`hubs`·`source`·`rank`·`gate`·`velocity`·`insight_candidate`·`hub_candidate`·`new_hub`·`held`·`interrupted`를 모은다. **노트를 다시 읽거나 새로 조회하지 않는다** — 보고서 비용을 실행 길이와 무관하게 로그 한 번 읽기로 고정하기 위해서다. 채팅에 출력하고 같은 내용을 `research-autopilot/<정지 날짜>.md`에 저장한다(같은 날 두 번째면 `-2`). 파일 안에서 논문은 `papers/<slug>` 평문 경로로 적는다 — `[[wikilink]]`를 쓰면 보고서 한 장이 논문 여러 편에 inbound를 만들어 hub 소속과 구분되지 않는다. `research-autopilot/`는 `_meta/` 밖이므로 **vault 본문 격리 규칙이 적용된다**(내부 메타 식별자 금지). wiki-lint 고아 검사에서는 제외 폴더다.

```
📋 autopilot 실행 보고 — {run_started} → {정지 시각} · scope: {…} · 정지: {reason}
   처리 {N}편 (ok {a} · partial {b}) · source: S1 {…} · S2 {…} · PA {…} · F {…} · 건너뜀 {s}건(scope 밖 {x}) · 보류 {h}건 · 끊김 {i}회 · 새 hub: {…|-} · hub 후보: {…|-}
   {PA만 처리했으면: ⚠️ 신규 유입 없음 — scope 안 S1/S2가 고갈돼 백필(인용 지도)만 돌았다. scope를 넓히거나 우선 큐를 채울 때}

## 들어온 논문
1. {title} (arXiv:{id}) — papers/{slug} · {rank}/{source} · {gate} · hubs: {…} · vel {v}
   {tldr}
2. …

## 통찰 후보 — 저장되지 않았다. 고르면 insight-capture 초안 모드로
- {slug}: {insight_candidate}
- …

## 이번 배치가 말하는 것
{2~3문장. 위 TL;DR과 후보만으로 쓴 종합 — 어떤 흐름이 채워졌고 무엇이 비어 있는지. 새 조사·추측 금지. 근거가 없으면 "종합할 만한 공통점 없음" 한 줄}

## 아침 할 일
- figure/table on-demand 후보: {figure가 있을 법한 논문 slug, …} — paper-ingest override 경로
- hub 후보 검토: {hub_candidate 목록} · 새 hub 확인: {new_hub}
- 보류 {h}건 훑기 · scope 밖 {x}건 · wiki-lint(L4 stale 후보: 소속이 늘어난 hub {…})
```

"이번 배치가 말하는 것"은 판단이지만 vault에 쓰지 않는 채팅 산출물이다 — 통찰 노트는 여전히 사용자가 `insight-capture`로 고른 것만 저장된다. "autopilot 보고" 요청은 정지 없이 같은 형식으로 현재 실행(마지막 `stop` 이후) 기준으로 만들고, 파일은 저장하지 않는다.

아침 검토: 보고서 파일 → `grep "^## \[" _meta/autopilot-log.md`(`start` 수 ≠ 결과 수면 열린 반복). 헤더의 `velocity_est=`는 대기열 시점 추정값이고, 검증값 `velocity=`·판정 `gate=`·`interrupted=`·`new_hub=`·`hub_candidate=`·`insight_candidate=`는 결과 줄에 있다 — `grep -o 'gate=[a-z]*' … | sort | uniq -c`로 게이트 분포. 그림은 `paper-ingest` override로 on-demand, `## 보류`·`## 건너뜀`은 줄을 지우면 되살아남, hub 요약은 `wiki-lint`, 통찰은 `insight-capture`, 남은 대기열은 `reading-queue`.

## Failure handling (디스패처)
- **끊긴 반복**(워커가 보고 없이 끝남·한도 거부·세션 종료) — 로그엔 `start`만 남는다. 다음 tick의 D0가 `consecutive_failures += 1`(3이면 정지 처리 — 같은 항목에서 계속 죽는다는 뜻), 워커는 그 id·iter를 이어받아 닫는다(`WORKER.md` Step 0·3). 같은 tick에서 워커를 다시 띄우지 않는다. 고정 간격이면 한도 창이 풀린 뒤 자동 재개, 동적이면 사용자가 다시 `/loop`.
- **scope 미입력** — 실패가 아니라 대기. 고정 간격이면 tick마다 한 줄로 재요청(cron 유지), 동적이면 루프 정지. 사용자가 답하면 검증 후 진행.
- **cron 삭제 실패** — 옛 cron의 다음 tick을 D0가 `deleted_jobs`의 id로 알아보고 다시 지운다. 두 번 지워도 남으면 매 tick 한 줄만 내고 `/tasks`에서 수동 삭제를 안내한다.
- **컨텍스트 압축** — 반복 *사이*의 압축은 무해하다. 이 스킬은 이전 turn을 기억에 의존하지 않고 모든 상태를 vault·`_meta`에서 다시 읽는다. 워커 안의 압축은 `WORKER.md` Failure handling.
- **Agent 도구 없음** → 인라인 모드. 보고 형식·로그는 같다.
