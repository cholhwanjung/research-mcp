"""`python -m agent.cli "<message>"` — 터미널에서 에이전트 1회 실행.

tool 호출은 진행 중 stderr로 표시하고, 최종 응답은 stdout으로 출력한다.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from agent.runtime import make_agent
from agent.streaming import run_event_stream


async def _run(message: str, model: str | None) -> int:
    agent = make_agent(model)
    async for event in run_event_stream(agent, message):
        etype = event["type"]
        if etype == "tool_call":
            print(f"  ▸ {event['tool']}({event['args']})", file=sys.stderr, flush=True)
        elif etype == "done":
            print(event.get("output") or "")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent.cli", description="Research agent CLI")
    parser.add_argument("message", help="에이전트에게 보낼 메시지")
    parser.add_argument("--model", default=None, help="provider:model (예: openai:gpt-4o)")
    args = parser.parse_args(argv)
    return asyncio.run(_run(args.message, args.model))


if __name__ == "__main__":
    raise SystemExit(main())
