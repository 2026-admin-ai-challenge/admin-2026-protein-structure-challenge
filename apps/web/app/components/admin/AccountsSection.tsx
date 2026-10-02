"use client";
import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { send } from "../../lib/api";
import type { AdminTeam, IssuedAccount } from "../../types";
import Feedback from "./Feedback";
import { useAdminData } from "./useAdmin";

export default function AccountsSection({
  finalized,
  onChanged,
}: {
  finalized: boolean;
  onChanged: () => void;
}) {
  const { data, loading, busy, error, notice, run } =
    useAdminData<AdminTeam[]>("/admin/teams");
  // Shown once: the server keeps only the hash and cannot display it again.
  const [issued, setIssued] = useState<IssuedAccount | null>(null);
  const box = useRef<HTMLDivElement>(null);
  // The box renders above a long table; bring it to the organizer who clicked far below.
  useEffect(() => {
    if (issued) box.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [issued]);
  // No username is sent, so the server picks a random 10-character ID.
  const issue = (teamId: number) =>
    run(async () => {
      setIssued(await send<IssuedAccount>("/admin/users", { team_id: teamId }));
      onChanged();
    });
  return (
    <>
      <Feedback error={error} notice={notice} loading={loading} />
      {issued && (
        <div className="secret-box" role="status" ref={box}>
          <button
            className="icon-btn close"
            aria-label="닫기"
            onClick={() => setIssued(null)}
          >
            <X size={16} />
          </button>
          <h3>임시 비밀번호 — 지금만 표시됩니다</h3>
          <p>
            이 창을 닫으면 다시 볼 수 없습니다. 팀에 전달한 뒤 닫으세요. 잊었다면
            재설정으로 새 비밀번호를 발급합니다.
          </p>
          <dl>
            <dt>아이디</dt>
            <dd>{issued.username}</dd>
            <dt>임시 비밀번호</dt>
            <dd>{issued.temporary_password}</dd>
          </dl>
          <button
            className="btn secondary compact"
            onClick={() =>
              navigator.clipboard?.writeText(
                `아이디: ${issued.username}\n비밀번호: ${issued.temporary_password}`,
              )
            }
          >
            복사
          </button>
        </div>
      )}
      <form
        className="inline-form"
        onSubmit={(e) => {
          e.preventDefault();
          const form = e.currentTarget;
          const name = String(new FormData(form).get("name") ?? "").trim();
          if (!name) return;
          run(async () => {
            await send("/admin/teams", { name });
            form.reset();
            onChanged();
          }, `팀 "${name}"을 만들었습니다. 이어서 계정을 발급하세요.`);
        }}
      >
        <label>
          새 팀 이름
          <input name="name" required minLength={2} maxLength={60} />
        </label>
        <button className="btn primary" disabled={busy}>
          팀 만들기
        </button>
      </form>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Team</th>
              <th>Accounts</th>
              <th>제출 횟수</th>
              <th>Best Public</th>
              <th>계정 발급</th>
            </tr>
          </thead>
          <tbody>
            {(data ?? []).map((team) => (
              <tr key={team.id}>
                <td>
                  <strong>{team.name}</strong>
                  <button
                    className="text-link"
                    disabled={busy}
                    onClick={() => {
                      const name = prompt("새 팀 이름", team.name)?.trim();
                      if (name && name !== team.name)
                        run(async () => {
                          await send("/admin/teams/" + team.id, { name }, "PATCH");
                          onChanged();
                        }, "팀 이름을 바꿨습니다.");
                    }}
                  >
                    이름 변경
                  </button>
                </td>
                <td>
                  {team.users.map((u) => (
                    <div className="account-row" key={u.id}>
                      <code>{u.username}</code>
                      {u.role === "ADMIN" ? (
                        <span className="status-pill succeeded">ADMIN</span>
                      ) : (
                        <>
                          {u.banned && (
                            <span className="status-pill failed">차단됨</span>
                          )}
                          <button
                            className="btn secondary compact"
                            disabled={busy}
                            onClick={() => {
                              if (
                                confirm(
                                  `${u.username}의 비밀번호를 재설정할까요? 기존 비밀번호와 로그인 세션은 즉시 무효가 됩니다.`,
                                )
                              )
                                run(async () =>
                                  setIssued(
                                    await send<IssuedAccount>(
                                      `/admin/users/${u.id}/reset-password`,
                                    ),
                                  ),
                                );
                            }}
                          >
                            비밀번호 재설정
                          </button>
                          <button
                            className="btn secondary compact"
                            disabled={busy || finalized}
                            onClick={() =>
                              run(
                                async () => {
                                  await send(
                                    "/admin/users/" + u.id,
                                    { banned: !u.banned },
                                    "PATCH",
                                  );
                                  onChanged();
                                },
                                u.banned ? "차단을 해제했습니다." : "계정을 차단했습니다.",
                              )
                            }
                          >
                            {u.banned ? "차단 해제" : "차단"}
                          </button>
                        </>
                      )}
                    </div>
                  ))}
                  {!team.users.length && <span className="muted">계정 없음</span>}
                </td>
                <td>
                  {team.used} / {team.limit}
                  <small className="row-error muted">접수 {team.submissions}건</small>
                </td>
                <td className="score">{team.best_public?.toFixed(5) ?? "—"}</td>
                <td>
                  <button
                    className="btn secondary compact"
                    disabled={busy}
                    onClick={() => issue(team.id)}
                  >
                    랜덤 아이디로 발급
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {data && !data.length && (
          <p className="muted table-note">
            팀이 없습니다. 위에서 팀을 만들거나 서버에서 계정 시트를
            불러오세요.
          </p>
        )}
      </div>
      <p className="muted">
        여러 계정을 한꺼번에 만들거나 고칠 때는 서버의 accounts/participants.csv를
        수정한 뒤 sync_accounts 명령을 실행하세요. 비밀번호는 해시로만
        저장됩니다.
      </p>
    </>
  );
}
