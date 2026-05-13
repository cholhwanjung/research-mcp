"""API layer — FastAPI 백엔드 (web deploy, ADR-024 W-2).

import 방향: api → agent / wiki / tools / core (단방향). 하위 레이어는 api를 import 하지 않는다.
실행: `uvicorn api.main:create_app --factory`.
"""
