---
name: wiki-prune
description: vault에서 아무도 쓰지 않는 논문(hub 자동 링크뿐·통찰 근거 아님·인용 분석 안 됨·autopilot frontier 유입 후 90일 경과·hub seed 아님)을 후보로 뽑아 승인된 것만 노트·figure·PDF·그래프째 삭제하고, 깨진 링크는 wiki-lint로 정리한다.
trigger:
  - "vault 프루닝"
  - "안 쓰는 논문 지워줘"
  - "wiki-prune"
inputs:
  - 'min_age_days (선택) — ingest 후 이 일수 미만인 논문은 제외. 기본 90'
---

## When to invoke
autopilot이 쌓은 논문이 많아져 vault가 무거울 때, 또는 명시 요청 시. **삭제 전용** — 논문 추가는 `paper-ingest`, 링크 정합성만 보려면 `wiki-lint`.

## 원칙
- **자동 삭제 금지** — 후보 목록 제시까지. 삭제는 사용자가 번호로 승인한 것만.
- 후보 판정은 도구가 한다. 에이전트는 목록을 줄이거나 늘리지 않는다 — 조건 밖 논문을 "안 중요해 보인다"고 추가하지 않고, 후보를 "중요해 보인다"고 임의로 빼지 않는다(빼는 것은 사용자 몫).
- 삭제는 되돌릴 수 없다(vault는 git 밖). 되돌림 경로는 로그의 arxiv_id로 다시 ingest하는 것뿐이므로 **로그를 먼저 쓰고 지운다**.
- vault에 쓰는 어떤 텍스트에도 내부 메타 식별자를 넣지 않는다. 로그는 `_meta/`에만.

## Steps

| # | 동작 | 도구 |
|---|---|---|
| 1 | 후보 목록 — 번호·slug·arxiv_id·제목·velocity·ingest일·inbound·PDF 크기 | `wiki_prune_candidates(min_age_days=90)` |
| 2 | 목록 + 합계(편수·PDF MB) 제시 → **승인 요청** ("전부" / 번호 / "없음") | (대화) |
| 3 | 승인된 항목을 `_meta/prune-log.md`에 append — 삭제 **전에** | `wiki_read_note("_meta/prune-log")` → `wiki_write_note` |
| 4 | 승인된 slug마다 삭제 | `wiki_delete_paper(slug)` |
| 5 | 깨진 링크 정리 — 삭제된 slug를 가리키던 hub·다이제스트·보고서의 `[[slug]]` | `wiki-lint` (scope=all) |

- 0건이면 step 2에서 "후보 없음"으로 끝낸다.
- step 5의 wiki-lint는 자체 승인 게이트를 가진다. 삭제된 slug로의 깨진 링크는 "링크 삭제"를 제안하되, `tech-blog-digest/`에서 온 것은 미수록 논문 취급이 아니라 **삭제된 논문**이므로 재읽기 큐에 올리지 않는다 — 로그의 arxiv_id와 대조.

## prune 로그 (`_meta/prune-log.md`)
```markdown
## [2026-11-06] prune | 후보 18 · 승인 18 · PDF 148 MB
- loopvl · 2609.38426 · LoopVL: ... · vel 0 · ingested 2026-10-14 · inbound topics/vlm
- spatialcore · 2609.38716 · SpatialCore: ... · vel 0 · ingested 2026-10-14 · inbound 없음
```
헤더는 `grep "^## \[" prune-log.md | tail -5`로 읽는다. 재ingest는 줄의 arxiv_id로 `paper-ingest`.

## Output
후보 수·PDF 합계 → 승인 → 삭제된 편수·회수된 MB·삭제 경로 요약 → wiki-lint 결과(깨진 링크 몇 건 정리).

## Failure handling
- 로그 없음(`_meta/autopilot-log.md`) → 후보를 증명할 유입 기록이 없어 0건. 수동 ingest만 있는 vault라고 안내.
- `wiki_delete_paper`가 `❌` → 그 slug는 건너뛰고 나머지 진행, 끝에 실패 목록. 로그에는 이미 적혔으므로 `(삭제 실패)`를 줄 끝에 덧붙인다.
- `_meta/prune-log.md` 없음 → `# Prune Log` 헤더로 생성.
