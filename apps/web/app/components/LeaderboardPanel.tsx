"use client";
import { useEffect, useState } from "react";
import { ChevronDown, Lock, RotateCcw, Trophy } from "lucide-react";
import { api } from "../lib/api";
import { date, duration } from "../format";
import type { Competition, Entry } from "../types";
import Empty from "./Empty";
import { MockNotice } from "./StatusPill";

export function LeaderboardTable({
  entries,
  board = "public",
  preview = false,
}: {
  entries: Entry[];
  board?: string;
  preview?: boolean;
}) {
  return (
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
            <th>채점 시간</th>
            <th>Scored submissions</th>
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
                <span className="avatar">{e.team.slice(0, 2).toUpperCase()}</span>
                <strong>{e.team}</strong>
              </td>
              <td className="score">{e.score.toFixed(5)}</td>
              <td>{duration(e.grading_seconds)}</td>
              <td>{e.submissions}</td>
              <td>{date(e.last_submission)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {entries.length === 0 && (
        <Empty
          title="첫 번째 도전의 주인공이 되어 보세요"
          text="제출이 채점되면 이곳에 팀 순위가 표시됩니다."
        />
      )}
    </div>
  );
}

export default function LeaderboardPanel({
  competition,
}: {
  competition: Competition | null;
}) {
  const [board, setBoard] = useState("public"),
    [entries, setEntries] = useState<Entry[]>([]),
    [loading, setLoading] = useState(true),
    [error, setError] = useState("");
  const settings = competition?.settings;
  async function load(which = board) {
    setLoading(true);
    try {
      setEntries(
        (await api<{ entries: Entry[] }>("/leaderboard?board=" + which)).entries,
      );
      setError("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    load(board);
  }, [board]);
  return (
    <div className="page-content">
      <div className="section-heading">
        <div>
          <div className="section-kicker">LEARN FROM THE LEADERS</div>
          <h2 className="section-title">The leaderboard.</h2>
        </div>
        <button className="btn secondary" onClick={() => load()} disabled={loading}>
          <RotateCcw size={14} /> {loading ? "Loading…" : "Refresh"}
        </button>
      </div>
      {competition?.evaluator === "mock" && <MockNotice />}
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
        {board === "final"
          ? "Private 점수 기준 최종 순위 · Macro F1"
          : "팀별 최고 Public 점수 기준 · Macro F1"}
        {settings?.frozen && board === "public"
          ? " · 순위가 동결되어 있습니다."
          : ""}
      </p>
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
      <LeaderboardTable entries={entries} board={board} />
    </div>
  );
}
