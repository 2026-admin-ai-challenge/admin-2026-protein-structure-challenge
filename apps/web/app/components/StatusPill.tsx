import { STATUS_LABEL } from "../lib/status";
import type { SubmissionStatus } from "../types";

export default function StatusPill({ status }: { status: SubmissionStatus }) {
  return (
    <span className={"status-pill " + status}>
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

export function MockNotice() {
  return (
    <div className="alert mock" role="note">
      개발용 mock 채점입니다. 표시되는 점수는 실제 모델 성능이 아닙니다.
    </div>
  );
}
