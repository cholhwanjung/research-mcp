"""`python -m agent.cli "<message>" [--mode ask|accept_edits|read_only]` — 터미널에서 에이전트 1회 실행.

tool 호출은 진행 중 stderr로 표시하고, 승인 요청과 최종 응답은 stdout으로 출력한다. CLI는 승인을 받지 않는다 —
승인이 필요한 호출에서 멈추면 미리보기를 보여주고 끝난다.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from agent.permissions import MODES, Policy
from agent.runtime import HarnessDeps, make_agent, resolve_model_name
from agent.streaming import run_event_stream


async def _run(message: str, model: str | None, mode: str) -> int:
    agent = make_agent(model)
    deps = HarnessDeps(policy=Policy(mode), model_name=resolve_model_name(model))
    async for event in run_event_stream(agent, message, deps=deps):
        etype = event["type"]
        if etype == "tool_call":
            print(f"  ▸ {event['tool']}({event['args']})", file=sys.stderr, flush=True)
        elif etype == "approval_required":
            for request in event["requests"]:
                meta = request.get("metadata") or {}
                print(f"⏸ 승인 필요: {request['tool']} — {meta.get('reason', '')}")
                if meta.get("preview"):
                    print(meta["preview"])
            print("(CLI는 승인을 받지 않는다 — 웹 UI에서 승인하거나 --mode accept_edits로 다시 실행)")
        elif etype == "done":
            print(event.get("output") or "")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent.cli", description="Research agent CLI")
    parser.add_argument("message", help="에이전트에게 보낼 메시지")
    parser.add_argument("--model", default=None, help="provider:model (예: openai:gpt-5)")
    parser.add_argument("--mode", default="ask", choices=MODES, help="권한 모드 (기본 ask)")
    args = parser.parse_args(argv)
    return asyncio.run(_run(args.message, args.model, args.mode))


if __name__ == "__main__":
    raise SystemExit(main())
