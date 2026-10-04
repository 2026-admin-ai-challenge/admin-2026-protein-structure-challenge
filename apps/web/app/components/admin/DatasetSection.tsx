"use client";
import { useState } from "react";
import { send } from "../../lib/api";
import { count, date, fileSize } from "../../format";
import type { DatasetReport } from "../../types";
import Feedback from "./Feedback";
import { useAdminData } from "./useAdmin";

export default function DatasetSection({ onChanged }: { onChanged: () => void }) {
  const { data, loading, busy, error, notice, run } =
    useAdminData<DatasetReport>("/admin/dataset");
  const [changed, setChanged] = useState<string[] | null>(null);
  const approved = data?.approved;
  const validation = data?.validation;
  return (
    <>
      <Feedback error={error} notice={notice} loading={loading} />
      {data && approved && (
        <>
          <div className="stat-cards">
            <div className={data.metadata_present ? "" : "warn"}>
              <small>연결된 데이터 버전</small>
              <strong>{data.version ?? "—"}</strong>
              <span>
                {data.metadata_present
                  ? "데이터 저장소의 metadata.json 기준"
                  : "metadata.json이 없습니다. 데이터 디렉터리 연결을 확인하세요."}
              </span>
            </div>
            <div className={validation?.passed ? "" : "warn"}>
              <small>데이터 검증</small>
              <strong>
                {validation
                  ? validation.passed
                    ? "통과"
                    : "미통과"
                  : "정보 없음"}
              </strong>
              <span>
                {validation
                  ? "데이터팀 검증 기록"
                  : "데이터팀 manifest에 검증 결과가 아직 없습니다."}
              </span>
            </div>
            <div className={approved.version ? "" : "warn"}>
              <small>공개 승인</small>
              <strong>{approved.version ?? "미승인"}</strong>
              <span>
                {approved.at
                  ? `${date(approved.at)} · ${approved.by}`
                  : "승인 전에는 대회가 열려도 다운로드가 잠깁니다."}
              </span>
            </div>
            <div>
              <small>잠금</small>
              <strong>{approved.locked ? "잠김" : "열림"}</strong>
              <span>잠그면 같은 대회에서 다시 승인할 수 없습니다.</span>
            </div>
          </div>
          {approved.version && data.version !== approved.version && (
            <div className="alert error" role="alert">
              연결된 데이터 버전({data.version ?? "없음"})이 승인된 버전(
              {approved.version})과 다릅니다.
            </div>
          )}
          {changed && (
            <div
              className={"alert " + (changed.length ? "error" : "success")}
              role="status"
            >
              {changed.length
                ? "승인 이후 바뀐 파일: " + changed.join(", ")
                : "모든 파일이 승인 당시의 SHA-256과 일치합니다."}
            </div>
          )}
          <div className="admin-actions">
            <button
              className="btn primary"
              disabled={busy || approved.locked || !data.metadata_present}
              onClick={() => {
                if (
                  confirm(
                    "현재 파일의 SHA-256을 기록하고 이 버전을 참가자 공개용으로 승인할까요?",
                  )
                )
                  run(async () => {
                    await send("/admin/dataset/approve");
                    setChanged(null);
                    onChanged();
                  }, "데이터 버전을 승인했습니다.");
              }}
            >
              현재 버전 승인
            </button>
            <button
              className="btn secondary"
              disabled={busy || !approved.version}
              onClick={() =>
                run(async () =>
                  setChanged(
                    (
                      await send<{ ok: boolean; changed: string[] }>(
                        "/admin/dataset/verify",
                      )
                    ).changed,
                  ),
                )
              }
            >
              파일 변경 여부 검사
            </button>
            <button
              className="btn secondary"
              disabled={busy || !approved.version}
              onClick={() =>
                run(
                  () => send("/admin/dataset/lock", { locked: !approved.locked }),
                  approved.locked ? "잠금을 해제했습니다." : "데이터 버전을 잠갔습니다.",
                )
              }
            >
              {approved.locked ? "잠금 해제" : "버전 잠금"}
            </button>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>참가자 공개 파일</th>
                  <th>상태</th>
                  <th>행 수</th>
                  <th>크기</th>
                  <th>승인된 SHA-256</th>
                </tr>
              </thead>
              <tbody>
                {data.files.map((f) => (
                  <tr key={f.name}>
                    <td>
                      <strong>{f.name}</strong>
                    </td>
                    <td>
                      <span
                        className={
                          "status-pill " + (f.present ? "succeeded" : "queued")
                        }
                      >
                        {f.present ? "있음" : "없음"}
                      </span>
                    </td>
                    <td>{count(f.rows)}</td>
                    <td>{fileSize(f.bytes)}</td>
                    <td>
                      <code>{f.approved_sha256 ?? "—"}</code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted">
            평가 입력과 정답은 이 목록에 없습니다. 웹 서버에는 연결되지 않으며
            채점 작업자만 읽습니다. 데이터 생성과 검증은 대회 전에 데이터
            저장소에서 마칩니다.
          </p>
        </>
      )}
    </>
  );
}
