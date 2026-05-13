"""FastAPI app factory. 실행: `uvicorn api.main:create_app --factory`.

agent/session_store를 주입할 수 있어(테스트) lifespan은 미주입 시에만 실 자원을 생성한다.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import chat, skills


def create_app(agent=None, session_store=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if getattr(app.state, "agent", None) is None:
            from agent.runtime import make_agent

            app.state.agent = make_agent()
        if getattr(app.state, "session_store", None) is None:
            from agent.sessions import SqliteSessionStore
            from wiki.vault import vault_root

            app.state.session_store = SqliteSessionStore(vault_root() / "_meta" / "sessions.db")
        yield

    app = FastAPI(title="Research Agent API", lifespan=lifespan)
    app.state.agent = agent
    app.state.session_store = session_store

    origins = [o for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(chat.router)
    app.include_router(skills.router)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app
