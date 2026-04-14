# PRD — Research MCP

> Liner 스타일 시각적 연구 흐름 요약 + Karpathy식 로컬 LLM Wiki + Claude Desktop Skill 워크플로우 + 자가개선 하네스를 갖춘 개인용 연구 에이전트.

관련 문서: [ARCHITECTURE](ARCHITECTURE.md) · [ADR](ADR.md) · [PLAN](PLAN.md) · [../CLAUDE.md](../CLAUDE.md)

---

## 1. 비전

> "한 번 본 논문은 영원히 누적되고, 한 주제의 연구 흐름은 한 장의 그림으로 본다."

상용 도구(Liner)가 보여주는 토픽 중심의 시각적 인용 그래프를 **로컬 위키와 결합**하여, 매번 새로 검색하는 대신 **시간이 지날수록 더 똑똑해지는 개인 연구 에이전트**를 만든다.

---

## 2. 사용자 & 사용 맥락

- 단일 사용자 (개인 연구자).
- 실행 환경: **Claude Desktop + MCP 서버**.
- 출력 언어: 한국어 기본.
- 저장소: 로컬 파일시스템 (Obsidian vault + `pdfs/`).

---

## 3. 핵심 요구사항

### R1. 시각적 연구 흐름 요약
- 특정 주제(또는 anchor 논문)를 중심으로 **무엇을 위해 인용했는가**를 그룹별로 보여줘야 한다 (model / data / method / benchmark / comparison / discussion).
- "기간 대비 인용수" (citation velocity) 기준으로 **top-5** 추출 — 절대 인용수만으로는 오래된 논문이 항상 이긴다.
- 출력: **Mermaid graph** + **Obsidian Canvas JSON** 둘 다 — 첨부 스크린샷처럼 anchor 중심 카드 UI.

### R2. Karpathy LLM Wiki 철학 (멀티모달 KB)
- 사용자가 한 번 쿼리한 논문은 **PDF 원본을 로컬에 저장**.
- 요약 + 메타 + 인용그룹 스냅샷을 **Obsidian vault 노트**로 누적.
- 모든 노트는 frontmatter + `[[wikilink]]` 양방향 링크를 사용 → 백링크로 자동 교차참조.
- 한 노트 = 한 논문 또는 한 주제 (atomicity 유지).
- **멀티모달**: 논문 내 figure(architecture diagram·plot 등)도 추출해 vault에 저장. Claude가 후속 세션에서 시각 정보를 다시 활용 가능 ([ADR-010](ADR.md#adr-010)).

### R3. 툴 독립성 + 스킬화
- MCP **tool은 작고 직교(orthogonal)** — 한 도구가 두 책임을 겸하지 않는다.
- 호출 순서를 가진 워크플로우는 **Claude Skill**(`.claude/skills/*/SKILL.md`)에 담는다.
- Claude Desktop이 자연어 한 줄로 스킬을 호출할 수 있어야 한다.

### R4. 데이터 소스 3종 (2026-05-31 정리)
- **arXiv** — 검색 + 원본 PDF
- **Semantic Scholar** — citation graph (+ `contexts` 필드로 인용 의도 분류 보조)
- **Hugging Face Daily Papers** — 일일 인기 논문
- ~~GeekNews (news.hada.io)~~ — endpoint default-UA 차단 (지속 403), UA 헤더 추가에도 미해결 → 도구·워크플로우에서 제외. 후속 ADR로 재검토 가능.

### R5. 자가개선 하네스
- **CLAUDE.md + docs/* 가 코드와 함께 진화**.
- 매 세션 또는 명시적 트리거(`self-improve` 스킬)에서 사용자 정정/실패/패턴을 추출하여 문서에 반영.
- 변경 이력은 `vault/_meta/changelog.md`에 누적.

---

## 4. 비목표 (Non-Goals)

- 다중 사용자 / 협업 (단일 사용자 가정 → vault 동시쓰기 잠금 없음).
- 모바일 클라이언트.
- 클라우드 호스팅 — 모두 로컬.
- 완전 자동 큐레이션 — 그룹 분류 결과는 사용자가 vault에서 직접 수정 가능해야 함.

---

## 5. 현재 상태 (As-Is, 2026-05-30)

| 항목 | 현재 |
|---|---|
| 구조 | 단일 `server.py` (~470 LoC), 5개 MCP tool |
| 데이터 소스 | arXiv · Semantic Scholar (HF Daily / GeekNews **없음**) |
| 영속성 | **없음** — 매 호출마다 네트워크 fetch |
| 주제 그룹핑 | **없음** — 단순 인용수 정렬 |
| 시각화 | 텍스트 리스트만 |
| 워크플로우화 | tool만 있음, 사용자가 매번 손으로 순서 짜야 함 |
| 자가개선 | **없음** |

장점: 5개 도구가 어느 정도 직교적이고, Semantic Scholar 페이지네이션·한글 출력 포맷이 잘 다듬어져 있음. → **폐기가 아닌 분해 후 재배치** 대상.

---

## 6. 성공 기준

- "주제 X의 흐름 보여줘" 한 마디로 Mermaid + Canvas 산출.
- 한 번 ingest한 논문은 다음 세션에서 vault에서 즉시 인용 가능 (네트워크 fetch 없이).
- 매일 `daily-digest` 스킬 1회 실행으로 HF Daily 신착이 vault에 누적.
- CLAUDE.md가 6개월 후에도 현재 코드 구조와 일치 — 자가개선 루프가 실제로 돈다는 증거.
