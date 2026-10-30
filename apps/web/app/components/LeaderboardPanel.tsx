"use client";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  Lock,
  RotateCcw,
  Trophy,
} from "lucide-react";
import { date, duration } from "../format";
import { useLeaderboard } from "../lib/useLeaderboard";
import type { Competition, Entry } from "../types";
import Empty from "./Empty";
import { MockNotice } from "./StatusPill";

// What happened to one team since the list before: places climbed (negative: fell),
// first score on the board, best score went up.
type Change = { climb: number; fresh: boolean; better: boolean };

// How long the ▲/▼/NEW mark stays next to the rank. The fade in globals.css
// (.rank-move) runs over the same 6 s.
const MARK_MS = 6000;

const calm = () =>
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function changesBetween(before: Entry[], after: Entry[]) {
  const old = new Map(before.map((e) => [e.team, e]));
  const found: Record<string, Change> = {};
  for (const e of after) {
    // A team still waiting for its first score gets no mark.
    if (e.rank === null || e.score === null) continue;
    const was = old.get(e.team);
    if (!was || was.rank === null || was.score === null)
      found[e.team] = { climb: 0, fresh: true, better: true };
    else if (was.rank !== e.rank || was.score !== e.score)
      found[e.team] = {
        climb: was.rank - e.rank,
        fresh: false,
        better: e.score > was.score,
      };
  }
  return found;
}

