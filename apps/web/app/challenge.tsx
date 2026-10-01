"use client";
import ProjectFooter from "./components/ProjectFooter";
import OverviewPanel from "./components/OverviewPanel";
import SubmissionPanel from "./components/SubmissionPanel";
import AdminPanel from "./components/AdminPanel";
import Empty from "./components/Empty";
import { date } from "./format";
import Protein from "./components/protein";
import DataPanel from "./components/DataPanel";
import EvaluationPanel from "./components/EvaluationPanel";
import RulesPanel from "./components/RulesPanel";
import { useEffect, useRef, useState } from "react";
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
import type {
  Entry,
  User,
  Submission,
  Settings,
  Meta,
  Competition,
} from "./types";
const tabs = [
  "Overview",
  "Data",
  "Evaluation",
  "Rules",
  "Leaderboard",
  "Submit",
];
async function api(path: string, options: RequestInit = {}) {
  const response = await fetch("/api" + path, {
    ...options,
    headers: {
      "X-Requested-With": "ADMIN-Challenge",
      ...(options.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...options.headers,
    },
  });
  const body = await response.json();
  if (!response.ok)
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : "요청 정보를 확인해 주세요.",
    );
  return body;
}
const fmt = (n?: number) => (n === undefined ? "—" : n.toLocaleString());
export default function Challenge({
  initialTab = "Overview",
}: {
  initialTab?: string;
}) {
  const [tab, setTab] = useState(initialTab),
    [data, setData] = useState<Competition | null>(null),
    [user, setUser] = useState<User | null>(null),
    [entries, setEntries] = useState<Entry[]>([]),
    [board, setBoard] = useState("public"),
    [history, setHistory] = useState<Submission[]>([]),
    [used, setUsed] = useState(0),
    [auth, setAuth] = useState<null | "login" | "register">(null),
    [dark, setDark] = useState(false),
    [error, setError] = useState(""),
    [authError, setAuthError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false),
    [file, setFile] = useState<File | null>(null),
    [result, setResult] = useState<Submission | null>(null),
    [drag, setDrag] = useState(false),
    [mobile, setMobile] = useState(false),
    [adminUsers, setAdminUsers] = useState<
      (User & { banned: boolean; submissions: number })[]
    >([]),
    [adminSubs, setAdminSubs] = useState<Submission[]>([]);
  const input = useRef<HTMLInputElement>(null),
    content = useRef<HTMLElement>(null);
  const settings = data?.settings;
  async function refresh() {
    try {
      setData(await api("/competition"));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    const timer = window.setInterval(refresh, 30000);
    const recheck = () => {
      if (!document.hidden) refresh();
    };
    document.addEventListener("visibilitychange", recheck);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", recheck);
    };
  }, []);
  async function refreshBoard() {
    try {
      setEntries((await api("/leaderboard?board=" + board)).entries);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function refreshHistory() {
    try {
      const h = await api("/submissions/me");
      setHistory(h.entries);
      setUsed(h.used_today);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function refreshAdmin() {
    try {
      setAdminUsers(await api("/admin/users"));
      setAdminSubs(await api("/admin/submissions"));
    } catch (e) {
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    refresh();
    api("/auth/me")
      .then(setUser)
      .catch(() => {});
    const saved = localStorage.getItem("admin-theme") === "dark";
    setDark(saved);
    document.documentElement.dataset.theme = saved ? "dark" : "light";
  }, []);
  useEffect(() => {
    refreshBoard();
  }, [board]);
  useEffect(() => {
    if (user) {
      refreshHistory();
      if (user.role === "ADMIN") refreshAdmin();
    }
  }, [user]);
  function navigate(v: string) {
    setTab(v);
    setMobile(false);
    setNotice("");
    if (v === "Leaderboard") refreshBoard();
    if (v === "Submit" && user) refreshHistory();
    setTimeout(
      () =>
        content.current?.scrollIntoView({ behavior: "smooth", block: "start" }),
      20,
    );
  }
  function theme() {
    setDark(!dark);
    document.documentElement.dataset.theme = !dark ? "dark" : "light";
    localStorage.setItem("admin-theme", !dark ? "dark" : "light");
  }
  async function authenticate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setAuthError("");
    const form = Object.fromEntries(new FormData(event.currentTarget));
    try {
      setUser(
        await api("/auth/" + auth, {
          method: "POST",
          body: JSON.stringify(form),
        }),
      );
      setAuth(null);
      setNotice("환영합니다. 데이터 다운로드부터 시작해 보세요.");
    } catch (e) {
      setAuthError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function upload() {
    if (!file) return;
    setBusy(true);
    setError("");
    setResult(null);
    const form = new FormData();
    form.set("file", file);
    try {
      setResult(await api("/submissions", { method: "POST", body: form }));
      await refreshHistory();
      await refreshBoard();
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function adminAction(path: string, body?: object, method = "POST") {
    setBusy(true);
    setError("");
    try {
      await api(path, {
        method,
        ...(body ? { body: JSON.stringify(body) } : {}),
      });
      await refresh();
      await refreshBoard();
      await refreshAdmin();
      setNotice("설정을 저장했습니다.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const isActive = data?.dataset_available ?? false;
  const status = settings?.finalized
    ? "대회 종료 · 최종 순위 공개"
    : isActive
      ? "참가 접수 및 제출 진행 중"
      : "대회 준비 중";
  const stat = data?.dataset?.stats;
  const table = (preview = false) => (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Rank</th>
            <th>Team</th>
            <th>
              {board === "final" ? "Private" : "Public"} Score{" "}
              <ChevronDown size={12} />
            </th>
            <th>Submissions</th>
            <th>Last submission</th>
          </tr>
        </thead>
        <tbody>
          {(preview ? entries.slice(0, 5) : entries).map((e) => (
            <tr key={e.rank}>
              <td>
                <span className={"rank r" + e.rank}>
                  {e.rank <= 3 ? <Trophy size={16} /> : null}
                  {String(e.rank).padStart(2, "0")}
                </span>
              </td>
              <td>
                <span className="avatar">
                  {e.team.slice(0, 2).toUpperCase()}
                </span>
                <strong>{e.team}</strong>
              </td>
              <td className="score">{e.score.toFixed(5)}</td>
              <td>{e.submissions}</td>
              <td>{date(e.last_submission)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {entries.length === 0 && (
        <Empty
          title="첫 번째 도전의 주인공이 되어 보세요"
          text="제출이 채점되면 이곳에 실제 팀 순위가 표시됩니다."
        />
      )}
    </div>
  );
  return (
    <>
      <header className="header">
        <div className="header-inner">
          <a href="/" className="brand" aria-label="ADMIN Challenge 홈">
            <img src="/admin-logo.png" alt="ADMIN" />
            <span className="brand-divider" />
            <span>AI CHALLENGE</span>
          </a>
          <nav className={mobile ? "nav expanded" : "nav"}>
            <button
              onClick={() => navigate("Overview")}
              className={tab === "Overview" ? "nav-active" : ""}
            >
              Competition
            </button>
            <button onClick={() => navigate("Leaderboard")}>Leaderboard</button>
            <button onClick={() => navigate("Submit")}>Submit</button>
          </nav>
          <div className="header-actions">
            <button
              className="icon-btn theme"
              onClick={theme}
              aria-label="테마 변경"
            >
              {dark ? <Sun size={18} /> : <Moon size={18} />}
            </button>
            {user ? (
              <>
                <button
                  className="user-pill"
                  onClick={() =>
                    navigate(user.role === "ADMIN" ? "Admin" : "Submit")
                  }
                >
                  {user.display_name}
                  <ChevronDown size={13} />
                </button>
                <button
                  className="icon-btn"
                  aria-label="로그아웃"
                  onClick={async () => {
                    await api("/auth/logout", { method: "POST" });
                    setUser(null);
                    setHistory([]);
                    setUsed(0);
                    setAdminSubs([]);
                    setAdminUsers([]);
                    setResult(null);
                  }}
                >
                  <LogOut size={16} />
                </button>
              </>
            ) : (
              <button
                className="login"
                onClick={() => {
                  setAuth("login");
                  setAuthError("");
                }}
              >
                Log in <ArrowUpRight size={15} />
              </button>
            )}
            <button
              className="icon-btn mobile-toggle"
              aria-label="메뉴"
              onClick={() => setMobile(!mobile)}
            >
              <Menu size={20} />
            </button>
          </div>
        </div>
      </header>
      <main>
        <div className="breadcrumb container">
          <span>Competitions</span>
          <ChevronRight size={12} />
          <span>2026</span>
          <ChevronRight size={12} />
          <strong>Protein Structure Challenge</strong>
        </div>
        <section className="hero container">
          <div className="hero-copy">
            <div className="eyebrow">
              <span className="live-dot" />
              ADMIN AI CHALLENGE 2026
              <span className="edition">01 / BIO AI</span>
            </div>
            <h1>
              Small structures.
              <br />
              Big <span>discoveries.</span>
            </h1>
            <h2>Protein Structure Classification</h2>
            <p className="hero-question">
              Can AI recognize architecture
              <br />
              from protein structures?
            </p>
            <p className="hero-korean">
              서열과 3D 구조에서 단백질의 Architecture를 분류하세요.
              <br />
              충남대학교 AI 동아리 ADMIN과 함께하는 단백질 AI 챌린지.
            </p>
            <div className="hero-cta">
              <button
                className="btn primary"
                onClick={() =>
                  user ? navigate("Submit") : setAuth("register")
                }
              >
                Join Competition <ArrowUpRight size={17} />
              </button>
              <button
                className="btn secondary"
                onClick={() => navigate("Leaderboard")}
              >
                View Leaderboard <ArrowRight size={17} />
              </button>
            </div>
            <div className="hero-note">
              <span className="live-dot" />
              {status}
              <span className="small-divider" />
              Open to curious minds
            </div>
          </div>
          <div className="hero-art">
            <div className="art-grid" />
            <Protein />
            <div className="art-caption">
              <span>FIG. 01</span> FROM STRUCTURE TO DISCOVERY{" "}
              <Plus size={13} />
            </div>
            <span className="art-corner">+ </span>
          </div>
        </section>
        <section className="stats container">
          {[
            [Layers3, "TASK", "Multiclass", "Classification"],
            [Database, "DATASET", "CATH S40", "Protein domains"],
            [Activity, "METRIC", "Macro F1", "Higher is better"],
            [Users, "PARTICIPANTS", fmt(data?.participants), "Curious minds"],
            [
              Upload,
              "SUBMISSIONS",
              fmt(data?.submissions),
              "Ideas put to the test",
            ],
            [
              Clock,
              "DEADLINE",
              settings?.end_time
                ? new Date(settings.end_time).toLocaleDateString("ko-KR")
                : "Coming soon",
              "일정은 추후 안내",
            ],
          ].map(([Icon, label, value, sub], i) => {
            const I = Icon as typeof Layers3;
            return (
              <div className="stat" key={i}>
                <div className="stat-label">
                  <I size={15} />
                  {label as string}
                </div>
                <strong>{value as string}</strong>
                <small>{sub as string}</small>
              </div>
            );
          })}
        </section>
        <section className="competition container" ref={content}>
          <div className="tab-bar" role="tablist" aria-label="대회 메뉴">
            {tabs.map((t) => (
              <button
                key={t}
                role="tab"
                aria-selected={tab === t}
                className={tab === t ? "active" : ""}
                onClick={() => navigate(t)}
              >
                {t}
                {t === "Submit" && <ArrowUpRight size={14} />}
              </button>
            ))}
            {user?.role === "ADMIN" && (
              <button
                role="tab"
                aria-selected={tab === "Admin"}
                className={tab === "Admin" ? "active" : ""}
                onClick={() => navigate("Admin")}
              >
                <ShieldCheck size={15} /> Admin
              </button>
            )}
            <span className="tab-status">
              <span className="live-dot" />
              {settings?.finalized
                ? "Final results"
                : isActive
                  ? "Competition open"
                  : "Preparing challenge"}
            </span>
          </div>
          {error && (
            <div className="alert error" role="alert">
              {error}
              <button
                className="icon-btn"
                onClick={() => setError("")}
                aria-label="닫기"
              >
                <X size={16} />
              </button>
            </div>
          )}
          {notice && (
            <div className="alert success" role="status">
              <Check size={16} />
              {notice}
            </div>
          )}
          {tab === "Overview" && (
            <OverviewPanel
              datasetAvailable={data?.dataset_available ?? false}
              stat={stat}
              settings={settings}
              navigate={navigate}
              table={table}
            />
          )}
          {tab === "Data" && <DataPanel data={data} />}
          {tab === "Evaluation" && <EvaluationPanel />}
          {tab === "Rules" && <RulesPanel />}
          {tab === "Leaderboard" && (
            <div className="page-content">
              <div className="section-heading">
                <div>
                  <div className="section-kicker">LEARN FROM THE LEADERS</div>
                  <h2 className="section-title">The leaderboard.</h2>
                </div>
                <button className="btn secondary" onClick={refreshBoard}>
                  <RotateCcw size={14} /> Refresh
                </button>
              </div>
              <div className="board-switch">
                <button
                  className={board === "public" ? "selected" : ""}
                  onClick={() => setBoard("public")}
                >
                  Public Leaderboard
                </button>
                {settings?.finalized ? (
                  <button
                    className={board === "final" ? "selected" : ""}
                    onClick={() => setBoard("final")}
                  >
                    Final Leaderboard
                  </button>
                ) : (
                  <span>
                    <Lock size={13} /> Final · 대회 종료 후 공개
                  </span>
                )}
              </div>
              <p className="body-copy">
                팀별 최고 점수 기준 · Macro F1 · 동점 시 먼저 달성한 팀 우선
                {settings?.frozen ? " · 순위가 동결되어 있습니다." : ""}
              </p>
              {table()}
            </div>
          )}
          {tab === "Submit" && (
            <SubmissionPanel
              user={user}
              setAuth={setAuth}
              drag={drag}
              setDrag={setDrag}
              file={file}
              setFile={setFile}
              setResult={setResult}
              input={input}
              busy={busy}
              isActive={isActive}
              used={used}
              settings={settings}
              upload={upload}
              result={result}
              history={history}
            />
          )}
          {tab === "Admin" && (
            <AdminPanel
              user={user}
              setAuth={setAuth}
              settings={settings}
              adminAction={adminAction}
              busy={busy}
              adminUsers={adminUsers}
              adminSubs={adminSubs}
            />
          )}
        </section>
      </main>
      <ProjectFooter />
      {auth && (
        <div
          className="modal-backdrop"
          onClick={(e) => {
            if (e.target === e.currentTarget) setAuth(null);
          }}
        >
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="auth-title"
          >
            <button
              className="icon-btn close"
              aria-label="닫기"
              onClick={() => setAuth(null)}
            >
              <X size={20} />
            </button>
            <div className="section-kicker">WELCOME TO THE CHALLENGE</div>
            <h2 id="auth-title">
              {auth === "register"
                ? "Your discovery starts here."
                : "Welcome back."}
            </h2>
            <p>함께 배우고, 단백질 구조의 가능성을 탐구하세요.</p>
            <form onSubmit={authenticate}>
              <label>
                Email
                <input
                  autoFocus
                  name="email"
                  type="email"
                  required
                  autoComplete="email"
                  placeholder="you@cnu.ac.kr"
                />
              </label>
              {auth === "register" && (
                <>
                  <label>
                    Display name
                    <input
                      name="display_name"
                      required
                      minLength={2}
                      maxLength={60}
                      autoComplete="nickname"
                    />
                  </label>
                  <label>
                    Team name
                    <input
                      name="team_name"
                      required
                      minLength={2}
                      maxLength={60}
                      placeholder="당신의 개인 팀 이름"
                    />
                  </label>
                </>
              )}
              <label>
                Password
                <input
                  name="password"
                  type="password"
                  required
                  minLength={10}
                  maxLength={128}
                  autoComplete={
                    auth === "login" ? "current-password" : "new-password"
                  }
                  placeholder="10자 이상"
                />
              </label>
              {authError && (
                <div className="alert error" role="alert">
                  {authError}
                </div>
              )}
              <button className="btn primary full" disabled={busy}>
                {busy
                  ? "잠시만 기다려 주세요…"
                  : auth === "register"
                    ? "Create account"
                    : "Log in"}
                <ArrowRight size={16} />
              </button>
            </form>
            <button
              className="auth-switch"
              onClick={() => {
                setAuth(auth === "login" ? "register" : "login");
                setAuthError("");
              }}
            >
              {auth === "login"
                ? "처음 오셨나요? 회원가입"
                : "이미 계정이 있나요? 로그인"}
            </button>
            <small>
              충남대학교 이메일을 권장하며, 다른 이메일도 사용할 수 있습니다.
            </small>
          </section>
        </div>
      )}
    </>
  );
}
