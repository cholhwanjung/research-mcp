"""POST /snapshots/{id}/restore — 에이전트가 쓴 파일을 쓰기 전 내용으로 되돌린다(ADR-063).

읽기 전용 서버(토큰 없음)에서는 되돌리기도 쓰기이므로 거부한다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from agent.workspace import SnapshotStore
from api.deps import resolve_mode, verify_token

router = APIRouter(dependencies=[Depends(verify_token)])


@router.post("/snapshots/{snapshot_id}/restore")
def restore(snapshot_id: str):
    if resolve_mode(None) == "read_only":
        raise HTTPException(status_code=403, detail="read-only server: set RESEARCH_API_TOKEN to restore")
    try:
        path = SnapshotStore().restore(snapshot_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"path": path}
