"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../lib/api";

// Loads one admin resource and exposes a guarded action runner, so every section
// shows loading, error and success states the same way.
export function useAdminData<T>(path: string) {
  const [data, setData] = useState<T | null>(null),
    [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const reload = useCallback(async () => {
    try {
      setData(await api<T>(path));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [path]);
  useEffect(() => {
    setLoading(true);
    reload();
  }, [reload]);
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
