"use client";
import { date } from "../../format";
import type { AuditEntry } from "../../types";
import Feedback from "./Feedback";
import { useAdminData } from "./useAdmin";

export default function AuditSection() {
  const { data, loading, error, reload } =
    useAdminData<AuditEntry[]>("/admin/audit?limit=200");
  return (
    <>
      <Feedback error={error} notice="" loading={loading} />
      <div className="admin-actions">
        <button className="btn secondary" onClick={reload}>
          새로 고침
        </button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>시각</th>
              <th>담당자</th>
              <th>조작</th>
              <th>대상</th>
              <th>결과</th>
              <th>내용</th>
            </tr>
          </thead>
          <tbody>
            {(data ?? []).map((entry) => (
              <tr key={entry.id}>
                <td>{date(entry.created_at)}</td>
                <td>{entry.actor}</td>
                <td>
                  <strong>{entry.action}</strong>
                </td>
                <td>{entry.target}</td>
                <td>
                  <span
                    className={
                      "status-pill " + (entry.ok ? "succeeded" : "failed")
                    }
                  >
                    {entry.ok ? "성공" : "실패"}
                  </span>
                </td>
                <td>
                  <small className="row-error muted">{entry.detail}</small>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {data && !data.length && (
          <p className="muted table-note">아직 기록된 조작이 없습니다.</p>
        )}
      </div>
    </>
  );
}
