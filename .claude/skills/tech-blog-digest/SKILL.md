---
name: tech-blog-digest
description: Anthropic/OpenAI/DeepMind/Google Research 블로그의 미요약 신규 포스트(소스별 최대 10)를 한국어로 요약해 vault `tech-blog-digest/{date}.md`에 누적한다. seen 추적으로 새 포스트만 처리.
trigger:
  - "테크 블로그 요약"
  - "blog digest"
  - "블로그 신착 정리"
inputs:
  - 'limit_per_source (선택, 기본 10)'
---

## When to invoke
실행할 때마다 — 지난 실행에서 seen 처리된 포스트는 제외. 소스당 신규가 한도를 넘으면 최신순 한도만, 나머지는 다음 실행으로 이월(seen에 안 넣으므로 자동).

## Steps

| # | 도구 | 규칙 |
|---|---|---|
| 1 | `get_tech_blog_posts()` | 소스별 미요약 신규 (최신순) |
| 2 | 각 포스트에 `read_blog_post(url)` | 본문. OpenAI는 본문 불가 — step 1의 RSS 발췌 사용 |
| 3 | 요약 (LLM) | 포스트당 2-3문단 한국어 (무엇을/왜/연구 시사점). OpenAI는 1문단 |
| 4 | `wiki_write_note("tech-blog-digest/{date}", fm, body)` | 같은 날 재실행이면 `wiki_read_note` 후 섹션 append |
| 5 | `mark_blog_posts_seen([이번 url 전부])` | **반드시 step 4 성공 후** — 먼저 seen을 남기면 포스트가 유실된다 |

## Frontmatter / Body
```yaml
date: 2026-07-13
type: blog-digest
sources: [anthropic, openai, deepmind, google-research]
post_count: 8
```
```markdown
# Tech Blog Digest — {date}
## 오늘의 흐름          ← 소스 전체를 관통하는 2-4줄 (공통 테마·경쟁 구도)
## Anthropic
### [{제목}]({url}) — {published}
{2-3문단}
## OpenAI
### [{제목}]({url}) — {published}
{1문단} *(본문 접근 불가 — RSS 발췌 기반)*
```
요약만 저장(본문 전문 금지 — 저작권·크기). 원문 링크 필수. 신규 0건 소스는 섹션 생략.

## Output
노트 경로 · 소스별 요약 편수 · 이월 건수(있을 때).

## Failure handling
- 소스 1개 수집 실패 → 나머지 진행, 노트에 "{source} 수집 실패" 한 줄.
- `read_blog_post` 실패 → 제목+링크만 기록하고 seen에 포함(재시도 무한루프 방지). 원하면 수동 재시도.
- 전 소스 0건 → "신규 없음", 저장·mark 없음.
