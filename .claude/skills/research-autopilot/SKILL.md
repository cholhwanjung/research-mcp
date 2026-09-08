---
name: research-autopilot
description: 무인 축적 루프의 한 반복(논문 1편)을 디스패처로 돈다 — 게이트 → 서브에이전트 워커(`WORKER.md`) → 보고 릴레이. `/loop 10m /research-autopilot scope=…`로 반복. scope는 실행마다 필수, 자연어 중 hub에 없는 주제는 탐색 주제로 등록해 arXiv seed. 정지 시 실행 보고서.
trigger:
  - "autopilot"
  - "밤새 논문 쌓아줘"
  - "무인 ingest 루프"
inputs:
  - 'scope (필수) — 이번 실행의 hub. slug(`scope=graph-rag,finance-agents`) 또는 자연어. 자식 hub 자동 포함. hub에 없는 주제는 탐색 주제로 등록된다. 전체는 `all` 명시. 없으면 묻기만 하고 돌지 않는다'
  - 'max_papers (선택, 기본 0=무제한) — 제어 노트에 저장, 정지해도 남는다'
---

## When to invoke
자리를 비운 사이 vault를 채울 때. **한 반복 = 논문 1편**, 반복은 `/loop`이 연다 — 스킬 안에서 루프를 돌리지 않는다. 논문 1편 지금 넣기는 `paper-ingest`, 대기열 보기는 `reading-queue`, lint 반영은 `wiki-lint`(autopilot은 lint를 반영하지 않는다).

## 운용
사용법(시작·정지·재개·보고·탐색·전제)은 README "research-autopilot 운용" 절. 디스패처가 알아야 할 것:
- 플러그인 설치 프로젝트에선 `/research-mcp:research-autopilot` (하위 스킬도 `research-mcp:` 접두사).
- MCP 서버가 둘 보이면(`mcp__research__` · `mcp__plugin_research-mcp_research__`) 각각 `wiki_list_hubs()`를 불러 hub가 보이는 쪽 접두사를 워커 프롬프트에 박는다.
- **이 파일은 tick마다 프롬프트에 들어간다** — 디스패처 분량만 두고 워커 절차는 `WORKER.md`, 정지·보고서는 `STOP.md`에. 키우지 않는다.
- 동적 모드: 정지 조건이 아니면 `delaySeconds=60`으로 같은 프롬프트 재예약, 정지 조건(scope 미입력 포함)이면 `stop`.

## 디스패처 절차
본 세션은 디스패처만. Step 0~7은 워커(서브에이전트)가 새 컨텍스트에서 수행하고 본 세션엔 보고 15줄만 남는다.

```
D0 게이트 — 스폰 없이 끝낼 tick을 거른다
   · wiki_read_note("_meta/autopilot") + Bash: grep "^## \[" <vault>/_meta/autopilot-log.md | tail -3   (전체를 읽지 않는다. <vault>=OBSIDIAN_VAULT_PATH, 기본 ~/Documents/research-wiki)
   · 마지막 헤더가 결과 줄 없는 start → 끊긴 반복. consecutive_failures += 1 (워커가 이어받아 닫으면 0). 3이면 정지 처리(⓪이 그 start를 먼저 닫는다) · 종료
   · stop: true → CronList. 남은 job id가 deleted_jobs에 있으면 옛 cron — CronDelete 다시, "정지 상태 — 옛 cron 정리" 한 줄 · 종료
                  없고 인자에 scope가 있으면 새 /loop — stop: false, deleted_jobs 비우고 계속. scope도 없으면 "정지 상태 — 새로 /loop scope=…" 한 줄 · 종료
                  (cron은 세션 안에만 산다 — 새 세션이면 deleted_jobs 잔재는 그냥 비운다)
   · 인자에도 노트에도 scope 없음 → "scope 요청 출력" · 첫 회만 scope_missing 로그 · 종료 (노트 그대로, cron 유지 — 대기)
   · max_papers 도달 → 정지 처리 · 종료
   · 설정만 하는 발화("오늘은 graph rag로") → 제어 노트에 scope 기록(stop: false), 확인 한 줄 · 종료 (반복 시작 안 함)
   · "autopilot 멈춰" → STOP.md Read → 정지 처리 ⓪~④ · 종료 (이미 정지 상태면 로그 없이 ③만)
   · "autopilot 보고" → STOP.md Read → 실행 보고서만 출력 · 종료
D1 워커 스폰 — Agent(subagent_type="general-purpose", run_in_background=false, prompt=아래). 반드시 동기 — 워커가 끝나기 전에 tick이 끝나면 다음 tick이 둘째 워커를 띄워 같은 vault를 건드린다
D2 워커의 마지막 메시지를 그대로 릴레이
   · ask=가 있으면(scope 미입력) "scope 요청 출력"으로 감싼다
   · stop_reason≠- → STOP.md Read → 정지 처리 ③ → ④ 실행 보고서
   · 아니면 동적 모드일 때만 60초 재예약
```

