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
export default function AdminPanel({
  user,
  setAuth,
  settings,
  adminAction,
  busy,
  adminUsers,
  adminSubs,
}: {
  user: User | null;
  setAuth: (value: "login" | "register" | null) => void;
  settings: Settings | undefined;
  adminAction: (path: string, body?: object, method?: string) => Promise<void>;
  busy: boolean;
  adminUsers: (User & { banned: boolean; submissions: number })[];
  adminSubs: Submission[];
}) {
  return (
    <div className="page-content">
      <div className="section-kicker">ORGANIZER WORKSPACE</div>
      <h2 className="section-title">Competition control.</h2>
      {user?.role !== "ADMIN" ? (
        <div className="sign-in-card">
          <ShieldCheck size={30} />
          <h3>관리자 권한이 필요합니다</h3>
          <button className="btn primary" onClick={() => setAuth("login")}>
            Log in
          </button>
        </div>
      ) : (
        <>
          <form
            className="admin-form"
            key={JSON.stringify(settings)}
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              adminAction(
                "/admin/competition",
                {
                  daily_limit: Number(f.get("daily_limit")),
                  start_time: f.get("start_time")
                    ? new Date(String(f.get("start_time"))).toISOString()
                    : null,
                  end_time: f.get("end_time")
                    ? new Date(String(f.get("end_time"))).toISOString()
                    : null,
                },
                "PATCH",
              );
            }}
          >
            <label>
              일일 제출 제한
              <input
                name="daily_limit"
                type="number"
                min="1"
                max="100"
                defaultValue={settings?.daily_limit}
              />
            </label>
            <label>
              시작 시간 (기기 현지 시간)
              <input
                name="start_time"
                type="datetime-local"
                defaultValue={localTime(settings?.start_time)}
              />
            </label>
            <label>
              종료 시간 (기기 현지 시간)
              <input
                name="end_time"
                type="datetime-local"
                defaultValue={localTime(settings?.end_time)}
              />
            </label>
            <button
              className="btn primary"
              disabled={busy || settings?.finalized}
            >
              Save settings
            </button>
          </form>
          <div className="admin-actions">
            <button
              className="btn secondary"
              disabled={busy || settings?.finalized}
              onClick={() =>
                adminAction(
                  "/admin/competition",
                  { is_open: !settings?.is_open },
                  "PATCH",
                )
              }
            >
              {settings?.is_open ? "Close competition" : "Open competition"}
            </button>
            <button
              className="btn secondary"
              disabled={busy || settings?.finalized}
              onClick={() =>
                adminAction(
                  "/admin/competition",
                  { frozen: !settings?.frozen },
                  "PATCH",
                )
              }
            >
              {settings?.frozen ? "Unfreeze leaderboard" : "Freeze leaderboard"}
            </button>
            <button
              className="btn secondary"
              disabled={busy || settings?.finalized || settings?.frozen}
              onClick={() => adminAction("/admin/leaderboard/recalculate")}
            >
              Recalculate scores
            </button>
            <button
              className="btn primary"
              disabled={busy || settings?.is_open || settings?.finalized}
              onClick={() => {
                if (
                  confirm(
                    "최종 순위를 공개하면 대회를 다시 열 수 없습니다. Private 점수 기반 최종 순위를 공개할까요?",
                  )
                )
                  adminAction("/admin/leaderboard/finalize");
              }}
            >
              Publish final leaderboard
            </button>
          </div>
          <h3>Participants</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>User</th>
                  <th>Team</th>
                  <th>Submissions</th>
                  <th>Account</th>
                </tr>
              </thead>
              <tbody>
                {adminUsers.map((u) => (
                  <tr key={u.id}>
                    <td>
                      {u.display_name}
                      <small className="row-error muted">{u.email}</small>
                    </td>
                    <td>{u.team_name}</td>
                    <td>{u.submissions}</td>
                    <td>
                      {u.role === "ADMIN" ? (
                        "ADMIN"
                      ) : (
                        <button
                          className="btn secondary compact"
                          disabled={busy || settings?.finalized}
                          onClick={() =>
                            adminAction(
                              "/admin/users/" + u.id,
                              { banned: !u.banned },
                              "PATCH",
                            )
                          }
                        >
                          {u.banned ? "Unban" : "Ban"}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <h3 className="history-title">All submissions · Organizer only</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Team / User</th>
                  <th>File</th>
                  <th>Public</th>
                  <th>Private</th>
                  <th>Status / Time</th>
                </tr>
              </thead>
              <tbody>
                {adminSubs.map((s) => (
                  <tr key={s.id}>
                    <td>
                      {s.team}
                      <small className="row-error muted">{s.user}</small>
                    </td>
                    <td>
                      {s.filename}
                      <small className="row-error">{s.error_message}</small>
                    </td>
                    <td>{s.public_score?.toFixed(5) ?? "—"}</td>
                    <td>{s.private_score?.toFixed(5) ?? "—"}</td>
                    <td>
                      {s.status}
                      <small className="row-error muted">
                        {date(s.created_at)}
                      </small>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
