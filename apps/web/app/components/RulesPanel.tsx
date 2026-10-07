import { megabytes, minutes } from "../format";
import type { Limits } from "../types";

// Rules still being decided by organizers are stated as "to be announced", never guessed.
export default function RulesPanel({ limits }: { limits: Limits | undefined }) {
  const rules = [
    [
      "01",
      "제공된 학습 데이터로만",
      "운영진이 제공한 학습 데이터로 모델을 학습합니다. 평가 데이터는 참가자에게 제공하지 않으며, 서버가 제출된 모델로 추론만 실행합니다. 외부 사전학습 가중치·외부 데이터의 허용 범위는 추후 공지합니다.",
    ],
    [
      "02",
      "정답 직접 조회 금지",
      "CATH/PDB나 서열·구조 유사도 검색으로 평가 샘플의 label을 조회하거나, 원본 domain ID를 복원해 정답을 찾는 행위를 금지합니다. 사람이 직접 label을 작성하는 것도 금지합니다.",
    ],
    [
      "03",
      "모델 ZIP 제출",
      limits
        ? `추론 코드와 학습된 모델을 ZIP 하나로 제출합니다. ZIP은 최대 ${megabytes(limits.zip_bytes)}, 추론은 최대 ${minutes(limits.inference_seconds)}입니다. requirements.txt에 적은 패키지는 추론 전에 설치합니다. 추론 중에는 학습과 인터넷 접속을 할 수 없습니다.`
        : "추론 코드와 학습된 모델을 ZIP 하나로 제출합니다. requirements.txt에 적은 패키지는 추론 전에 설치합니다. 추론 중에는 학습과 인터넷 접속을 할 수 없습니다.",
    ],
    [
      "04",
      "팀당 제출 횟수",
      limits
        ? `대회 전체 기간에 팀당 최대 ${limits.team_submissions}회 제출할 수 있습니다. 날짜가 바뀌어도 초기화되지 않습니다. ZIP 규격 위반과 서버 오류를 제외한 모든 실패는 1회 차감됩니다.`
        : "대회 전체 기간의 팀당 제출 횟수가 정해져 있으며 날짜가 바뀌어도 초기화되지 않습니다.",
    ],
    [
      "05",
      "운영진이 발급한 팀 계정",
      "참가자는 운영진이 발급한 아이디로만 로그인합니다. 계정을 다른 팀과 공유하거나, 다른 팀과 모델·비공개 코드를 공유하거나, 여러 계정으로 제출 제한을 우회하는 행위를 금지합니다.",
    ],
    [
      "06",
      "재현 가능한 결과",
      "수상 후보는 학습 코드와 재현에 필요한 설정·시드·환경을 제출합니다. 제공 데이터만으로 결과를 재현할 수 없거나 규칙 위반이 확인되면 실격될 수 있습니다.",
    ],
  ];
  return (
    <div className="page-content narrow">
      <div className="section-kicker">BUILD WITH INTEGRITY</div>
      <h2 className="section-title">좋은 경쟁을 위한 약속.</h2>
      <p className="body-copy">
        이 대회는 서열과 제공된 3D 구조로 Architecture를 분류하는 AI 모델의
        성능을 비교합니다. 공개 데이터에서 파생된 만큼 정답 조회 금지 규칙이
        특히 중요합니다.
      </p>
      {rules.map(([n, title, desc]) => (
        <article className="rule" key={n}>
          <span>{n}</span>
          <div>
            <h3>{title}</h3>
            <p>{desc}</p>
          </div>
        </article>
      ))}
    </div>
  );
}
