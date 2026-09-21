"""도구 출력의 상태 표지와 반복 안의 예외를 영구/일시 실패로 가른다.

도구 함수는 실패를 예외 대신 `❌`(없음·형식 오류)·`⚠️`(오류 응답)·`⏳`(호출 한도·일시 장애)로
시작하는 문자열로 돌려준다. 표지를 확인하지 않으면 오류 문구를 논문 본문으로 알고 요약해
저장한다. 영구 실패는 같은 논문을 다시 집어도 똑같이 실패하므로 항목을 건너뜀으로 옮기고,
일시 실패는 항목을 남겨 다음 반복이 재시도한다.
"""

from __future__ import annotations

from pydantic_ai.exceptions import UsageLimitExceeded

from agent.autopilot.notes import VaultIsolationError

_PERMANENT = ("❌", "⚠")
_TRANSIENT = ("⏳",)


class VaultWriteError(RuntimeError):
    """vault에 쓰지 못했다(권한·디스크). 논문 탓이 아니라 실행 환경 문제라 즉시 정지한다."""


class ToolFailure(RuntimeError):
    def __init__(self, message: str, *, permanent: bool):
        super().__init__(message)
        self.permanent = permanent


def check_tool_output(text: str) -> str:
    """상태 표지로 시작하면 첫 줄을 메시지로 ToolFailure, 아니면 그대로 돌려준다."""
    head = text.lstrip().split("\n", 1)[0].strip() if isinstance(text, str) else ""
    if head.startswith(_PERMANENT):
        raise ToolFailure(head, permanent=True)
    if head.startswith(_TRANSIENT):
        raise ToolFailure(head, permanent=False)
    return text


def classify_failure(exc: BaseException) -> tuple[bool, str]:
    """(영구 실패인가, 로그·건너뜀에 남길 사유)."""
    if isinstance(exc, ToolFailure):
        return exc.permanent, str(exc)
    if isinstance(exc, FileExistsError):
        return True, f"slug 충돌: {exc}"
    if isinstance(exc, UsageLimitExceeded):
        return True, f"토큰 한도 초과: {exc}"
    if isinstance(exc, VaultWriteError):
        return False, f"vault 쓰기 실패: {exc}"
    if isinstance(exc, VaultIsolationError):
        return False, "vault_isolation"
    return False, f"{type(exc).__name__}: {exc}"


class MetaUnavailable(ToolFailure):
    """SS 상세 조회가 거절됐거나 논문을 찾지 못했다. ❌·⚠️는 영구, ⏳는 일시 실패."""

    def __init__(self, message: str):
        super().__init__(message, permanent=not message.lstrip().startswith("⏳"))
