"use client";
import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { send } from "../../lib/api";
import { fileSize } from "../../format";
import type { AdminTeam, DeletedTeam, IssuedAccount } from "../../types";
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
  // No username is sent, so the server picks the account's internal ID. The team signs
  // in with its name; accounts of one team are told apart by password.
  const issue = (teamId: number) =>
    run(async () => {
      setIssued(await send<IssuedAccount>("/admin/users", { team_id: teamId }));
      onChanged();
    });
  // The organizer types the team name, which the server checks too.
  const remove = (team: AdminTeam) => {
    const typed = prompt(
      `팀 "${team.name}"을 영구 삭제합니다. 계정 ${team.users.length}개, 제출 ${team.submissions}건, ` +
        `보관 중인 ZIP ${team.files}개와 순위 기록이 함께 지워지며 되돌릴 수 없습니다.\n` +
        "계정 시트(accounts/participants.csv)에 남아 있으면 다음 sync_accounts 때 다시 만들어지니 시트에서도 지우세요.\n\n" +
        "확인을 위해 팀 이름을 입력하세요(대소문자·띄어쓰기 구분 없음).",
    );
    if (!typed?.trim()) return;
    run(
      async () => {
        const deleted = await send<DeletedTeam>(`/admin/teams/${team.id}/delete`, {
          confirm: typed,
        });
        if (issued?.team_id === team.id) setIssued(null);
        onChanged();
        return deleted;
      },
      (deleted) =>
        deleted.not_deleted.length
          ? `팀 "${deleted.name}"을 삭제했습니다. ZIP ${deleted.not_deleted.length}개는 디스크에서 지우지 못했습니다. 제출·대기열의 파일 정합성 검사로 확인하세요.`
          : `팀 "${deleted.name}"과 계정 ${deleted.accounts.length}개, 제출 ${deleted.submissions}건을 삭제했습니다.`,
    );
  };
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
            <dt>아이디 (팀 이름)</dt>
            <dd>{issued.team_name}</dd>
            <dt>임시 비밀번호</dt>
            <dd>{issued.temporary_password}</dd>
          </dl>
          <button
            className="btn secondary compact"
            onClick={() =>
              navigator.clipboard?.writeText(
                `아이디(팀 이름): ${issued.team_name}\n비밀번호: ${issued.temporary_password}`,
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
                      const name = prompt(
                        "새 팀 이름 (참가자가 로그인할 때 쓰는 이름도 바뀝니다)",
                        team.name,
                      )?.trim();
                      if (name && name !== team.name)
                        run(async () => {
                          const renamed = await send<{ name: string }>(
                            "/admin/teams/" + team.id,
                            { name },
                            "PATCH",
                          );
                          // An open password box shows the sign-in name; keep it current.
                          setIssued((open) =>
                            open?.team_id === team.id
                              ? { ...open, team_name: renamed.name }
                              : open,
                          );
                          onChanged();
                        }, "팀 이름을 바꿨습니다. 이제 새 이름으로 로그인합니다.");
                    }}
                  >
                    이름 변경
                  </button>
                  {!team.users.some((u) => u.role === "ADMIN") && (
                    <button
                      className="text-link danger"
                      disabled={busy || finalized}
                      title={finalized ? "최종 순위 공개 후에는 삭제할 수 없습니다." : undefined}
                      onClick={() => remove(team)}
                    >
                      팀 삭제
                    </button>
                  )}
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
                  <small className="row-error muted">
                    접수 {team.submissions}건 · ZIP {team.files}개{" "}
                    {fileSize(team.storage_bytes)}
                  </small>
                </td>
                <td className="score">{team.best_public?.toFixed(5) ?? "—"}</td>
                <td>
                  <button
                    className="btn secondary compact"
                    disabled={busy}
                    onClick={() => issue(team.id)}
                  >
                    {team.users.length ? "계정 추가 발급" : "계정 발급"}
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
        모든 계정은 팀 이름을 아이디로, 배부된 비밀번호로 로그인합니다(대소문자·띄어쓰기
        구분 없음). 운영진은 관리자 아이디로도 로그인할 수 있습니다. 계정 옆의 코드는 내부 구분용이며 로그인에는 쓰지 않습니다. 한
        팀에 계정이 여럿이면 비밀번호로 구분합니다. 여러 계정을 한꺼번에 만들거나
        고칠 때는 서버의 accounts/participants.csv를 수정한 뒤 sync_accounts 명령을
        실행하세요. 비밀번호는 해시로만 저장됩니다.
      </p>
    </>
  );
}