// Counts up from the old score to the new one instead of jumping. A page the browser
// does not draw gets no frames, so a timer makes sure the new score lands anyway.
function Score({ value, animate }: { value: number; animate: boolean }) {
  const [shown, setShown] = useState(value);
  const current = useRef(value);
  useEffect(() => {
    const from = current.current;
    if (from === value) return;
    let frame = 0;
    const land = () => {
      cancelAnimationFrame(frame);
      current.current = value;
      setShown(value);
    };
    if (!animate || calm()) {
      land();
      return;
    }
    const start = performance.now();
    const step = (now: number) => {
      const t = Math.max(now - start, 0) / 900;
      if (t >= 1) return land();
      current.current = from + (value - from) * (1 - (1 - t) ** 3);
      setShown(current.current);
      frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    const timer = window.setTimeout(land, 1000);
    return () => {
      cancelAnimationFrame(frame);
      window.clearTimeout(timer);
    };
  }, [value]);
  return <>{shown.toFixed(5)}</>;
}

/** `entries` is null until the first answer. The first list the table gets is shown as
 *  is; after that, each new list slides the rows from where they were to their new
 *  place, lights up teams whose best score rose and marks how far they moved. With
 *  `live` off (frozen ranking) a new list just replaces the old one, without motion. */
export function LeaderboardTable({
  entries,
  board = "public",
  live = true,
}: {
  entries: Entry[] | null;
  board?: string;
  live?: boolean;
}) {
  const shown = entries ?? [];
  const [marks, setMarks] = useState<{
    id: number;
    teams: Record<string, Change>;
  } | null>(null);
  const table = useRef<HTMLTableElement>(null),
    rows = useRef(new Map<string, HTMLTableRowElement>()),
    // Where each team's row was laid out last, and for which list. offsetTop leaves out
    // running transforms, so a row caught mid-slide still reports its real place.
    places = useRef<Map<string, number> | null>(null),
    placedFor = useRef<Entry[] | null>(null);
  function measure() {
    const found = new Map<string, number>();
    rows.current.forEach((row, team) => found.set(team, row.offsetTop));
    return found;
  }
  useLayoutEffect(() => {
    if (!entries) return;
    const before = places.current,
      old = placedFor.current;
    places.current = measure();
    placedFor.current = entries;
    if (!before || !old || old === entries || !live) return;
    const changes = changesBetween(old, entries);
    if (Object.keys(changes).length)
      setMarks((m) => ({ id: (m?.id ?? 0) + 1, teams: changes }));
    const still = calm(),
      glow = getComputedStyle(document.documentElement)
        .getPropertyValue("--board-glow")
        .trim();
    places.current.forEach((top, team) => {
      const row = rows.current.get(team)!,
        from = before.get(team);
      if (changes[team]?.better && glow)
        row.animate(
          [
            { backgroundColor: glow },
            { backgroundColor: glow, offset: 0.35 },
            { backgroundColor: "transparent" },
          ],
          { duration: 3500, easing: "ease-out" },
        );
      if (still) return;
      if (from === undefined)
        row.animate(
          [
            { opacity: 0, transform: "translateY(14px)" },
            { opacity: 1, transform: "none" },
          ],
          { duration: 500, easing: "ease-out" },
        );
      else if (from !== top) {
        // A climbing row passes over the ones it overtakes.
        const layer = from > top ? 2 : 1;
        row.animate(
          [
            { transform: `translateY(${from - top}px)`, zIndex: layer },
            { transform: "none", zIndex: layer },
          ],
          { duration: 900, easing: "cubic-bezier(.2, .8, .2, 1)" },
        );
      }
    });
  });
  useEffect(() => {
    if (!marks) return;
    const timer = window.setTimeout(() => setMarks(null), MARK_MS);
    return () => window.clearTimeout(timer);
  }, [marks]);
  // A wider or narrower window moves rows without a new list; remember the new places
  // so the next update does not slide rows that did not change.
  useEffect(() => {
    const observer = new ResizeObserver(() => {
      if (placedFor.current) places.current = measure();
    });
    if (table.current) observer.observe(table.current);
    return () => observer.disconnect();
  }, []);
  return (
    <div className="table-wrap board-table">
      <table ref={table}>
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
          {shown.map((e) => {
            const mark = marks?.teams[e.team];
            return (
              <tr
                key={e.team}
                className={e.rank === null ? "unranked" : undefined}
                ref={(row) => {
                  if (row) rows.current.set(e.team, row);
                  else rows.current.delete(e.team);
                }}
              >
                <td>
                  <span
                    className={e.rank === null ? "rank" : "rank r" + e.rank}
                  >
                    {e.rank !== null && e.rank <= 3 ? (
                      <Trophy size={16} />
                    ) : null}
                    {e.rank === null ? "—" : String(e.rank).padStart(2, "0")}
                    <span className="rank-move">
                      {mark && (mark.fresh || mark.climb !== 0) && (
                        <span
                          key={marks?.id}
                          className={
                            mark.fresh ? "new" : mark.climb > 0 ? "up" : "down"
                          }
                          aria-label={
                            mark.fresh
                              ? "새로 진입"
                              : `${Math.abs(mark.climb)}계단 ${mark.climb > 0 ? "상승" : "하락"}`
                          }
                        >
                          {mark.fresh ? (
                            "NEW"
                          ) : (
                            <>
                              {mark.climb > 0 ? (
                                <ArrowUp size={11} />
                              ) : (
                                <ArrowDown size={11} />
                              )}
                              {Math.abs(mark.climb)}
                            </>
                          )}
                        </span>
                      )}
                    </span>
                  </span>
                </td>
                <td>
                  <span className="avatar">
                    {e.team.slice(0, 2).toUpperCase()}
                  </span>
                  <strong>{e.team}</strong>
                </td>
                <td className="score">
                  {/* No submission scored yet: shown as 0 and counts up from there. */}
                  <Score value={e.score ?? 0} animate={live} />
                </td>
                <td>{duration(e.grading_seconds)}</td>
                <td>{e.submissions}</td>
                <td>{e.last_submission ? date(e.last_submission) : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {entries?.length === 0 && (
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
  const [board, setBoard] = useState("public");
  const settings = competition?.settings;
  // A frozen ranking (also after finalize) does not move: no checks, no animation.
  const live = !settings?.frozen;
  const { data, loading, error, reload } = useLeaderboard(board, live);
  return (
    <div className="page-content">
      <div className="section-heading">
        <div>
          <div className="section-kicker">LEARN FROM THE LEADERS</div>
          <h2 className="section-title">The leaderboard.</h2>
        </div>
        <button className="btn secondary" onClick={reload} disabled={loading}>
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
        {live && (
          <span className="board-live">
            <span className="live-dot" /> 실시간 반영
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
      {/* A new key on a board switch: the other board's rows must not slide. */}
      <LeaderboardTable
        key={data?.board}
        entries={data?.entries ?? null}
        board={data?.board ?? board}
        live={live}
      />
    </div>
  );
}
