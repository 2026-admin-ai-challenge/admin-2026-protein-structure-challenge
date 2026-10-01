import {
  FileText,
  Download,
  ShieldCheck,
  ExternalLink,
  Activity,
} from "lucide-react";
import type { Competition } from "../types";
const fmt = (n?: number) => (n === undefined ? "—" : n.toLocaleString());
export default function EvaluationPanel() {
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
      <h3>Two stages. One final result.</h3>
      <div className="split-bar">
        <div>Public · 30%</div>
        <div>Private · 70%</div>
      </div>
      <div className="two-col">
        <p>
          <b>Public leaderboard</b>
          <br />
          제출 즉시 공개되는 참고 점수입니다. 시험 데이터 중 어떤 샘플인지
          공개하지 않습니다.
        </p>
        <p>
          <b>Final leaderboard</b>
          <br />
          대회 종료 후 나머지 70%에서 계산한 점수로 최종 순위를 결정합니다.
        </p>
      </div>
      <div className="info-box">
        <Activity size={22} />
        <p>
          전체 허용 클래스에 대해 F1을 평균하며, 예측이 없는 클래스의 F1은 0으로
          처리합니다. 점수는 소수점 5자리로 표시하되, 순위는 원래 정밀도로
          계산합니다. 동점은 먼저 달성한 제출이 우선합니다. 최종 순위는 팀의
          가장 높은 Private 점수를 사용합니다.
        </p>
      </div>
    </div>
  );
}
