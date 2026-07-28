---
name: tech-blog-digest
description: Anthropic/OpenAI/Google Gemini/DeepMind 테크 블로그의 미요약 신규 포스트를 소스별 최대 5개씩 가져와 본문(불가 소스는 RSS) 기반 몇 문단 한국어 요약으로 vault `digests/blogs-{date}.md`에 누적한다. seen 상태를 추적해 실행 시점까지 쌓인 새 포스트만 처리.
trigger:
  - "테크 블로그 요약"
  - "blog digest"
  - "블로그 다이제스트"
  - "블로그 신착 정리"
inputs:
  - limit_per_source (int, 옵션, 기본 5)
---

## When to invoke
사용자가 실행할 때마다 — 지난 실행에서 요약한 포스트는 제외되고, 그 이후 쌓인
신규만 처리된다. 소스당 신규가 3개면 3개, 10개면 최신순 5개만 요약하고
나머지는 다음 실행으로 이월 (seen에 안 넣으므로 자동 이월).

## Steps (tool sequence)

| # | Tool | 목적 |
|---|---|---|
| 1 | `get_tech_blog_posts(limit_per_source=5)` | 소스별 미요약 신규 포스트 목록 (최신순, seen 제외) |
| 2 | 본문 지원 소스의 각 포스트에 `read_blog_post(url)` | 본문 텍스트. OpenAI는 skip — step 1의 RSS 요약 사용 |
| 3 | (LLM 추론) | 포스트당 **2-3문단 한국어 요약**. OpenAI는 RSS 발췌 기반 1문단 |
| 4 | `wiki_write_note(f"digests/blogs-{date}", frontmatter, body)` | vault 저장. 같은 날 재실행이면 기존 노트 `wiki_read_note` 후 섹션 append |
| 5 | `mark_blog_posts_seen([이번에 다룬 url 전부])` | 처리 확정 — 다음 실행에서 제외 |

**step 5는 반드시 step 4 성공 후.** 노트 저장 전에 seen을 남기면 포스트가 유실된다.

## Frontmatter

```yaml
date: 2026-07-13
type: blog-digest
sources: [anthropic, openai, gemini, deepmind]
post_count: 8
```

## Body 구조 (고정 헤더)

```markdown
# Tech Blog Digest — {date}

## 오늘의 흐름
{소스 전체를 관통하는 2-4줄 한국어 요약 — 공통 테마·경쟁 구도}

## Anthropic
### [{제목}]({url}) — {published}
{2-3문단 요약: 무엇을/왜/연구 관점 시사점}

## OpenAI
### [{제목}]({url}) — {published}
{1문단 요약} *(본문 접근 불가 — RSS 발췌 기반)*
```

- vault에는 **요약만** 저장 — 본문 전문을 노트에 붙여넣지 않는다 (저작권·노트 크기).
- 각 포스트에 원문 링크 필수.
- 신규 0건인 소스는 섹션 생략.

## Output format (사용자 응답)

```
🗞️ Tech Blog Digest 완료: digests/blogs-{date}.md
   요약: anthropic {n}편 · openai {n}편 · gemini {n}편 · deepmind {n}편
   이월: {소스별 "신규 N건 중 M건"의 N-M 합이 0보다 크면 명시}
```

## Failure handling
- 소스 1개 수집 실패 → 나머지 소스로 진행, 노트에 "{source} 수집 실패" 한 줄 명시.
- `read_blog_post` 실패 (레이아웃 변경 등) → 해당 포스트는 제목+링크만 기록하고 seen에 포함
  (매 실행 재시도 무한루프 방지). 사용자가 원하면 수동 재시도.
- 전 소스 신규 0건 → "신규 포스트 없음" 안내, 노트 저장 skip, mark 호출 없음.
