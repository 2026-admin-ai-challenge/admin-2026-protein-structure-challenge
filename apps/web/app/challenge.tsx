"use client";
import ProjectFooter from "./components/ProjectFooter";
import OverviewPanel from "./components/OverviewPanel";
import SubmissionPanel from "./components/SubmissionPanel";
import AdminPanel from "./components/AdminPanel";
import AuthModal from "./components/AuthModal";
import LeaderboardPanel from "./components/LeaderboardPanel";
import Protein from "./components/protein";
import DataPanel from "./components/DataPanel";
import EvaluationPanel from "./components/EvaluationPanel";
import RulesPanel from "./components/RulesPanel";
import { useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  ArrowRight,
  Upload,
  Check,
  ChevronRight,
  ChevronDown,
  Sun,
  Moon,
  Menu,
  X,
  Layers3,
  Activity,
  Database,
  Clock,
  Users,
  ShieldCheck,
  LogOut,
  Plus,
} from "lucide-react";
import { api } from "./lib/api";
import { count } from "./format";
import type { Entry, User, Competition } from "./types";
const tabs = [
  "Overview",
  "Data",
  "Evaluation",
  "Rules",
  "Leaderboard",
  "Submit",
];
export default function Challenge({
  initialTab = "Overview",
}: {
  initialTab?: string;
}) {
  const [tab, setTab] = useState(initialTab),
    [data, setData] = useState<Competition | null>(null),
    [user, setUser] = useState<User | null>(null),
    [entries, setEntries] = useState<Entry[]>([]),
    [boardVersion, setBoardVersion] = useState(0),
    [auth, setAuth] = useState(false),
    [dark, setDark] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [mobile, setMobile] = useState(false);
  const content = useRef<HTMLElement>(null);
  const settings = data?.settings;
  async function refresh() {
    try {
      setData(await api<Competition>("/competition"));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  // Public top-of-board preview shown on the Overview tab.
  async function refreshBoard() {
    try {
      setEntries(
        (await api<{ entries: Entry[] }>("/leaderboard?board=public")).entries,
      );
    } catch (e) {
      setError((e as Error).message);
    }
    setBoardVersion((v) => v + 1);
  }
  function refreshAll() {
    refresh();
    refreshBoard();
  }
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!document.hidden) refresh();
    }, 30000);
    const recheck = () => {
      if (!document.hidden) refresh();
    };
    document.addEventListener("visibilitychange", recheck);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", recheck);
    };
  }, []);
  useEffect(() => {
    refreshAll();
    api<User>("/auth/me")
      .then(setUser)
      .catch(() => {});
    const saved = localStorage.getItem("admin-theme") === "dark";
    setDark(saved);
    document.documentElement.dataset.theme = saved ? "dark" : "light";
  }, []);
  function navigate(v: string) {
    setTab(v);
    setMobile(false);
    setNotice("");
    if (v === "Overview") refreshBoard();
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
  const open = data?.submission_open ?? false;
  const status = settings?.finalized
    ? "대회 종료 · 최종 순위 공개"
    : open
      ? "제출 진행 중"
      : "대회 준비 중";
  const stat = data?.dataset?.stats;
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
                  {user.team_name}
                  <ChevronDown size={13} />
                </button>
                <button
                  className="icon-btn"
                  aria-label="로그아웃"
                  onClick={async () => {
                    await api("/auth/logout", { method: "POST" });
                    setUser(null);
                  }}
                >
                  <LogOut size={16} />
                </button>
              </>
            ) : (
              <button className="login" onClick={() => setAuth(true)}>
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
                onClick={() => (user ? navigate("Submit") : setAuth(true))}
              >
                {user ? "Submit a model" : "Team log in"}{" "}
                <ArrowUpRight size={17} />
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
              운영진 발급 팀 계정으로 참가
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
            [Users, "TEAMS", count(data?.teams), "Curious minds"],
            [
              Upload,
              "SCORED MODELS",
              count(data?.submissions),
              "Ideas put to the test",
            ],
            [
              Clock,
              "DEADLINE",
              settings?.end_time
                ? new Date(settings.end_time).toLocaleDateString("ko-KR")
                : "Coming soon",
              settings?.end_time ? "제출 마감" : "일정은 추후 안내",
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
                : open
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
              limits={data?.limits}
              entries={entries}
              navigate={navigate}
            />
          )}
          {tab === "Data" && <DataPanel data={data} />}
          {tab === "Evaluation" && <EvaluationPanel limits={data?.limits} />}
          {tab === "Rules" && <RulesPanel limits={data?.limits} />}
          {tab === "Leaderboard" && (
            <LeaderboardPanel key={boardVersion} competition={data} />
          )}
          {tab === "Submit" && (
            <SubmissionPanel
              user={user}
              competition={data}
              onLogin={() => setAuth(true)}
              onScored={refreshAll}
            />
          )}
          {tab === "Admin" && (
            <AdminPanel
              user={user}
              settings={settings}
              onLogin={() => setAuth(true)}
              onChanged={refreshAll}
            />
          )}
        </section>
      </main>
      <ProjectFooter />
      {auth && (
        <AuthModal
          onClose={() => setAuth(false)}
          onSignedIn={(signedIn) => {
            setUser(signedIn);
            setAuth(false);
            setNotice(
              signedIn.role === "ADMIN"
                ? "관리자로 로그인했습니다."
                : `${signedIn.team_name} 팀으로 로그인했습니다.`,
            );
          }}
        />
      )}
    </>
  );
}
