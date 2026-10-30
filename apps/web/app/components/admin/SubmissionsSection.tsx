"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, send } from "../../lib/api";
import { date, fileSize } from "../../format";
import { isPending } from "../../lib/status";
import type { AdminSubmission, FileCheck } from "../../types";
import StatusPill from "../StatusPill";
import Feedback from "./Feedback";
import { useAdminData } from "./useAdmin";

const STATUSES = ["queued", "running", "succeeded", "failed"];
const FAILURE_CODES = [
  "zip_invalid",
  "install_failed",
  "runtime_error",
  "timeout",
  "out_of_memory",
  "output_missing",
  "output_invalid",
  "system_error",
];
// Refresh only while the tab is visible: a forgotten background tab should not
// keep sending requests.
const REFRESH_MS = 10000;

export default function SubmissionsSection({
  finalized,
  onChanged,
}: {
  finalized: boolean;
  onChanged: () => void;
}) {
  const [status, setStatus] = useState(""),
    [failureCode, setFailureCode] = useState(""),
    [search, setSearch] = useState(""),
    [query, setQuery] = useState(""),
    [detail, setDetail] = useState<AdminSubmission | null>(null),
    [fileCheck, setFileCheck] = useState<FileCheck | null>(null);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (detail) box.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [detail]);
  const path = useMemo(() => {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (failureCode) params.set("failure_code", failureCode);
    if (query) params.set("q", query);
    return "/admin/submissions?" + params.toString();
  }, [status, failureCode, query]);
  const { data, loading, busy, error, notice, reload, run } =
    useAdminData<AdminSubmission[]>(path);
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!document.hidden) reload();
    }, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [reload]);
  const open = (id: number) =>
    run(async () =>
      setDetail(await api<AdminSubmission>("/admin/submissions/" + id)),
    );
  return (
    <>
      <form
        className="filters"
        onSubmit={(e) => {
          e.preventDefault();
          setQuery(search.trim());
        }}
      >
        <label>
          상태
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">전체</option>
            {STATUSES.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <label>
          실패 사유
          <select
            value={failureCode}
            onChange={(e) => setFailureCode(e.target.value)}
          >
            <option value="">전체</option>
            {FAILURE_CODES.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <label>
          검색 (팀·파일·접수 ID)
          <input value={search} onChange={(e) => setSearch(e.target.value)} />
        </label>
        <button className="btn secondary">검색</button>
        <button
          type="button"
          className="btn secondary"
          disabled={busy}
          onClick={() =>
            run(async () =>
              setFileCheck(await send<FileCheck>("/admin/files/verify")),
            )
          }
        >
          파일 정합성 검사
        </button>
      </form>
      <Feedback error={error} notice={notice} loading={loading} />
      {fileCheck && (
        <div
          className={"alert " + (fileCheck.ok ? "success" : "error")}
          role="status"
        >
          {fileCheck.ok
            ? `보관 중인 ZIP ${fileCheck.checked}개가 DB 기록과 일치합니다.`
            : `ZIP ${fileCheck.checked}개 검사: 디스크에 없음 ${fileCheck.missing.length}, 크기 다름 ${fileCheck.size_mismatch.length}, 삭제 기록인데 남아 있음 ${fileCheck.deleted_present.length}, 기록 없는 파일 ${fileCheck.orphans.length}. 접수 ID: ${
                [...fileCheck.missing, ...fileCheck.size_mismatch]
                  .map((f) => "#" + f.submission_id)
                  .join(", ") || "—"
              }`}
          {fileCheck.stale_uploads > 0 &&
            ` 중단된 업로드 조각 ${fileCheck.stale_uploads}개.`}
        </div>
      )}
      {detail && (
        <div className="secret-box" ref={box}>
          <h3>
            접수 #{detail.id} · {detail.team} · {detail.filename}
          </h3>
          <p>
            SHA-256 {detail.sha256 ?? "—"} · {fileSize(detail.size_bytes)} ·
            시도 {detail.attempts}회 · 작업자 {detail.worker_id ?? "—"} · ZIP{" "}
            {detail.file_deleted
              ? "삭제됨"
              : detail.file_present
                ? "보관 중"
                : "없음"}
          </p>
          {detail.file_deleted && detail.file_deleted_at && (
            <p>
              파일 삭제: {date(detail.file_deleted_at)} ·{" "}
              {detail.file_deleted_by} · 사유: {detail.file_delete_reason}
            </p>
          )}
          <pre className="log-tail">
            {detail.log_tail || "기록된 실행 로그가 없습니다."}
          </pre>
          <button
            className="btn secondary compact"
            onClick={() => setDetail(null)}
          >
            닫기
          </button>
        </div>
      )}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>접수 ID</th>
              <th>Team / Account</th>
              <th>File</th>
              <th>Status</th>
              <th>Public</th>
              <th>Private</th>
              <th>횟수</th>
              <th>조치</th>
            </tr>
          </thead>
          <tbody>
            {(data ?? []).map((s) => (
              <tr key={s.id}>
                <td>
                  #{s.id}
                  <small className="row-error muted">{date(s.created_at)}</small>
                </td>
                <td>
                  {s.team}
                  {s.user && (
                    <small className="row-error muted">{s.user}</small>
                  )}
                </td>
                <td>
                  {s.filename}
                  <small className="row-error muted">
                    {fileSize(s.size_bytes)} · {s.evaluator ?? "미채점"}
                    {s.file_deleted ? " · 파일 삭제됨" : ""}
                    {s.on_leaderboard ? " · 순위 반영" : ""}
                  </small>
                </td>
                <td>
                  <StatusPill status={s.status} />
                  {s.queue_position && (
                    <small className="row-error muted">
                      순서 {s.queue_position}
                    </small>
                  )}
                  {s.failure_code && (
                    <small className="row-error">
                      {s.failure_code}: {s.error_message}
                    </small>
                  )}
                </td>
                <td>{s.public_score?.toFixed(5) ?? "—"}</td>
                <td>{s.private_score?.toFixed(5) ?? "—"}</td>
                <td>{s.counted ? "차감" : "미차감"}</td>
                <td>
                  <div className="row-actions">
                    <button
                      className="btn secondary compact"
                      disabled={busy}
                      onClick={() => open(s.id)}
                    >
                      로그
                    </button>
                    {s.file_id && !s.file_deleted && (
                      <>
                        <a
                          className="btn secondary compact"
                          href={`/api/admin/files/${s.file_id}/download`}
                        >
                          ZIP 받기
                        </a>
                        <button
                          className="btn secondary compact"
                          disabled={busy || s.on_leaderboard || isPending(s.status)}
                          title={
                            s.on_leaderboard
                              ? "순위에 반영된 제출의 파일은 삭제할 수 없습니다"
                              : isPending(s.status)
                                ? "채점이 끝난 뒤 삭제할 수 있습니다"
                                : undefined
                          }
                          onClick={() => {
                            const reason = prompt(
                              `#${s.id} ${s.filename}의 ZIP을 삭제합니다. 점수와 기록은 남고 파일만 지워지며 되돌릴 수 없습니다.\n삭제 사유를 적어 주세요.`,
                            )?.trim();
                            if (reason)
                              run(
                                () =>
                                  send(`/admin/files/${s.file_id}/delete`, {
                                    reason,
                                  }),
                                `#${s.id}의 ZIP을 삭제했습니다.`,
                              );
                          }}
                        >
                          파일 삭제
                        </button>
                      </>
                    )}
                    {s.status === "failed" && !s.file_deleted && (
                      <button
                        className="btn secondary compact"
                        disabled={busy || finalized}
                        onClick={() =>
                          run(async () => {
                            await send(`/admin/submissions/${s.id}/requeue`);
                            onChanged();
                          }, `#${s.id}을 대기열에 다시 넣었습니다.`)
                        }
                      >
                        다시 채점
                      </button>
                    )}
                    <button
                      className="btn secondary compact"
                      disabled={busy}
                      onClick={() =>
                        run(
                          () =>
                            send(
                              "/admin/submissions/" + s.id,
                              { counted: !s.counted },
                              "PATCH",
                            ),
                          s.counted
                            ? `#${s.id}의 제출 횟수를 돌려줬습니다.`
                            : `#${s.id}을 다시 횟수에 포함했습니다.`,
                        )
                      }
                    >
                      {s.counted ? "횟수 복구" : "횟수 차감"}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {data && !data.length && (
          <p className="muted table-note">조건에 맞는 제출이 없습니다.</p>
        )}
      </div>
    </>
  );
}
