"use client";
import { useState } from "react";
import { send } from "../../lib/api";
import { date, fileSize } from "../../format";
import type {
  AwardBoard,
  AwardKind,
  Awards,
  ClimbRow,
  EfficiencyRow,
  RecordedAward,
} from "../../types";
import Feedback from "./Feedback";
import { useAdminData } from "./useAdmin";

const TITLES: Record<AwardKind, string> = {
  efficiency: "성능 대비 파일 용량",
  climb: "첫 제출 이후 순위 상승",
};
const BOARDS: Record<AwardBoard, string> = {
  public: "Public 순위",
  final: "최종 순위",
};
const score = (n: number) => n.toFixed(5);

function summary(award: RecordedAward) {
  if (award.kind === "efficiency") {
    const row = award.detail as EfficiencyRow;
    return `효율 ${row.value.toFixed(3)} · 점수 ${score(row.score)} · ZIP ${fileSize(row.size_bytes)}`;
  }
  const row = award.detail as ClimbRow;
  return `${row.rank_then}위(${row.teams_then}팀 중) → ${row.rank}위 · ${row.value}계단 상승`;
}

export default function AwardsSection({ finalized }: { finalized: boolean }) {
  // The final board exists only once published; until then only Public can be used.
  const [choice, setChoice] = useState<AwardBoard>("final");
  const board: AwardBoard = finalized ? choice : "public";
  const { data, loading, busy, error, notice, reload, run } =
    useAdminData<Awards>("/admin/awards?board=" + board);
  const winner = (kind: AwardKind, teamId: number) => {
    const award = data?.recorded[kind];
    return award?.team_id === teamId && award.board === board;
  };
  const choose = (kind: AwardKind, teamId: number, team: string) => {
    const current = data?.recorded[kind];
    if (
      current &&
      !confirm(
        `"${TITLES[kind]}" 수상팀이 "${current.team}" 팀으로 기록되어 있습니다. "${team}" 팀으로 바꿀까요?`,
      )
    )
      return;
    run(
      () => send(`/admin/awards/${kind}`, { team_id: teamId, board }),
      `"${team}" 팀을 "${TITLES[kind]}" 수상팀으로 기록했습니다.`,
    );
  };
  const recorded = (kind: AwardKind) => {
    const award = data?.recorded[kind];
    if (!award)
      return (
        <div className="secret-box">
          <h3>기록된 수상팀 없음</h3>
          <p>아래 표에서 수상팀을 골라 "수상 기록"을 누르세요.</p>
        </div>
      );
    return (
      <div className="secret-box">
        <h3>기록된 수상팀: {award.team}</h3>
        <p>
          {BOARDS[award.board]} 기준 · {summary(award)}
        </p>
        <p>
          {date(award.recorded_at)} · {award.recorded_by} 기록. 기록 당시
          수치이며 이후 순위가 바뀌어도 그대로 남습니다.
        </p>
        <button
          className="btn secondary compact"
          disabled={busy}
          onClick={() => {
            if (
              confirm(`"${TITLES[kind]}" 수상 기록(${award.team})을 지울까요?`)
            )
              run(
                () => send(`/admin/awards/${kind}/delete`),
                "수상 기록을 지웠습니다.",
              );
          }}
        >
          기록 지우기
        </button>
      </div>
    );
  };
  const action = (kind: AwardKind, row: EfficiencyRow | ClimbRow) =>
    winner(kind, row.team_id) ? (
      <span className="status-pill succeeded">수상 기록됨</span>
    ) : (
      <button
        className="btn secondary compact"
        disabled={busy || (kind === "climb" && row.value <= 0)}
        title={
          kind === "climb" && row.value <= 0
            ? "순위가 오른 팀만 기록할 수 있습니다"
            : undefined
        }
        onClick={() => choose(kind, row.team_id, row.team)}
      >
        수상 기록
      </button>
    );
  return (
    <>
      <div className="filters">
        <label>
          계산 기준
          <select
            value={board}
            onChange={(e) => setChoice(e.target.value as AwardBoard)}
          >
            <option value="public">{BOARDS.public}</option>
            <option value="final" disabled={!finalized}>
              {BOARDS.final}
              {finalized ? "" : " (공개 후)"}
            </option>
          </select>
        </label>
        <button className="btn secondary" disabled={busy} onClick={reload}>
          새로 고침
        </button>
      </div>
      <Feedback error={error} notice={notice} loading={loading} />
      {data && board === "public" && data.frozen && (
        <div className="alert mock" role="note">
          순위가 동결되어 있어 동결 전에 마지막으로 반영된 Public 순위로
          계산합니다.
        </div>
      )}
      {data && (
        <>
          <h3>{TITLES.efficiency}</h3>
          <p className="muted">
            각 팀이 순위표에 올린 제출물의 점수와 ZIP 용량을 팀들 사이에서
            min-max로 0.01~1에 맞춘 뒤, 점수 ÷ 용량이 큰 순서입니다. 0.01은 가장
            작은 ZIP이 0으로 나뉘지 않게 하는 하한입니다. ZIP 기록이 없는 제출은
            빠집니다.
          </p>
          {recorded("efficiency")}
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>순서</th>
                  <th>팀</th>
                  <th>순위</th>
                  <th>점수</th>
                  <th>ZIP 용량</th>
                  <th>점수(0.01~1)</th>
                  <th>용량(0.01~1)</th>
                  <th>효율</th>
                  <th>조치</th>
                </tr>
              </thead>
              <tbody>
                {data.efficiency.map((row) => (
                  <tr key={row.team_id}>
                    <td>{row.place}</td>
                    <td>
                      <strong>{row.team}</strong>
                    </td>
                    <td>{row.rank}위</td>
                    <td>{score(row.score)}</td>
                    <td>
                      {fileSize(row.size_bytes)}
                      <small className="row-error muted">
                        접수 #{row.submission_id}
                      </small>
                    </td>
                    <td>{row.score_scaled.toFixed(3)}</td>
                    <td>{row.size_scaled.toFixed(3)}</td>
                    <td>
                      <strong>{row.value.toFixed(3)}</strong>
                    </td>
                    <td>{action("efficiency", row)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!data.efficiency.length && (
              <p className="muted table-note">순위표에 오른 팀이 없습니다.</p>
            )}
          </div>
          <h3>{TITLES.climb}</h3>
          <p className="muted">
            팀의 첫 점수가 나온 순간 같은 순위표에서의 순위(그때까지 점수가 있던
            팀들 중)에서 지금 순위를 뺀 값이 큰 순서입니다. 늦게 처음 제출한
            팀일수록 그때 순위가 낮게 잡힙니다. 순위가 오른 팀만 기록할 수
            있습니다.
          </p>
          {recorded("climb")}
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>순서</th>
                  <th>팀</th>
                  <th>첫 점수</th>
                  <th>그때 순위</th>
                  <th>지금 순위</th>
                  <th>상승</th>
                  <th>조치</th>
                </tr>
              </thead>
              <tbody>
                {data.climb.map((row) => (
                  <tr key={row.team_id}>
                    <td>{row.place}</td>
                    <td>
                      <strong>{row.team}</strong>
                    </td>
                    <td>
                      {score(row.score_then)}
                      <small className="row-error muted">
                        {date(row.first_at)} · 접수 #{row.first_submission_id}
                      </small>
                    </td>
                    <td>
                      {row.rank_then}위
                      <small className="row-error muted">
                        {row.teams_then}팀 중
                      </small>
                    </td>
                    <td>
                      {row.rank}위
                      <small className="row-error muted">
                        {score(row.score)}
                      </small>
                    </td>
                    <td>
                      <strong>
                        {row.value > 0
                          ? `▲ ${row.value}`
                          : row.value < 0
                            ? `▼ ${-row.value}`
                            : "—"}
                      </strong>
                    </td>
                    <td>{action("climb", row)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!data.climb.length && (
              <p className="muted table-note">순위표에 오른 팀이 없습니다.</p>
            )}
          </div>
        </>
      )}
    </>
  );
}
