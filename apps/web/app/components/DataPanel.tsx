import {
  FileText,
  Download,
  ShieldCheck,
  ExternalLink,
  Activity,
  Lock,
} from "lucide-react";
import type { Competition } from "../types";
const fmt = (n?: number) => (n === undefined ? "—" : n.toLocaleString());
export default function DataPanel({ data }: { data: Competition | null }) {
  const stat = data?.dataset?.stats;
  if (!data?.dataset_available)
    return (
      <div className="page-content narrow">
        <div className="section-kicker">DATA RELEASE</div>
        <h2 className="section-title">데이터셋은 대회 당일 공개됩니다.</h2>
        <div className="info-box">
          <Lock size={24} />
          <div>
            <h3>모두 같은 시간에, 같은 출발선에서.</h3>
            <p>
              서열·3D 좌표와 데이터가 포함된 Starter Kit은 대회 시작부터 종료
              시각까지만 다운로드할 수 있습니다.
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
              기본 Logistic Regression 코드·노트북과 환경 설치 안내를 먼저
              받으세요. 실제 데이터는 포함하지 않습니다. 학습 실행은 대회 시작
              후 데이터를 받은 뒤 가능합니다.
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
        서열·Cα 좌표 데이터입니다. 원본 domain ID와 시험 정답은 제공하지
        않습니다.
      </p>
      <div className="data-summary">
        <div>
          <small>Total samples</small>
          <strong>{fmt(stat?.total)}</strong>
        </div>
        <div>
          <small>Architectures</small>
          <strong>{fmt(stat?.classes)}</strong>
        </div>
        <div>
          <small>Train / Test</small>
          <strong>
            80 / 20<small> 목표 비율</small>
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
          <h3>처음이라면 Starter Kit부터.</h3>
          <p>
            학습·시험 CSV, 31개 기본 특징, H-group 검증 분할, Logistic
            Regression 노트북과 실행 방법을 한 번에 받으세요. CPU로 첫 제출까지
            실행할 수 있습니다. 구조 좌표는 아래 파일에서 별도로 받을 수
            있습니다.
          </p>
          <a className="btn primary" href="/api/datasets/starter-kit">
            <Download size={15} /> 베이스라인 &amp; Starter Kit
          </a>
        </div>
      </div>
      <p className="body-copy">
        <a href="/api/resources/baseline">
          코드·노트북만 필요하다면: 공개 베이스라인 다운로드 ↗
        </a>
      </p>
      <div className="download-grid">
        {[
          ["train.csv", "train", "학습용 관측 서열과 Architecture 정답"],
          ["test.csv", "test", "분류할 시험 관측 서열 · 정답 미포함"],
          [
            "sample_submission.csv",
            "sample-submission",
            "제출 형식 예시 · 실제 정답 아님",
          ],
          [
            "train_structures.zip",
            "train-structures",
            "학습용 Cα 좌표·마스크·잔기 위치 (NPZ)",
          ],
          [
            "test_structures.zip",
            "test-structures",
            "시험용 구조 좌표 · 정답·원본 ID 미포함",
          ],
          [
            "train_features.csv",
            "train-features",
            "학습용 서열 조성·구조 통계 31개 특징",
          ],
          [
            "test_features.csv",
            "test-features",
            "시험용 기본 특징 · 정답 미포함",
          ],
          [
            "validation_split.csv",
            "validation-split",
            "학습 데이터의 H-group 검증 분할",
          ],
          [
            "starter_kit.zip",
            "starter-kit",
            "CSV·특징·노트북·실행 코드·데이터 설명서",
          ],
        ].map(([name, path, desc]) => (
          <article className="download-card" key={name}>
            <FileText size={26} />
            <h3>{name}</h3>
            <p>{desc}</p>
            <div className="file-info">
              <span>
                {name.endsWith(".zip")
                  ? "ZIP archive"
                  : `${fmt(data?.dataset?.files[name]?.rows)} rows`}
              </span>
              <span>
                {data?.dataset?.files[name]
                  ? (data.dataset.files[name].bytes / (1024 * 1024)).toFixed(
                      2,
                    ) + " MB"
                  : "준비 중"}
              </span>
            </div>
            <code>
              {name.includes("_features")
                ? "id · 31 numerical features"
                : data?.dataset?.files[name]?.columns?.join(" · ") ||
                  "압축 해제 후 사용 · 원본 식별자 미포함"}
            </code>
            <a className="btn secondary full" href={"/api/datasets/" + path}>
              <Download size={15} /> Download
            </a>
          </article>
        ))}
      </div>
      <div className="info-box">
        <ShieldCheck size={22} />
        <div>
          <h3>Homology-aware. Reproducible.</h3>
          <p>
            구조의 ATOM 서열과 정확히 일치하며 Cα 좌표가 95% 이상 있는 샘플만
            사용합니다. 비표준 아미노산과 중복을 제거합니다. 동일 Homologous
            Superfamily는 train/test에 동시에 포함되지 않으며, 난수 시드는 42로
            고정합니다. 익명 ID만 공개해도 공개 서열·구조 검색으로 정답을 추적할
            가능성은 남으므로 Rules를 반드시 확인하세요.
          </p>
        </div>
      </div>
      {data?.dataset && (
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
      )}
      <h3>Structure format</h3>
      <p className="body-copy">
        샘플별 NPZ 파일에 관측 서열과 같은 순서의 Cα 좌표를 제공합니다. pos는
        중심화한 좌표(Å), ca_mask는 좌표 존재 여부입니다. 누락 좌표의 0은 실제
        위치가 아니므로 반드시 마스크와 함께 사용하세요. segment_index는 연속된
        주사슬 구간을 구분합니다. 파일 형식과 로딩 방법은 Starter Kit에
        있습니다.
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
