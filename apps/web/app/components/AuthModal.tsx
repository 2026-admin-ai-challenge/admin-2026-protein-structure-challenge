"use client";
import { useRef, useState } from "react";
import { ArrowRight, X } from "lucide-react";
import { api } from "../lib/api";
import type { User } from "../types";

// Accounts are issued by organizers. There is no sign-up form.
export default function AuthModal({
  onClose,
  onSignedIn,
}: {
  onClose: () => void;
  onSignedIn: (user: User) => void;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    password = useRef<HTMLInputElement>(null);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const form = Object.fromEntries(new FormData(event.currentTarget));
    try {
      onSignedIn(
        await api<User>("/auth/login", {
          method: "POST",
          body: JSON.stringify(form),
        }),
      );
    } catch (e) {
      setError((e as Error).message);
      // Ready for another try: typing replaces the rejected password.
      password.current?.focus();
      password.current?.select();
    } finally {
      setBusy(false);
    }
  }
  return (
    <div
      className="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <section
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="auth-title"
      >
        <button className="icon-btn close" aria-label="닫기" onClick={onClose}>
          <X size={20} />
        </button>
        <div className="section-kicker">WELCOME TO THE CHALLENGE</div>
        <h2 id="auth-title">Welcome back.</h2>
        <p>운영진에게 받은 팀 아이디와 비밀번호로 로그인하세요.</p>
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
              placeholder="배부받은 10자리 아이디"
            />
          </label>
          <label>
            비밀번호
            <input
              ref={password}
              name="password"
              type="password"
              required
              maxLength={128}
              autoComplete="current-password"
            />
          </label>
          {error && (
            <div className="alert error" role="alert">
              {error}
            </div>
          )}
          <button className="btn primary full" disabled={busy}>
            {busy ? "잠시만 기다려 주세요…" : "Log in"}
            <ArrowRight size={16} />
          </button>
        </form>
        <small className="modal-note">
          회원가입은 없습니다. 아이디를 받지 못했거나 비밀번호를 잊었다면
          운영진에게 문의하세요.
        </small>
      </section>
    </div>
  );
}
