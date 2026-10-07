"use client";
import { useState } from "react";
import { ArrowRight, X } from "lucide-react";
import { api } from "../lib/api";

// Before launch the site is open to admins only. After an admin signs in here, the
// next load passes the proxy (proxy.ts) and shows the site.
export default function AdminLogin({ onClose }: { onClose: () => void }) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const form = Object.fromEntries(new FormData(event.currentTarget));
    try {
      const user = await api<{ role: string }>("/auth/login", {
        method: "POST",
        body: JSON.stringify(form),
      });
      if (user.role === "ADMIN") return window.location.reload();
      // A participant session is of no use before launch.
      await api("/auth/logout", { method: "POST" });
      setError("대회 시작 전에는 운영진(관리자) 계정만 들어갈 수 있습니다.");
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy(false);
  }
  return (
    <div
      className="soon-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
    >
      <section
        className="soon-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="soon-login-title"
      >
        <button
          type="button"
          className="soon-close"
          aria-label="닫기"
          onClick={onClose}
        >
          <X size={18} />
        </button>
        <div className="soon-kicker">ORGANIZERS ONLY</div>
        <h2 id="soon-login-title">운영진 로그인</h2>
        <p>대회 시작 전에는 관리자 계정으로 로그인한 운영진만 사이트를 볼 수 있습니다.</p>
        <form onSubmit={submit}>
          <label>
            아이디
            <input
              autoFocus
              name="username"
              required
              maxLength={64}
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
            />
          </label>
          <label>
            비밀번호
            <input
              name="password"
              type="password"
              required
              maxLength={128}
              autoComplete="current-password"
            />
          </label>
          {error && (
            <div className="soon-error" role="alert">
              {error}
            </div>
          )}
          <button className="soon-submit" disabled={busy}>
            {busy ? "확인 중…" : "로그인"} <ArrowRight size={16} />
          </button>
        </form>
      </section>
    </div>
  );
}
