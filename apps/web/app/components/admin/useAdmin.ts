"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../lib/api";

// Loads one admin resource and exposes a guarded action runner, so every section
// shows loading, error and success states the same way.
export function useAdminData<T>(path: string) {
  const [data, setData] = useState<T | null>(null),
    [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  // A response that arrives after the path changed (a filter or board switched while it
  // was loading) is dropped, so it cannot replace the newer one.
  const latest = useRef(path);
  const reload = useCallback(async () => {
    try {
      const result = await api<T>(path);
      if (latest.current !== path) return;
      setData(result);
      setError("");
    } catch (e) {
      if (latest.current === path) setError((e as Error).message);
    } finally {
      if (latest.current === path) setLoading(false);
    }
  }, [path]);
  useEffect(() => {
    latest.current = path;
    setLoading(true);
    reload();
  }, [path, reload]);
  const run = useCallback(
    async <R,>(action: () => Promise<R>, done?: string) => {
      setBusy(true);
      setError("");
      setNotice("");
      try {
        const result = await action();
        await reload();
        if (done) setNotice(done);
        return result;
      } catch (e) {
        setError((e as Error).message);
        return undefined;
      } finally {
        setBusy(false);
      }
    },
    [reload],
  );
  return { data, loading, busy, error, notice, reload, run };
}