**워커 프롬프트**:
```
research-autopilot 스킬의 한 반복을 워커 모드로 수행하라.
- 지침: 프로젝트의 `.claude/skills/research-autopilot/WORKER.md`(플러그인이면 그 스킬 폴더)를 Read로 읽고 따른다. Skill 도구로 research-autopilot을 부르지 않는다
- 인자: scope={인자 원문 | "(없음 — 제어 노트 값 사용)"} max_papers={값 | "(없음)"}
- 상태: iter={N} · 직전 헤더="{D0가 읽은 마지막 헤더}" · processed={p}/{max_papers} · consecutive_failures={c}   ← 워커는 로그를 다시 읽지 않는다
- 환경: vault={절대경로} · MCP 도구 접두사={예: mcp__research__} · 오늘={YYYY-MM-DD} · SS 캐시 1주
- 도구 로드: MCP 도구가 deferred면 첫 행동으로 ToolSearch 한 번에 전부 — `select:` 뒤에 접두사 붙인 전체 이름을 쉼표로: wiki_read_note, wiki_write_note, wiki_list_hubs, wiki_backlinks, wiki_search, wiki_link, search_papers, get_paper_by_id, read_paper, get_references_by_citations, get_citations_by_citations, get_citation_contexts, build_citation_graph
- 계약: Step 0~7 전부. figure/table 추출 금지. 사용자 질문 금지(필요하면 scope_missing 로그 + ask=). 루프 제어 금지(정지 처리 ①②를 했으면 stop_reason). 로그는 헤더 tail -3만 읽고 >>로 append. read_paper는 max_pages=15
- 마지막 메시지는 WORKER.md "Output format" 블록 + 다음 한 줄, 15줄 이내:
  summary iter= action= id= slug= status= hubs= topic= new_hub= hub_candidate= links_fixed= held= processed= queue= frontier= interrupted= stop_reason= ask=
```

**인라인 모드**: Agent 도구가 없으면(Claude Desktop 플러그인, web 에이전트) 같은 세션이 `WORKER.md`를 읽고 Step 0~7을 직접 수행. 컨텍스트 격리만 없다.

## scope (디스패처 몫)
scope는 **hub slug 집합**(`wiki_list_hubs()`에 있는 것만, 자식 자동 포함)이며 **실행 단위** — 모든 정지에서 비워지고 다음 `/loop`에서 다시 받는다. 정지 기록 없이 끊긴 실행은 같은 실행이라 남는다. 해석·필터·탐색 주제는 `WORKER.md` "주제 scope"·"seed". 디스패처가 아는 것: 전체는 `all`로만(빈 값은 미입력) · hub에 안 닿는 주제는 묻지 않고 **탐색 주제**로 등록되며 첫 tick 보고의 `scope 확정:` echo로 확인한다(잘못 잡혔으면 제어 노트 `## 탐색 주제`에서 수정) · 첫 해석을 고정(`scope_input`이 같으면 재해석 안 함) · 설정만 하는 발화는 D0가 기록.

**scope 요청 출력**:
```
🛑 autopilot — scope가 없어 시작하지 않았습니다
   이번 실행에서 다룰 hub를 골라 주세요 (쉼표로 여러 개, 자식 hub 자동 포함, 자연어도 됩니다 — hub에 없는 주제는 탐색 주제로 등록됩니다):
   - {hub} — {summary} (자식: …)      ← wiki_list_hubs 전체
   전체를 대상으로 하려면 "전체"라고 명시해 주세요. 프롬프트에 고정: /loop 10m /research-autopilot scope=…
```

## 정지 처리
⓪ 열린 start 닫기 → ① stop 로그 → ② 제어 노트 리셋(`scope`·`scope_input`·`run_started`·`processed`·`consecutive_failures` 비움, `max_papers`·`min_velocity`·`## 탐색 주제` 유지) → ③ cron 삭제(`CronList` 확인, 지운 id는 `deleted_jobs`) → ④ 실행 보고서. ①②는 시작한 쪽(D0 또는 워커), ⓪③④는 디스패처. **세부 절차·보고서 형식은 `STOP.md`를 Read** — D0가 정지 처리에 들어갈 때, D2가 `stop_reason≠-`를 받았을 때, "autopilot 보고" 때만. tick마다 읽지 않는다.

`reason` ∈ `user | max_papers | consecutive_failures | queue_exhausted | control_parse_error`. `scope_missing`은 정지가 아니라 **대기** — 로그 한 줄(첫 회)만, ②③④ 없음. cron을 살려두면 tick마다 이 파일이 다시 들어온다.

## 상태 파일 (`_meta/`)
- `_meta/autopilot.md` 제어 — 사용자가 편집. frontmatter `stop`·`max_papers`·`min_velocity`·`scope`·`scope_input`·`run_started`·`processed`·`consecutive_failures`·`frontier_anchors`·`deleted_jobs`·`explore`·`max_topics`, 본문 `## 우선 큐`·`## 건너뜀`·`## 보류`·`## frontier`·`## 탐색 주제`. 템플릿은 `WORKER.md`.
- `_meta/autopilot-log.md` 이력 — append-only. 한 반복 = `start` 헤더 + 결과 헤더 + `key=value` 3줄. 문법 `## [YYYY-MM-DD HH:MM] autopilot | iter=N | action=start|ingest|skip|refill|stop | …`. D0는 헤더 `tail -3`만, 전체는 보고서 때 1회.

## Failure handling (디스패처)
- 끊긴 반복(워커 보고 없이 종료·한도 거부·세션 종료) → 로그엔 `start`만. 다음 tick의 D0가 `consecutive_failures += 1`(3이면 정지), 워커가 그 id·iter를 이어받아 닫는다. 같은 tick에서 워커를 다시 띄우지 않는다. 고정 간격이면 한도 창이 풀린 뒤 자동 재개, 동적이면 새 `/loop`.
- scope 미입력 → 대기. 고정 간격이면 tick마다 한 줄 재요청(cron 유지), 동적이면 정지.
- cron 삭제 실패 → 옛 cron의 다음 tick을 D0가 `deleted_jobs`로 알아보고 다시 지운다. 두 번 지워도 남으면 tick마다 한 줄 + `/tasks`에서 수동 삭제 안내.
- 반복 *사이* 컨텍스트 압축은 무해 — 상태는 전부 vault·`_meta`에서 다시 읽는다. 워커 안의 압축은 `WORKER.md`.
- Agent 도구 없음 → 인라인 모드.
