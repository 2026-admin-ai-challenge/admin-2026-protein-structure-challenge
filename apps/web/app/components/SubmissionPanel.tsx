import {
  ArrowUpRight,
  ArrowRight,
  ArrowDown,
  Download,
  Upload,
  Check,
  ChevronRight,
  ChevronDown,
  Sun,
  Moon,
  Menu,
  X,
  FlaskConical,
  Layers3,
  Activity,
  Database,
  Trophy,
  Clock,
  Users,
  FileText,
  Code2,
  ShieldCheck,
  LogOut,
  Plus,
  ExternalLink,
  Lock,
  RotateCcw,
} from "lucide-react";
import type { User, Submission, Settings, Meta } from "../types";
import { date, localTime } from "../format";
import Empty from "./Empty";
export default function SubmissionPanel({
  user,
  setAuth,
  drag,
  setDrag,
  file,
  setFile,
  setResult,
  input,
  busy,
  isActive,
  used,
  settings,
  upload,
  result,
  history,
}: {
  user: User | null;
  setAuth: (value: "login" | "register" | null) => void;
  drag: boolean;
  setDrag: (value: boolean) => void;
  file: File | null;
  setFile: (value: File | null) => void;
  setResult: (value: Submission | null) => void;
  input: React.RefObject<HTMLInputElement | null>;
  busy: boolean;
  isActive: boolean;
  used: number;
  settings: Settings | undefined;
  upload: () => Promise<void>;
  result: Submission | null;
  history: Submission[];
}) {
  return (
    <div className="page-content">
      <div className="section-kicker">TURN AN IDEA INTO A SCORE</div>
      <h2 className="section-title">Your next breakthrough.</h2>
      <p className="body-copy">
        예측을 제출하고 모델의 Public Macro F1을 확인하세요.
      </p>
      {!user ? (
        <div className="sign-in-card">
          <Lock size={28} />
          <h3>참가하려면 로그인하세요</h3>
          <p>내 제출 기록과 최고 점수를 안전하게 보관합니다.</p>
          <button className="btn primary" onClick={() => setAuth("login")}>
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
                  setFile(e.dataTransfer.files[0] ?? null);
                  setResult(null);
                }}
              >
                <span className="upload-circle">
                  <Upload size={26} />
                </span>
                <h3>{file ? file.name : "Drop your next discovery here."}</h3>
                <p>
                  {file
                    ? (file.size / 1024).toFixed(1) + " KB"
                    : "submission.csv를 끌어다 놓거나 파일을 선택하세요."}
                </p>
                <input
                  ref={input}
                  type="file"
                  accept=".csv,text/csv"
                  onChange={(e) => {
                    setFile(e.target.files?.[0] ?? null);
                    setResult(null);
                  }}
                  hidden
                />
                <button
                  className="btn secondary"
                  onClick={() => input.current?.click()}
                >
                  Browse files
                </button>
                <small>CSV only · Max 2 MB · id, label</small>
              </div>
              <button
                className="btn primary full submit-button"
                disabled={
                  !file ||
                  busy ||
                  !isActive ||
                  used >= (settings?.daily_limit ?? 5)
                }
                onClick={upload}
              >
                {busy ? "Validating & scoring…" : "Submit prediction"}
                <ArrowUpRight size={17} />
              </button>
              {!isActive && (
                <p className="muted">
                  운영자가 대회를 열면 제출할 수 있습니다.
                </p>
              )}
            </div>
            <aside className="submission-aside">
              <h3>Ready for a fair test?</h3>
              <p>
                예측 파일을 아래 형식으로 준비하세요. 행 순서는 달라도 ID를
                기준으로 안전하게 정렬합니다.
              </p>
              <pre>
                id,label{"\n"}TEST_000001,3.40{"\n"}TEST_000002,1.10
              </pre>
              <div className="quota">
                <span>Today’s submissions</span>
                <b>
                  {used}
                  <small> / {settings?.daily_limit ?? 5}</small>
                </b>
              </div>
              <p className="muted">UTC 기준 · 잘못된 제출도 횟수에 포함</p>
              <a
                className="text-link"
                href={isActive ? "/api/datasets/sample-submission" : undefined}
                aria-disabled={!isActive}
              >
                <Download size={14} />{" "}
                {isActive
                  ? "Download sample CSV"
                  : "Sample CSV · 대회 당일 공개"}
              </a>
            </aside>
          </div>
          {result && (
            <div
              role="status"
              className={
                "result " + (result.status === "success" ? "good" : "bad")
              }
            >
              <div>
                <h3>
                  {result.status === "success"
                    ? "Submission complete"
                    : "Submission rejected"}
                </h3>
                <p>
                  {result.status === "success"
                    ? "모델의 새로운 한 걸음입니다."
                    : result.error_message}
                </p>
              </div>
              {result.public_score !== null && (
                <>
                  <div>
                    <small>PUBLIC SCORE</small>
                    <strong>{result.public_score.toFixed(5)}</strong>
                  </div>
                  <div>
                    <small>PREVIOUS BEST</small>
                    <strong>{result.previous_best?.toFixed(5) ?? "—"}</strong>
                  </div>
                  {result.previous_best != null && (
                    <b>
                      {result.public_score - result.previous_best >= 0
                        ? "+"
                        : ""}
                      {(result.public_score - result.previous_best).toFixed(5)}
                    </b>
                  )}
                </>
              )}
            </div>
          )}
          <h3 className="history-title">My submissions</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>File</th>
                  <th>Public Score</th>
                  <th>Submitted at</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {history.map((s) => (
                  <tr key={s.id}>
                    <td>{s.id}</td>
                    <td>
                      <strong>{s.filename}</strong>
                      {s.error_message && (
                        <small className="row-error">{s.error_message}</small>
                      )}
                    </td>
                    <td className="score">
                      {s.public_score?.toFixed(5) ?? "—"}
                    </td>
                    <td>{date(s.created_at)}</td>
                    <td>
                      <span className={"status-pill " + s.status}>
                        {s.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!history.length && (
              <Empty
                title="아직 제출 기록이 없습니다"
                text="첫 번째 CSV 예측 파일을 제출해 보세요."
              />
            )}
          </div>
        </>
      )}
    </div>
  );
}
