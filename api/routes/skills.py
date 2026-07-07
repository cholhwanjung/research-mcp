"""GET /skills — 사용 가능한 워크플로우(skill) 메타."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from agent.skills_loader import load_skills
from api.deps import verify_token
from api.models import SkillItem

router = APIRouter(dependencies=[Depends(verify_token)])


@router.get("/skills", response_model=list[SkillItem])
def skills():
    return [
        SkillItem(name=s.name, description=s.description, triggers=s.triggers)
        for s in load_skills()
    ]
