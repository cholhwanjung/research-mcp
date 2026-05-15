#!/usr/bin/env bash
# 웹 앱 로컬 실행 — 백엔드(uvicorn:8000) + 프론트(Next.js:3000)를 함께 띄우고
# Ctrl-C 한 번으로 둘 다 종료. Docker 불필요.
#
#   ./run-web.sh                # .env 의 RESEARCH_MODEL (미설정 시 기본 Claude)
#   ./run-web.sh google         # Gemini  (google:gemini-2.5-pro)   ← GOOGLE_API_KEY 사용
#   ./run-web.sh anthropic      # Claude  (anthropic:claude-sonnet-4-5) ← ANTHROPIC_API_KEY
#   ./run-web.sh openai         # GPT-4o  (openai:gpt-4o)           ← OPENAI_API_KEY
#   ./run-web.sh google:gemini-2.0-flash   # provider:model 직접 지정
#
# 선택한 모델은 RESEARCH_MODEL 로 export → 백엔드가 .env 값보다 우선 적용
# (core/config 의 .env 로더는 이미 set 된 env 를 덮어쓰지 않음).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

[ -f .env ] || { echo "✗ .env 없음 — 'cp .env.example .env' 후 키를 채우세요." >&2; exit 1; }

# 1) 모델 선택(인자) → RESEARCH_MODEL. provider 별 필요한 키 변수도 기억.
need_key=""
case "${1:-}" in
  ""|default)        : ;;  # .env 의 RESEARCH_MODEL 그대로 사용
  google|gemini)     export RESEARCH_MODEL="google:gemini-2.5-pro";        need_key="GOOGLE_API_KEY" ;;
  anthropic|claude)  export RESEARCH_MODEL="anthropic:claude-sonnet-4-5";  need_key="ANTHROPIC_API_KEY" ;;
  openai|gpt)        export RESEARCH_MODEL="openai:gpt-4o";                need_key="OPENAI_API_KEY" ;;
  *:*)               export RESEARCH_MODEL="$1" ;;  # provider:model 직접 지정
  *) echo "✗ 알 수 없는 모델: '$1'  (google | anthropic | openai | provider:model)" >&2; exit 1 ;;
esac

# 2) 선택한 provider 의 키 사전 점검 — 부팅 전에 친절히 안내 (lifespan traceback 회피).
if [ -n "$need_key" ]; then
  val="${!need_key:-}"
  [ -n "$val" ] || val="$(grep -E "^${need_key}=" .env | head -1 | cut -d= -f2-)"
  if [ -z "${val//[\"\' ]/}" ]; then
    echo "✗ ${RESEARCH_MODEL} 사용에 ${need_key} 가 필요합니다 — .env 에 채우세요." >&2
    exit 1
  fi
fi

echo "▶ 모델   : ${RESEARCH_MODEL:-.env RESEARCH_MODEL (기본값)}"

# 의존성 부트스트랩 (최초 1회만 동작).
[ -d .venv ]            || { echo "▶ uv sync …";           uv sync                   || exit 1; }
[ -d web/node_modules ] || { echo "▶ npm install (web) …"; ( cd web && npm install ) || exit 1; }

# 종료 시 백엔드·프론트 동시 정리 (process group 전체에 신호).
trap 'echo; echo "■ 종료"; kill 0' EXIT

echo "▶ 백엔드 → http://localhost:8000  (API)"
uv run uvicorn api.main:create_app --factory --port 8000 &

echo "▶ 프론트 → http://localhost:3000  (웹 UI · 여기로 접속)"
( cd web && npm run dev ) &

echo "  Ctrl-C 로 백엔드·프론트 동시 종료."
wait
