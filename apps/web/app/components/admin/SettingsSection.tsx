"use client";
import { useEffect } from "react";
import { send } from "../../lib/api";
import { date, localTime } from "../../format";
import type { Overview } from "../../types";
import Feedback from "./Feedback";
import { useAdminData } from "./useAdmin";

// Refresh only while the tab is visible: a forgotten background tab should not
// keep sending requests (tunnel services meter them).
const REFRESH_MS = 10000;

export default function SettingsSection({ onChanged }: { onChanged: () => void }) {
  const { data, loading, busy, error, notice, reload, run } =
    useAdminData<Overview>("/admin/overview");
  // Queue and worker state change on their own, so keep this view current.
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!document.hidden) reload();
    }, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [reload]);
  const settings = data?.settings;
  const change = (body: object, done: string) =>
    run(async () => {
      await send("/admin/competition", body, "PATCH");
      onChanged();
    }, done);
  const alive = data?.workers.filter((w) => w.alive) ?? [];
  return (
    <>
      <Feedback error={error} notice={notice} loading={loading} />
      {data && settings && (
        <>
          <div className="stat-cards">
            <div>
              <small>대기 중</small>
              <strong>{data.queue.queued}</strong>
              <span>
                {data.oldest_queued_at
                  ? "가장 오래된 접수 " + date(data.oldest_queued_at)
                  : "대기열이 비어 있습니다"}
              </span>
            </div>
            <div>
              <small>채점 중</small>
              <strong>{data.queue.running}</strong>
              <span>완료 {data.queue.succeeded}건</span>
            </div>
            <div>
              <small>실패</small>
              <strong>{data.queue.failed}</strong>
              <span>
                {Object.entries(data.failures)
                  .map(([code, n]) => `${code} ${n}`)
                  .join(" · ") || "실패 없음"}
              </span>
            </div>
            <div className={alive.some((w) => w.ready) ? "" : "warn"}>
              <small>채점 작업자</small>
              <strong>{alive.length}</strong>
              <span>
                {alive.length === 0
                  ? "응답하는 작업자가 없습니다. 제출은 대기열에 쌓입니다."
                  : alive.map((w) => w.detail).join(" · ")}
              </span>
            </div>
          </div>
          {data.evaluator === "mock" && (
            <div className="alert mock" role="note">
              평가기: mock. 점수는 가짜입니다. 실제 대회는 EVALUATOR=docker로
              실행하세요.
            </div>
          )}
          <form
            className="admin-form"
            key={JSON.stringify(settings)}
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              const time = (name: string) =>
                f.get(name) ? new Date(String(f.get(name))).toISOString() : null;
              change(
                {
                  team_submission_limit: Number(f.get("team_submission_limit")),
                  start_time: time("start_time"),
                  end_time: time("end_time"),
                  count_failed: f.get("count_failed") === "true",
                  final_selection: f.get("final_selection"),
                },
                "설정을 저장했습니다.",
              );
            }}
          >
            <label>
              팀당 제출 횟수 (대회 전체)
              <input
                name="team_submission_limit"
                type="number"
                min="1"
                max="1000"
                defaultValue={settings.team_submission_limit}
              />
            </label>
            <label>
              시작 시간 (기기 현지 시간)
              <input
                name="start_time"
                type="datetime-local"
                defaultValue={localTime(settings.start_time)}
              />
            </label>
            <label>
              종료 시간 (기기 현지 시간)
              <input
                name="end_time"
                type="datetime-local"
                defaultValue={localTime(settings.end_time)}
              />
            </label>
            <label>
              실패한 제출의 횟수 차감
              <select
                name="count_failed"
                defaultValue={String(settings.count_failed)}
              >
                <option value="true">차감 (접수 시점 기준)</option>
                <option value="false">차감하지 않음</option>
              </select>
            </label>
            <label>
              최종 순위에 쓸 제출물
              <select name="final_selection" defaultValue={settings.final_selection}>
                <option value="best_public">
                  Public 최고 제출물의 Private 점수
                </option>
                <option value="best_private">Private 최고 제출물</option>
              </select>
            </label>
            <button className="btn primary" disabled={busy || settings.finalized}>
              Save settings
            </button>
          </form>
          <p className="muted">
            서버 장애로 실패한 제출은 설정과 무관하게 차감되지 않습니다. ZIP{" "}
            {Math.round(data.limits.zip_bytes / (1024 * 1024))} MB, 추론{" "}
            {data.limits.inference_seconds}초 제한은 서버 환경변수로 정합니다.
          </p>
          <div className="admin-actions">
            <button
              className="btn secondary"
              disabled={busy || settings.finalized}
              onClick={() =>
                change(
                  { is_open: !settings.is_open },
                  settings.is_open ? "대회를 닫았습니다." : "대회를 열었습니다.",
                )
              }
            >
              {settings.is_open ? "Close competition" : "Open competition"}
            </button>
            <button
              className="btn secondary"
              disabled={busy || settings.finalized}
              onClick={() =>
                change(
                  { frozen: !settings.frozen },
                  settings.frozen ? "순위 동결을 해제했습니다." : "순위를 동결했습니다.",
                )
              }
            >
              {settings.frozen ? "Unfreeze leaderboard" : "Freeze leaderboard"}
            </button>
            <button
              className="btn secondary"
              disabled={busy || settings.finalized || settings.frozen}
              onClick={() =>
                run(async () => {
                  await send("/admin/leaderboard/recalculate");
                  onChanged();
                }, "저장된 점수로 순위를 다시 만들었습니다.")
              }
            >
              Rebuild leaderboard
            </button>
            <button
              className="btn primary"
              disabled={busy || settings.is_open || settings.finalized}
              onClick={() => {
                if (
                  confirm(
                    "최종 순위를 공개하면 대회를 다시 열 수 없습니다. Private 점수 기반 최종 순위를 공개할까요?",
                  )
                )
                  run(async () => {
                    await send("/admin/leaderboard/finalize");
                    onChanged();
                  }, "최종 순위를 공개했습니다.");
              }}
            >
              Publish final leaderboard
            </button>
          </div>
          <h3>채점 작업자</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Worker</th>
                  <th>Evaluator</th>
                  <th>State</th>
                  <th>Current submission</th>
                  <th>Last seen</th>
                </tr>
              </thead>
              <tbody>
                {data.workers.map((w) => (
                  <tr key={w.id}>
                    <td>{w.id}</td>
                    <td>{w.evaluator}</td>
                    <td>
                      <span
                        className={
                          "status-pill " +
                          (w.alive && w.ready ? "succeeded" : "failed")
                        }
                      >
                        {!w.alive ? "응답 없음" : w.ready ? "정상" : "준비 안 됨"}
                      </span>
                      <small className="row-error muted">{w.detail}</small>
                    </td>
                    <td>{w.submission_id ? "#" + w.submission_id : "—"}</td>
                    <td>{date(w.last_seen)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!data.workers.length && (
              <p className="muted table-note">
                아직 보고한 작업자가 없습니다. worker 서비스가 실행 중인지
                확인하세요.
              </p>
            )}
          </div>
        </>
      )}
    </>
  );
}
