# research-autopilot — 정지 처리 · 실행 보고서

디스패처(`SKILL.md`)가 읽는다 — D0가 정지 처리에 들어갈 때, D2가 `stop_reason≠-`를 받았을 때, "autopilot 보고" 요청 때. tick마다 읽지 않는다. 워커는 읽지 않는다(워커의 ①②는 `WORKER.md`).

## 정지 처리 (모든 사유 공통)
①②는 시작한 쪽(D0 또는 워커), ⓪③④는 디스패처.
- **⓪ 열린 start 닫기** — 마지막 헤더가 결과 줄 없는 `start`면 stop 줄보다 먼저 닫는다: 헤더의 `id`·`source`·`rank`를 읽고 `wiki_read_note(id)`로 노트 유무 확인 → 결과 헤더 `action=ingest | id | slug=<slug|-> | status=partial`(노트 있음) 또는 `fail`(없음) + `interrupted=user_stop|consecutive_failures|session` append. 우선 큐 줄은 지우지 않고 `processed`도 올리지 않는다 — 다음 실행이 P0·PA로 이어받는다. stop 헤더의 `iter`는 그 열린 iter.
- **①** 로그 `## [ts] autopilot | iter=N | action=stop | reason=…` + `processed=… run_started=… scope=… scope_input="…"`.
- **②** 제어 노트 `stop: true`, `scope: []`, `scope_input: ''`, `run_started: ''`, `processed: 0`, `consecutive_failures: 0` (`max_papers`·`min_velocity`·`frontier_anchors`·본문 절 유지).
- **③** 루프 종료 — `CronList`에서 프롬프트에 `research-autopilot`이 든 job(맨 이름·`research-mcp:` 접두사 모두)을 `CronDelete` → `CronList`로 확인, 남았으면 한 번 더 → 지운 id를 `deleted_jobs`에. 동적이면 `stop`. **cron을 살려두면 tick마다 이 파일이 다시 들어온다.**
- **④** 실행 보고서.

`reason` ∈ `user | max_papers | consecutive_failures | queue_exhausted | control_parse_error`. `scope_missing`은 정지가 아니라 **대기** — 로그 한 줄(첫 회)만, ②③④ 없음.

## 실행 보고서 (정지 ④ · "autopilot 보고")
재료는 **로그뿐** — `_meta/autopilot-log.md`를 한 번 전체로 읽어 `run_started` 이후의 `title`·`tldr`·`hubs`·`source`·`rank`·`gate`·`velocity`·`insight_candidate`·`hub_candidate`·`new_hub`·`held`·`interrupted`·`topic`을 모은다. 노트를 다시 읽지 않는다. 채팅 출력 + `research-autopilot/<날짜>.md`(같은 날 둘째면 `-2`). 파일 안 논문은 `papers/<slug>` 평문 경로(`[[wikilink]]` 금지 — inbound가 생겨 hub 소속과 섞인다). vault 본문 격리 적용. "autopilot 보고"는 파일 저장 없음.

```
📋 autopilot 실행 보고 — {run_started} → {정지 시각} · scope: {…} · 정지: {reason}
   처리 {N}편 (ok {a} · partial {b}) · source: S1 {…} · S2 {…} · S0 {…} · PA {…} · F {…} · 건너뜀 {s}(scope 밖 {x}) · 보류 {h} · 끊김 {i} · 새 hub: {…|-} · hub 후보: {…|-}
   {PA만 처리했으면: ⚠️ 신규 유입 없음 — scope 안 S1/S2 고갈, 백필만 돌았다. scope를 넓히거나 우선 큐를 채울 때}
## 들어온 논문         ← 1. {title} (arXiv:{id}) — papers/{slug} · {rank}/{source} · {gate} · hubs · vel {v} / {tldr}
## 탐색 주제           ← - {slug}: seed {n}건 · 들어옴 {m}편 · 승격 {hub|-}   (탐색 주제가 있을 때만; explore 편입은 "(explore)" 표시)
## 통찰 후보 — 저장되지 않았다. 고르면 insight-capture 초안 모드로   ← - {slug}: {insight_candidate}
## 이번 배치가 말하는 것   ← 2~3문장, 위 TL;DR과 후보만으로. 새 조사·추측 금지. 근거 없으면 "종합할 공통점 없음"
## 아침 할 일           ← figure on-demand 후보 · hub 후보 검토/새 hub 확인 · 탐색 주제 검토(seed 0건이면 query 수정, 관심 밖이면 줄 삭제) · 보류 {h}건 · scope 밖 {x}건 · wiki-lint(L4 stale 후보 hub)
```

아침 검토: 보고서 → `grep "^## \[" _meta/autopilot-log.md`(`start` 수 ≠ 결과 수면 열린 반복) → `grep -o 'gate=[a-z]*' … | sort | uniq -c`. 그림은 `paper-ingest` override, `## 보류`·`## 건너뜀`은 줄을 지우면 되살아남, hub 요약은 `wiki-lint`, 통찰은 `insight-capture`, 대기열은 `reading-queue`.
