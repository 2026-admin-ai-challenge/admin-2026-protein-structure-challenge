import {
  FileText,
  Download,
  ShieldCheck,
  ExternalLink,
  Activity,
  Lock,
} from "lucide-react";
import { count } from "../format";
import type { Competition } from "../types";

// Only training material is listed. Evaluation input is never distributed:
// submitted models are run on it by the scoring server.
const FILES = [
  ["train.csv", "train", "학습용 관측 서열과 Architecture 정답"],
  [
    "train_features.csv",
    "train-features",
    "학습용 서열 조성·구조 통계 31개 특징",
  ],
  [
    "train_structures.zip",
    "train-structures",
    "선택 활용: 학습용 Cα 좌표·마스크·잔기 위치 (NPZ)",
  ],
  [
    "validation_split.csv",
    "validation-split",
    "학습 데이터의 H-group 검증 분할",
  ],
  [
    "example_io.zip",
    "example",
    "추론 입력과 같은 형식의 작은 예제 입력·출력",
  ],
];

export default function DataPanel({ data }: { data: Competition | null }) {
  const stat = data?.dataset?.stats;
  if (!data?.dataset_available)
    return (
      <div className="page-content narrow">
        <div className="section-kicker">DATA RELEASE</div>
        <h2 className="section-title">학습 데이터는 대회 시작과 함께 공개됩니다.</h2>
        <div className="info-box">
          <Lock size={24} />
          <div>
            <h3>모두 같은 시간에, 같은 출발선에서.</h3>
            <p>
              학습용 서열·특징·3D 좌표는 대회 시작부터 종료 시각까지만
              다운로드할 수 있습니다. 평가 데이터는 제공하지 않습니다. 제출한
              모델을 서버가 평가 데이터로 실행합니다.
            </p>
            <p>
              {data?.settings.start_time
                ? `공개 예정: ${new Date(data.settings.start_time).toLocaleString("ko-KR")}`
                : "대회 일정이 확정되면 공개 시간을 안내합니다."}
            </p>
            {data?.settings.end_time && (
              <p>
                다운로드 종료:{" "}
                {new Date(data.settings.end_time).toLocaleString("ko-KR")}
              </p>
            )}
          </div>
        </div>
        <div className="info-box">
          <FileText size={24} />
          <div>
            <h3>베이스라인은 지금 준비할 수 있어요.</h3>
            <p>
              기본 Logistic Regression 코드와 환경 설치 안내를 먼저 받으세요.
              실제 데이터는 포함하지 않습니다. 학습 실행은 대회 시작 후 데이터를
              받은 뒤 가능합니다.
            </p>
            <a className="btn primary" href="/api/resources/baseline">
              <Download size={15} /> 베이스라인 코드 미리 받기
            </a>
          </div>
        </div>
        <button className="btn secondary" disabled>
          <Lock size={15} /> 다운로드 잠김
        </button>
      </div>
    );
  return (
    <div className="page-content">
      <div className="section-kicker">THE DATA BEHIND THE DISCOVERY</div>
      <h2 className="section-title">CATH Protein Domains</h2>
      <p className="body-copy">
        CATH-Plus v4.4 · S40 non-redundant domains. 실제 실험 구조에 기반한
        서열·Cα 좌표 데이터입니다. 여기서 받는 것은 <b>학습 데이터</b>입니다.
        평가 데이터와 정답, 원본 domain ID는 제공하지 않습니다.
      </p>
      <div className="data-summary">
        <div>
          <small>Training samples</small>
          <strong>{count(stat?.train)}</strong>
        </div>
        <div>
          <small>Architectures</small>
          <strong>{count(stat?.classes)}</strong>
        </div>
        <div>
          <small>Hidden evaluation set</small>
          <strong>
            {count(stat?.test)}
            <small> 서버에서만 사용</small>
          </strong>
        </div>
        <div>
          <small>Length</small>
          <strong>
            40–1,200 <small>aa</small>
          </strong>
        </div>
      </div>
      <div className="info-box">
        <Activity size={24} />
        <div>
          <h3>처음이라면 베이스라인부터.</h3>
          <p>
            Logistic Regression 베이스라인 코드와 실행 방법을 받으세요. 31개
            기본 특징만으로 CPU에서 학습할 수 있습니다. 3D 좌표는 선택해서
            활용하는 자료이며, 쓰지 않는 모델도 채점됩니다.
          </p>
          <a className="btn primary" href="/api/resources/baseline">
            <Download size={15} /> 베이스라인 코드 받기
          </a>
        </div>
      </div>
      <div className="download-grid">
        {FILES.map(([name, path, desc]) => {
          const info = data.dataset?.files[name];
          return (
            <article className="download-card" key={name}>
              <FileText size={26} />
              <h3>{name}</h3>
              <p>{desc}</p>
              <div className="file-info">
                <span>
                  {name.endsWith(".zip")
                    ? "ZIP archive"
                    : `${count(info?.rows)} rows`}
                </span>
                <span>
                  {info
                    ? (info.bytes / (1024 * 1024)).toFixed(2) + " MB"
                    : "준비 중"}
                </span>
              </div>
              <code>
                {name.includes("_features")
                  ? "id · 31 numerical features"
                  : info?.columns?.join(" · ") ||
                    "압축 해제 후 사용 · 원본 식별자 미포함"}
              </code>
              <a className="btn secondary full" href={"/api/datasets/" + path}>
                <Download size={15} /> Download
              </a>
            </article>
          );
        })}
      </div>
      <div className="info-box">
        <ShieldCheck size={22} />
        <div>
          <h3>Homology-aware. Reproducible.</h3>
          <p>
            구조의 ATOM 서열과 정확히 일치하며 Cα 좌표가 95% 이상 있는 샘플만
            사용합니다. 비표준 아미노산과 중복을 제거합니다. 동일 Homologous
            Superfamily는 학습 데이터와 평가 데이터에 동시에 포함되지 않습니다.
            익명 ID만 공개해도 공개 서열·구조 검색으로 정답을 추적할 가능성은
            남으므로 Rules를 반드시 확인하세요.
          </p>
        </div>
      </div>
      <div className="chart-grid">
        <img
          src="/api/datasets/class-distribution"
          alt="Architecture별 샘플 수 분포"
        />
        <img
          src="/api/datasets/length-distribution"
          alt="단백질 서열 길이 분포"
        />
      </div>
      <h3>Structure format</h3>
      <p className="body-copy">
        샘플별 NPZ 파일에 관측 서열과 같은 순서의 Cα 좌표를 제공합니다. pos는
        중심화한 좌표(Å), ca_mask는 좌표 존재 여부입니다. 누락 좌표의 0은 실제
        위치가 아니므로 반드시 마스크와 함께 사용하세요. segment_index는 연속된
        주사슬 구간을 구분합니다. 평가 입력도 같은 형식으로 제공되어 추론
        코드에서 그대로 읽을 수 있습니다.
      </p>
      <pre>
        {
          "residue_type [N] · residue_index [N]\npos [N,3] · ca_mask [N] · segment_index [N]"
        }
      </pre>
      <h3>Sequence format</h3>
      <pre>
        id,sequence,label{"\n"}TRAIN_000001,[40–1200 standard amino acids],3.40
      </pre>
      <p className="attribution">
        Source:{" "}
        <a href="https://www.cathdb.info/" target="_blank" rel="noreferrer">
          CATH Database <ExternalLink size={12} />
        </a>{" "}
        · Orengo Group, UCL ·{" "}
        <a
          href="https://creativecommons.org/licenses/by/4.0/"
          target="_blank"
          rel="noreferrer"
        >
          CC BY 4.0
        </a>
        . 관측 서열 정제·Cα 추출·클래스 선택·익명화·분할을 적용한 파생
        데이터입니다.
      </p>
    </div>
  );
}
