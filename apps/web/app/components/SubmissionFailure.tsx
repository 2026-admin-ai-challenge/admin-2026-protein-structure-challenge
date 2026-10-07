"use client";
import { useState } from "react";
import { api } from "../lib/api";
import { FAILURE_HELP } from "../lib/status";
import type { Submission } from "../types";

export default function SubmissionFailure({
  submission: s,
  admin,
}: {
  submission: Submission;
  admin: boolean;
}) {
  const [log, setLog] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  async function loadLog() {
    if (log !== null || loading) return;
    setLoading(true);
    setError("");
    try {
      const detail = await api<{ log_tail: string | null }>(
        `/admin/submissions/${s.id}`,
      );
      setLog(detail.log_tail || "저장된 실행 로그가 없습니다.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }
  return (
    <div
      className="submission-failure"
      role="note"
      aria-label={`제출 ${s.id} 오류 상세`}
    >
      <strong>제출 #{s.id} 실패 원인</strong>
      <p>{s.error_message || "채점 중 오류가 발생했습니다."}</p>
      <p className="failure-explanation">
        {s.failure_detail ||
          (s.failure_code && FAILURE_HELP[s.failure_code]) ||
          "운영진에게 접수 ID와 함께 문의해 주세요."}
      </p>
      <small>
        오류 코드: {s.failure_code || "unknown"} ·{" "}
        {s.counted ? "제출 횟수 1회 차감" : "제출 횟수 차감 없음"}
      </small>
      {admin && (
        <details
          onToggle={(event) => {
            if (event.currentTarget.open) void loadLog();
          }}
        >
          <summary>운영진 실행 로그 · 전체 traceback 확인</summary>
          <p className="muted">
            평가 입력이 포함될 수 있는 운영진 전용 로그입니다.
          </p>
          {loading && <p>로그를 불러오는 중…</p>}
          {error && (
            <div className="alert error" role="alert">
              {error}
              <button className="btn secondary compact" onClick={loadLog}>
                다시 시도
              </button>
            </div>
          )}
          {log !== null && <pre className="log-tail">{log}</pre>}
        </details>
      )}
    </div>
  );
}
