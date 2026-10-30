import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Entry } from "../types";

// How often an open leaderboard asks for new scores. A hidden tab does not ask, and the
// next check is planned only after the previous answer arrived, so a slow server never
// gets a pile of requests from one page.
export const LIVE_INTERVAL = 10000;

export type LoadedBoard = { board: string; entries: Entry[] };

const same = (a: Entry[], b: Entry[]) =>
  JSON.stringify(a) === JSON.stringify(b);

/** One leaderboard, kept up to date while the page shows it. `data` is null until the
 *  first answer and names the board it belongs to, so a table can tell a board switch
 *  from a score update. An unchanged answer keeps the same object (no re-render).
 *  While `live` is false (frozen ranking) the board is read once and not checked again. */
export function useLeaderboard(board: string, live: boolean) {
  const [data, setData] = useState<LoadedBoard | null>(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState("");
  // Only the newest request may write: an older answer (other board, earlier poll) is dropped.
  const latest = useRef(0);
  async function load(quiet = false) {
    const ticket = ++latest.current;
    if (!quiet) setLoading(true);
    try {
      const { entries } = await api<{ entries: Entry[] }>(
        "/leaderboard?board=" + board,
      );
      if (ticket !== latest.current) return;
      setData((old) =>
        old && old.board === board && same(old.entries, entries)
          ? old
          : { board, entries },
      );
      setError("");
    } catch (e) {
      if (ticket === latest.current) setError((e as Error).message);
    } finally {
      if (ticket === latest.current) setLoading(false);
    }
  }
  useEffect(() => {
    let stopped = false,
      timer = 0;
    const next = () => {
      if (!stopped && live) timer = window.setTimeout(poll, LIVE_INTERVAL);
    };
    async function poll() {
      if (!document.hidden) await load(true);
      next();
    }
    const wake = () => {
      if (live && !document.hidden) load(true);
    };
    load().then(next);
    document.addEventListener("visibilitychange", wake);
    return () => {
      stopped = true;
      latest.current++;
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", wake);
    };
  }, [board, live]);
  return { data, loading, error, reload: () => load() };
}
