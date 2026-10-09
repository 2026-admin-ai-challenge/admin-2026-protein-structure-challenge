import { Activity } from "lucide-react";
import { minutes } from "../format";
import type { Limits } from "../types";

export default function EvaluationPanel({
  limits,
}: {
  limits: Limits | undefined;
}) {
  return (
    <div className="page-content narrow">
      <div className="section-kicker">FAIR BY DESIGN</div>
      <h2 className="section-title">Every architecture counts.</h2>
      <p className="body-copy">
        샘플이 많은 구조만 잘 맞히는 모델보다, 모든 Architecture를 고르게
        이해하는 모델을 찾습니다. Primary metric은 <b>Macro F1 Score</b>입니다.
      </p>
      <div className="formula">
        <span>Macro F1</span>
        <strong>
          1 / C × ∑ F1<sub>c</sub>
        </strong>
        <small>F1 = 2 × Precision × Recall / (Precision + Recall)</small>
      </div>
      <h3>작은 클래스에도 같은 한 표</h3>
      <div className="f1-example">
        {[
          ["Class A", "0.90", "90%", "1,000 samples"],
          ["Class B", "0.75", "75%", "300 samples"],
          ["Class C", "0.65", "65%", "50 samples"],
        ].map(([name, value, width, count]) => (
          <div key={name}>
            <span>
              {name}
              <small>{count}</small>
            </span>
            <div className="bar">
              <i style={{ width }} />
            </div>
            <b>{value}</b>
          </div>
        ))}
        <p>
          예시 Macro F1 = (0.90 + 0.75 + 0.65) / 3 = <b>0.76667</b>
        </p>
      </div>
      <h3>제출한 모델은 이렇게 채점됩니다</h3>
      <div className="steps">
        <div>
          <b>1. 접수</b>
          <p>ZIP을 올리면 접수 ID를 받고 채점 대기열에 들어갑니다.</p>
        </div>
        <div>
          <b>2. 추론</b>
          <p>
            서버가 인터넷이 차단된 격리 환경에서 숨겨진 평가 입력으로 추론
            코드를 실행합니다.
            {limits
              ? ` 추론은 최대 ${minutes(limits.inference_seconds)}입니다.`
              : ""}
          </p>
        </div>
        <div>
          <b>3. 채점</b>
          <p>
            모델이 만든 예측 파일을 서버가 정답과 비교합니다. 참가자에게는 Public
            점수와 오류 사유만 보여줍니다.
          </p>
        </div>
      </div>
      <h3>Two stages. One final result.</h3>
      <div className="split-bar">
        <div>Public · 30%</div>
        <div>Private · 70%</div>
      </div>
      <div className="two-col">
        <p>
          <b>Public leaderboard</b>
          <br />
          채점이 끝나면 공개되는 참고 점수입니다. 팀의 최고 Public 점수가 실시간
          순위에 반영됩니다. 평가 데이터 중 어떤 샘플인지는 공개하지 않습니다.
        </p>
        <p>
          <b>Final leaderboard</b>
          <br />
          대회 종료 후 나머지 70%에서 계산한 Private 점수로 최종 순위를
          결정합니다. 팀에서 Public 점수가 가장 높았던 제출물 1개가 자동으로
          최종 제출물이 되며, 다른 제출물의 Private 점수가 더 높아도 바뀌지
          않습니다.
        </p>
      </div>
      <div className="info-box">
        <Activity size={22} />
        <p>
          전체 허용 클래스에 대해 F1을 평균하며, 예측이 없는 클래스의 F1은 0으로
          처리합니다. 점수는 소수점 5자리로 표시하되, 순위는 원래 정밀도로
          계산합니다. 점수가 같으면 채점 시간이 더 짧은 쪽, 채점 시간도 같으면
          제출한 ZIP 파일이 더 작은 쪽, 크기도 같으면 먼저 제출한 쪽이 앞섭니다.
          팀의 최종 제출물도 같은 기준으로 고릅니다.
          예측 파일에는 모든 평가 ID가 정확히 한 번씩 있어야 하고
          허용된 클래스만 쓸 수 있습니다.
        </p>
      </div>
    </div>
  );
}
