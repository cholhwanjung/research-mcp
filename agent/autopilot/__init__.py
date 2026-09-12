"""독립 autopilot 런타임 — Claude Code(`/loop`·서브에이전트·Cron) 없이 무인 축적 루프를 돈다.

스킬 모드와 같은 vault·같은 제어 노트(`_meta/autopilot.md`)·같은 로그 문법을 쓴다.
결정론 부분(제어 노트·로그·게이트·대기열·기록)은 코드가, 판단 부분(요약·hub 판정·
유용도)은 provider 무관 에이전트가 맡는다.
"""
