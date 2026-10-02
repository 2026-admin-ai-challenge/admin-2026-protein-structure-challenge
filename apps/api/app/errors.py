from fastapi import HTTPException

# Failure codes written by the worker. Messages are safe to show to participants:
# they never include container output, which could leak hidden evaluation input.
FAILURES = {
    "zip_invalid": "ZIP 내용이 제출 규격에 맞지 않습니다.",
    "runtime_error": "추론 코드가 오류와 함께 종료되었습니다.",
    "timeout": "추론이 제한 시간 안에 끝나지 않았습니다.",
    "out_of_memory": "추론 중 메모리 한도를 넘어 종료되었습니다.",
    "output_missing": "예측 파일이 생성되지 않았습니다.",
    "output_invalid": "예측 파일 형식이 올바르지 않습니다.",
    "system_error": "채점 서버 오류입니다. 운영진이 확인한 뒤 다시 채점합니다.",
}
# Server-side faults never use up one of the team's attempts.
SYSTEM_FAILURES = {"system_error"}


class ApiError(HTTPException):
    """HTTP error carrying a stable machine-readable code next to the Korean message."""

    def __init__(self, status_code, code, message):
        super().__init__(status_code, detail=message)
        self.code = code
