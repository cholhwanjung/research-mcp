---
name: daily-digest
description: HF Daily Papers를 받아 `digests/<YYYY-MM-DD>.md` 노트로 vault에 누적한다 (ADR-006).
trigger:
  - "오늘 신착 정리해"
  - "daily digest"
  - "오늘 트렌딩 논문"
inputs:
  - date (string, 옵션, YYYY-MM-DD. 기본 오늘 UTC)
  - hf_limit (int, 기본 10)
---

## When to invoke
하루 단위로 인기 논문을 한 노트에 모으고 싶을 때. 1회성 조회만이면 `get_hf_daily_papers` 단독으로 충분.

> GeekNews는 2026-05-31 정리에서 제외됨 — endpoint(news.hada.io/rss)가 default-UA를 403 차단, UA 헤더 추가에도 지속 실패. 후속 ADR이 필요할 경우 재도입.

## Steps (tool sequence)

| # | Tool | 목적 |
|---|---|---|
| 1 | `get_hf_daily_papers(date, limit=10)` | HF Daily Papers (비공식 API → HTML fallback, ADR-006) |
| 2 | (선택) 각 HF 논문에 대해 `get_paper_by_id(arxiv_id)` | citation 수 등 메타 보강 — 토큰 절약을 위해 상위 N편만 |
| 3 | (LLM 추론) | 묶음을 보고 "오늘의 흐름" 3-5줄 한국어 요약 작성 |
| 4 | `wiki_write_note(f"digests/{date}", frontmatter, body)` | vault에 일일 노트 저장 |

## Frontmatter

```yaml
date: 2026-05-31
hf_count: 10
ingested_at: 2026-05-31T13:00:00Z
```

## Body 구조 (고정 헤더)

```markdown
# Daily Digest — 2026-05-31

## 오늘의 흐름
{3-5줄 한국어 요약}

## 🤗 HF Daily Papers (상위 N)
- [[{title-slug}|{Title 약어}]] (arXiv:{arxiv_id}) — {Full Title} (👍 99)
  - {1줄 요약}
- ...
```

wikilink 형식 규약 (ADR-023):
- **link target**은 `core.slug.slugify_title({title})` 결과 — 사람-가독 slug (예: `minwm`, `qwen-vla`). graph view에서 노드 텍스트로 표시됨.
- arxiv_id가 아닌 slug를 사용하는 이유: 그래프에서 `2605.30161`보다 `why-far-looks-up`이 직관적 (ADR-023).
- arxiv_id는 link 옆 `(arXiv:...)` 텍스트로 보존 — 사용자가 paper-ingest 호출 시 식별자.
- alias `|{Title 약어}`로 본문 표시 이름을 짧은 약어로. `[[<slug>]]` 단독도 가능 — 그래프 노드 텍스트는 slug 자체.

paper-ingest 시 같은 slug로 폴더 + 파일 생성되면 자동 backlink 연결 (D-2).

## Output format (사용자 응답)
```
🗞️ Daily Digest 완료: digests/{date}.md
   HF: {N}편 (👍 평균 {avg})
   주요 토픽: {topic_1}, {topic_2}, ...
```

## Failure handling
- step 1 HF Daily 비공식 API 4xx → 자동으로 HTML fallback (ADR-006). 둘 다 실패하면 빈 결과 — body에 "오늘 HF 응답 없음" 명시.
- HF가 빈 결과면 사용자에게 "오늘 신착 없음" 안내하고 노트 저장 skip.

## 자동화 (옵션)
사용자가 매일 아침 자동 실행하길 원하면 `schedule` 스킬과 결합:
- `/schedule "매일 08:00 UTC daily-digest 실행"`
- vault에 `digests/2026-05-30.md`가 매일 자동 누적.
