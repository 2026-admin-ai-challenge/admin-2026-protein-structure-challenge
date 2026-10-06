import type { SubmissionStatus } from "../types";

export const STATUS_LABEL: Record<SubmissionStatus, string> = {
  queued: "대기 중",
  running: "채점 중",
  succeeded: "완료",
  failed: "실패",
};

// What a team can do about each failure code. The server message says what went wrong.
export const FAILURE_HELP: Record<string, string> = {
  zip_invalid:
    "ZIP 구성을 확인하세요. 폴더째 압축하지 말고 필수 항목이 ZIP 최상위에 오도록 압축해야 합니다. 제출 횟수는 차감되지 않습니다.",
  runtime_error:
    "추론 코드가 오류로 끝났습니다. 같은 명령을 내 컴퓨터에서 먼저 실행해 보세요. 채점 중에는 인터넷과 패키지 설치를 쓸 수 없습니다.",
  timeout:
    "추론이 제한 시간 안에 끝나지 않았습니다. 모델이나 전처리를 가볍게 줄여 보세요.",
  out_of_memory:
    "메모리 한도를 넘었습니다. 한 번에 처리하는 양(batch)이나 모델 크기를 줄여 보세요.",
  output_missing:
    "예측 파일이 지정된 경로에 만들어지지 않았습니다. 출력 경로를 확인하세요.",
  output_invalid: "예측 파일의 컬럼(id,label), 행 수, 라벨 값을 확인하세요.",
  system_error:
    "채점 서버 쪽 문제입니다. 제출 횟수는 차감되지 않으며 운영진이 다시 채점합니다.",
};

export const isPending = (status: SubmissionStatus) =>
  status === "queued" || status === "running";
