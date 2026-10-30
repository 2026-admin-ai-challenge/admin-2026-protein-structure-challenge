"use client";
import { useState } from "react";
import { ArrowRight, X } from "lucide-react";
import { send } from "../lib/api";
import type { User } from "../types";

// A team replaces the password organizers issued. Organizers change theirs on the server.
export default function PasswordModal({
  user,
  onClose,
  onChanged,
}: {
  user: User;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const next = String(form.get("new_password"));
    if (next !== form.get("confirm_password")) {
      setError("새 비밀번호와 확인이 서로 다릅니다.");
      return;
    }
    // One account per team, so a change signs the rest of the team out. The notice above
    // says so, but the click that does it is worth confirming.
    if (
      !confirm(
        `${user.team_name} 팀의 비밀번호를 바꿉니다. 지금 로그인해 있는 팀원은 모두 로그아웃되고, 새 비밀번호를 알려 주기 전에는 다시 들어오지 못합니다. 바꿀까요?`,
      )
    )
      return;
    setBusy(true);
    setError("");
    try {
      await send("/auth/password", {
        current_password: form.get("current_password"),
        new_password: next,
      });
      onChanged();
    } catch (e) {
      setError((e as Error).message);
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
        aria-labelledby="password-title"
      >
        <button className="icon-btn close" aria-label="닫기" onClick={onClose}>
          <X size={20} />
        </button>
        <div className="section-kicker">TEAM ACCOUNT</div>
        <h2 id="password-title">비밀번호 변경</h2>
        <p>
          {user.team_name} 팀의 비밀번호를 바꿉니다. 바꾸면 이 창을 뺀 모든
          곳에서 로그아웃되니, 팀원에게 새 비밀번호를 알려 주세요.
        </p>
        <form onSubmit={submit}>
          {/* Lets password managers file the new password under the team name. */}
          <input
            name="username"
            autoComplete="username"
            value={user.team_name}
            readOnly
            hidden
          />
          <label>
            현재 비밀번호
            <input
              autoFocus
              name="current_password"
              type="password"
              required
              maxLength={128}
              autoComplete="current-password"
            />
          </label>
          <label>
            새 비밀번호
            <input
              name="new_password"
              type="password"
              required
              minLength={8}
              maxLength={128}
              autoComplete="new-password"
              placeholder="8자 이상"
            />
          </label>
          <label>
            새 비밀번호 확인
            <input
              name="confirm_password"
              type="password"
              required
              minLength={8}
              maxLength={128}
              autoComplete="new-password"
            />
          </label>
          {error && (
            <div className="alert error" role="alert">
              {error}
            </div>
          )}
          <button className="btn primary full" disabled={busy}>
            {busy ? "잠시만 기다려 주세요…" : "비밀번호 변경"}
            <ArrowRight size={16} />
          </button>
        </form>
        <small className="modal-note">
          비밀번호를 잊었다면 운영진에게 재설정을 요청하세요.
        </small>
      </section>
    </div>
  );
}
