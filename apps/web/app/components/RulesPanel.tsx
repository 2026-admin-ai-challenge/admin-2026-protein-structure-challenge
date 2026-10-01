import {
  FileText,
  Download,
  ShieldCheck,
  ExternalLink,
  Activity,
} from "lucide-react";
import type { Competition } from "../types";
const fmt = (n?: number) => (n === undefined ? "—" : n.toLocaleString());
export default function RulesPanel() {
  return (
    <div className="page-content narrow">
      <div className="section-kicker">BUILD WITH INTEGRITY</div>
      <h2 className="section-title">좋은 경쟁을 위한 약속.</h2>
      <p className="body-copy">
        이 대회는 서열과 제공된 3D 구조로 Architecture를 분류하는 AI 모델의 성능을 비교합니다. 공개
        데이터에서 파생된 만큼 정답 조회 금지 규칙이 특히 중요합니다.
      </p>
      {[
        [
          "01",
          "자유로운 모델, 공정한 학습",
          "외부 공개 pretrained model, ESM·ProtBERT·ProtT5 등 Protein Language Model을 사용할 수 있습니다. 사용한 모델과 데이터 출처를 명시하세요.",
        ],
        [
          "02",
          "정답 직접 조회 금지",
          "CATH/PDB나 서열·구조 유사도 검색을 이용하여 시험 샘플의 label을 조회하거나, 원본 domain ID를 복원해 정답을 검색하는 행위를 금지합니다. 사람이 직접 label을 작성하는 것도 금지합니다.",
        ],
        [
          "03",
          "하루 최대 제출 횟수",
          "기본 5회이며 운영자 설정을 따릅니다. UTC 00:00에 초기화됩니다. 검증 실패 제출도 횟수에 포함됩니다. 파일 크기는 최대 2 MB입니다.",
        ],
        [
          "04",
          "한 사람, 한 계정, 한 팀",
          "MVP는 개인 팀으로 운영됩니다. 팀 이름은 중복할 수 없습니다. 계정 공유, 다른 팀과 예측 파일·비공개 코드 공유, 다중 계정으로 제출 제한을 우회하는 행위를 금지합니다.",
        ],
        [
          "05",
          "재현 가능한 연구",
          "대회 종료 후 학습·추론 코드, 환경, 시드, 사용 데이터와 pretrained checkpoint를 제출하도록 요구할 수 있습니다. 재현이 불가능하거나 규칙 위반이 확인되면 실격될 수 있습니다.",
        ],
      ].map(([n, title, desc]) => (
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
