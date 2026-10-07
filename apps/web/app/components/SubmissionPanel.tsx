"use client";
import { Fragment, useEffect, useRef, useState } from "react";
import { ArrowRight, ArrowUpRight, Lock, Upload } from "lucide-react";
import { ApiError, api, uploadZip } from "../lib/api";
import { isPending } from "../lib/status";
import SubmissionFailure from "./SubmissionFailure";
import { date, fileSize, megabytes, minutes } from "../format";
import type {
  Competition,
  Quota,
  Submission,
  SubmissionHistory,
  User,
} from "../types";
import Empty from "./Empty";
import StatusPill, { MockNotice } from "./StatusPill";

const POLL_MS = 3000;

export default function SubmissionPanel({
  user,
  competition,
  onLogin,
  onScored,
}: {
  user: User | null;
  competition: Competition | null;
  onLogin: () => void;
  onScored: () => void;
}) {
  const [file, setFile] = useState<File | null>(null),
    [drag, setDrag] = useState(false),
    [progress, setProgress] = useState<number | null>(null),
    [error, setError] = useState(""),
    [accepted, setAccepted] = useState<(Submission & Quota) | null>(null),
    [history, setHistory] = useState<Submission[]>([]),
    [quota, setQuota] = useState<Quota | null>(null),
    [loaded, setLoaded] = useState(false);
  const input = useRef<HTMLInputElement>(null),
    previous = useRef<Submission[]>([]);
  const limits = competition?.limits;
  const open = competition?.submission_open ?? false;
  const uploading = progress !== null;
  const pending = history.some((s) => isPending(s.status));

  async function load() {
    try {
      const data = await api<SubmissionHistory>("/submissions/me");
      // A submission that just left the queue may have changed the leaderboard.
      const finished = previous.current.some(
        (old) =>
          isPending(old.status) &&
          data.entries.some((s) => s.id === old.id && !isPending(s.status)),
      );
      previous.current = data.entries;
      setHistory(data.entries);
      if (finished) onScored();
      setQuota({
        used: data.used,
        limit: data.limit,
        remaining: data.remaining,
      });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoaded(true);
    }
  }
  useEffect(() => {
    if (user) load();
    else {
      previous.current = [];
      setHistory([]);
      setQuota(null);
      setAccepted(null);
      setLoaded(false);
    }
  }, [user?.id]);
  // Keep the status fresh while anything is waiting or being scored.
  useEffect(() => {
    if (!user || !pending) return;
    const timer = window.setInterval(() => {
      if (!document.hidden) load();
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [user?.id, pending]);

  function choose(next: File | null) {
    setAccepted(null);
    setError("");
    if (next && !next.name.toLowerCase().endsWith(".zip")) {
      setFile(null);
      setError("ZIP 파일만 제출할 수 있습니다.");
      return;
    }
    if (next && limits && next.size > limits.zip_bytes) {
      setFile(null);
      setError(
        `ZIP 파일은 최대 ${megabytes(limits.zip_bytes)}입니다. 선택한 파일: ${fileSize(next.size)}`,
      );
      return;
    }
    setFile(next);
  }

  async function submit() {
    if (!file || !quota) return;
    if (
      !window.confirm(
        `${file.name} (${fileSize(file.size)})을 제출할까요?\n접수되면 팀 제출 횟수 1회를 사용합니다. 남은 횟수: ${quota.remaining}회`,
      )
    )
      return;
    setError("");
    setAccepted(null);
    setProgress(0);
    try {
      const result = await uploadZip(file, setProgress);
      setAccepted(result);
      setFile(null);
      if (input.current) input.current.value = "";
      await load();
    } catch (e) {
      const failure = e as ApiError;
      setError(
        failure.status === 413
          ? "파일이 너무 큽니다. " + failure.message
          : failure.message,
      );
      if (failure.code === "limit_reached" || failure.code === "closed") load();
    } finally {
      setProgress(null);
    }
  }

  const required = limits?.required_entries ?? [];
  return (
    <div className="page-content">
      <div className="section-kicker">TURN AN IDEA INTO A SCORE</div>
      <h2 className="section-title">Your next breakthrough.</h2>
      <p className="body-copy">
        학습을 마친 모델과 추론 코드를 ZIP으로 제출하세요. 서버가 숨겨진 평가
        데이터로 추론만 실행해 Public Macro F1을 계산합니다.
      </p>
      {competition?.evaluator === "mock" && <MockNotice />}
      {!user ? (
        <div className="sign-in-card">
          <Lock size={28} />
          <h3>제출하려면 로그인하세요</h3>
          <p>운영진에게 받은 팀 아이디로 로그인합니다.</p>
          <button className="btn primary" onClick={onLogin}>
            Log in <ArrowRight size={16} />
          </button>
        </div>
      ) : (
        <>
          <div className="submit-grid">
            <div>
              <div
                className={"dropzone " + (drag ? "drag" : "")}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDrag(true);
                }}
                onDragLeave={() => setDrag(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDrag(false);
                  if (!uploading) choose(e.dataTransfer.files[0] ?? null);
                }}
              >
                <span className="upload-circle">
                  <Upload size={26} />
                </span>
                <h3>{file ? file.name : "Drop your model here."}</h3>
                <p>
                  {file
                    ? fileSize(file.size)
                    : "code.zip을 끌어다 놓거나 파일을 선택하세요."}
                </p>
                <input
                  ref={input}
                  type="file"
                  accept=".zip,application/zip"
                  onChange={(e) => choose(e.target.files?.[0] ?? null)}
                  hidden
                />
                <button
                  className="btn secondary"
                  disabled={uploading}
                  onClick={() => input.current?.click()}
                >
                  Browse files
                </button>
                {limits && (
                  <small>
                    ZIP only · 최대 {megabytes(limits.zip_bytes)} · 추론 최대{" "}
                    {minutes(limits.inference_seconds)}
                  </small>
                )}
              </div>
              {uploading && (
                <div
                  className="progress"
                  role="progressbar"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={Math.round((progress ?? 0) * 100)}
                >
                  <i style={{ width: `${(progress ?? 0) * 100}%` }} />
                  <span>
                    {progress !== null && progress >= 1
                      ? "서버에서 ZIP을 확인하는 중…"
                      : `업로드 중 ${Math.round((progress ?? 0) * 100)}%`}
                  </span>
                </div>
              )}
              <button
                className="btn primary full submit-button"
                disabled={
                  !file || uploading || !open || !quota || quota.remaining <= 0
                }
                onClick={submit}
              >
                {uploading ? "Uploading…" : "Submit model"}
                <ArrowUpRight size={17} />
              </button>
              {!open && (
                <p className="muted">
                  {competition?.settings.finalized
                    ? "대회가 종료되어 더 이상 제출할 수 없습니다."
                    : "운영자가 대회를 열면 제출할 수 있습니다."}
                </p>
              )}
              {open && quota && quota.remaining <= 0 && (
                <p className="muted">팀의 제출 횟수를 모두 사용했습니다.</p>
              )}
            </div>
            <aside className="submission-aside">
              <h3>ZIP에 넣을 것</h3>
              <p>
                아래 항목이 ZIP 최상위에 있어야 합니다. 폴더째 압축하면 한 단계
                안쪽에 들어가므로 접수되지 않습니다.
              </p>
              <pre>
                {"code.zip\n" +
                  required
                    .map(
                      (item, i) =>
                        (i === required.length - 1 ? "└── " : "├── ") + item,
                    )
                    .join("\n")}
              </pre>
              <p>
                train.py는 채점 때 실행하지 않지만 반드시 함께 넣어야 합니다.
                채점 중에는 인터넷과 패키지 설치를 쓸 수 없습니다.
                requirements.txt는 사용한 패키지를 알리는 용도입니다.
              </p>
              <div className="quota">
                <span>팀 제출 횟수 (대회 전체)</span>
                <b>
                  {quota ? quota.used : "—"}
                  <small>
                    {" "}
                    / {quota?.limit ?? limits?.team_submissions ?? "—"}
                  </small>
                </b>
              </div>
              <p className="muted">
                팀 계정 전체가 함께 쓰며 날짜가 바뀌어도 초기화되지 않습니다.
              </p>
            </aside>
          </div>
          {error && (
            <div className="alert error" role="alert">
              {error}
            </div>
          )}
          {accepted && (
            <div role="status" className="result good">
              <div>
                <h3>접수되었습니다</h3>
                <p>
                  채점 대기열에 들어갔습니다. 이 화면을 닫아도 채점은 계속되며,
                  결과는 아래 제출 내역에 표시됩니다.
                </p>
              </div>
              <div>
                <small>접수 ID</small>
                <strong>#{accepted.id}</strong>
              </div>
              <div>
                <small>남은 횟수</small>
                <strong>{accepted.remaining}</strong>
              </div>
            </div>
          )}
          <h3 className="history-title">팀 제출 내역</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>접수 ID</th>
                  <th>File</th>
                  <th>Status</th>
                  <th>Public Score</th>
                  <th>Submitted at</th>
                </tr>
              </thead>
              <tbody>
                {history.map((s) => (
                  <Fragment key={s.id}>
                    <tr>
                      <td>#{s.id}</td>
                      <td>
                        <strong>{s.filename}</strong>
                        <small className="row-error muted">
                          {fileSize(s.size_bytes)}
                          {s.submitted_by ? " · " + s.submitted_by : ""}
                        </small>
                      </td>
                      <td>
                        <StatusPill status={s.status} />
                        {s.status === "queued" && s.queue_position && (
                          <small className="row-error muted">
                            대기 순서 {s.queue_position}번째
                          </small>
                        )}
                      </td>
                      <td className="score">
                        {s.public_score?.toFixed(5) ?? "—"}
                      </td>
                      <td>{date(s.created_at)}</td>
                    </tr>
                    {s.status === "failed" && (
                      <tr className="submission-failure-row">
                        <td colSpan={5}>
                          <SubmissionFailure
                            submission={s}
                            admin={user.role === "ADMIN"}
                          />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
            {loaded && !history.length && (
              <Empty
                title="아직 제출 기록이 없습니다"
                text="첫 번째 모델 ZIP을 제출해 보세요."
              />
            )}
          </div>
        </>
      )}
    </div>
  );
}
