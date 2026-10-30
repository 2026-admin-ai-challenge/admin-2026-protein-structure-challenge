import {
  ArrowUpRight,
  ArrowRight,
  ArrowDown,
  Download,
  Upload,
  Check,
  ChevronRight,
  ChevronDown,
  Sun,
  Moon,
  Menu,
  X,
  FlaskConical,
  Layers3,
  Activity,
  Database,
  Trophy,
  Clock,
  Users,
  FileText,
  Code2,
  ShieldCheck,
  LogOut,
  Plus,
  ExternalLink,
  Lock,
  RotateCcw,
} from "lucide-react";
import type { Limits, Meta } from "../types";
import { megabytes } from "../format";
import { useLeaderboard } from "../lib/useLeaderboard";
import { LeaderboardTable } from "./LeaderboardPanel";
export default function OverviewPanel({
  stat,
  datasetAvailable,
  limits,
  live,
  navigate,
}: {
  stat: Meta["stats"] | undefined;
  datasetAvailable: boolean;
  limits: Limits | undefined;
  // False while the ranking is frozen: the board then stays still.
  live: boolean;
  navigate: (tab: string) => void;
}) {
  // Every ranked team, kept live like the Leaderboard tab.
  const { data: board } = useLeaderboard("public", live);
  return (
    <>
      <div className="overview-grid">
        <div>
          <div className="section-kicker">THE CHALLENGE</div>
          <h2 className="section-title">생명의 구조를, AI로 읽다.</h2>
          <p className="body-copy">
            단백질의 모양에는 공간에 놓인 아미노산들의 관계가 담겨 있습니다.
            이번 대회에서는{" "}
            <b>서열과 실험 3D 구조를 이용해 단백질 도메인의 Architecture</b>를
            예측합니다.
          </p>
          <p className="body-copy">
            제공된 학습 데이터로 모델을 학습하고, 학습된 모델과 추론 코드를
            ZIP으로 제출하세요.
            <br />
            서버가 숨겨진 평가 데이터로 추론을 실행해 점수를 계산합니다.
          </p>
          <div className="tags">
            <span>Bioinformatics</span>
            <span>Multiclass Classification</span>
            <span>All skill levels</span>
          </div>
          <div className="workflow">
            <div>
              <div className="step-icon">
                <Code2 size={21} />
              </div>
              <small>01 · INPUT</small>
              <strong>Sequence + 3D structure</strong>
              <code>Amino acids · Cα coordinates</code>
            </div>
            <ArrowRight size={20} />
            <div>
              <div className="step-icon">
                <FlaskConical size={21} />
              </div>
              <small>02 · YOUR APPROACH</small>
              <strong>AI model</strong>
              <span>Learn the hidden patterns</span>
            </div>
            <ArrowRight size={20} />
            <div>
              <div className="step-icon target">
                <Layers3 size={21} />
              </div>
              <small>03 · SCORED ON SERVER</small>
              <strong>Architecture</strong>
              <code>CATH label · 3.40</code>
            </div>
          </div>
        </div>
        <aside className="quick-card">
          <div className="quick-title">
            <span className="small-icon">
              <FlaskConical size={18} />
            </span>
            <strong>Your next discovery starts here.</strong>
          </div>
          <p>
            작은 호기심을 첫 번째 모델로.
            <br />
            {datasetAvailable
              ? "학습 데이터를 내려받고 도전을 시작하세요."
              : "학습 데이터는 대회 시작 시각에 공개됩니다."}
          </p>
          <div className="quick-line">
            <span>Dataset</span>
            <strong>CATH-Plus v4.4</strong>
          </div>
          <div className="quick-line">
            <span>Architectures</span>
            <strong>
              {stat ? stat.classes + " classes" : "대회 당일 공개"}
            </strong>
          </div>
          <div className="quick-line">
            <span>Submissions per team</span>
            <strong>
              {limits ? limits.team_submissions + "회 · 대회 전체" : "—"}
            </strong>
          </div>
          <div className="quick-line">
            <span>Submission format</span>
            <code>
              Model ZIP{limits ? " · " + megabytes(limits.zip_bytes) : ""}
            </code>
          </div>
          <div className="quick-actions">
            {datasetAvailable ? (
              <>
                <button
                  className="btn primary quick-action"
                  onClick={() => navigate("Data")}
                >
                  <span>학습 데이터 다운로드</span>
                  <ArrowRight size={17} />
                </button>
                <a
                  className="btn secondary quick-action"
                  href="/api/resources/baseline"
                >
                  <span>
                    <Download size={16} /> 베이스라인 코드 받기
                  </span>
                  <ArrowDown size={16} />
                </a>
              </>
            ) : (
              <>
                <a
                  className="btn primary quick-action"
                  href="/api/resources/baseline"
                >
                  <span>
                    <Download size={16} /> 베이스라인 코드 받기
                  </span>
                  <ArrowDown size={16} />
                </a>
                <button
                  className="btn secondary quick-action"
                  onClick={() => navigate("Data")}
                >
                  <span>
                    <Lock size={15} /> 데이터 공개 일정
                  </span>
                  <ArrowRight size={16} />
                </button>
              </>
            )}
            <p className="quick-action-note">
              코드와 실행 안내는 지금 확인할 수 있어요.
            </p>
          </div>
          <div className="quick-foot">
            <ShieldCheck size={13} /> 단백질 계열을 분리한 학습·평가 데이터
          </div>
        </aside>
      </div>
      <div className="section-rule" />
      <div className="section-heading">
        <div>
          <div className="section-kicker">BUILT FOR EXPLORATION</div>
          <h2 className="section-title smaller">
            One structure. Many possibilities.
          </h2>
        </div>
        <span className="muted">Learn. Experiment. Discover.</span>
      </div>
      <div className="feature-grid">
        <article>
          <span className="feature-index">01</span>
          <Database size={22} />
          <h3>Real science. Real data.</h3>
          <p>
            실험적으로 확인된 CATH S40 도메인. 서열·Cα 좌표와 CPU 베이스라인을
            제공해 모델 실험에 집중할 수 있습니다.
          </p>
          <button className="text-link" onClick={() => navigate("Data")}>
            데이터 살펴보기 <ArrowUpRight size={14} />
          </button>
        </article>
        <article>
          <span className="feature-index">02</span>
          <Layers3 size={22} />
          <h3>Find the architecture.</h3>
          <p>
            Class → Architecture → Topology → Superfamily. 네 단계 중 구조의
            전체적인 배치를 예측합니다.
          </p>
          <div className="mini-hierarchy">
            <span>C</span>
            <ChevronRight size={12} />
            <b>A</b>
            <ChevronRight size={12} />
            <span>T</span>
            <ChevronRight size={12} />
            <span>H</span>
            <small>Prediction target</small>
          </div>
        </article>
        <article>
          <span className="feature-index">03</span>
          <Activity size={22} />
          <h3>Every class matters.</h3>
          <p>
            클래스마다 동등한 비중을 주는 Macro F1. Public 30%, Private 70%로
            모델의 일반화 성능을 평가합니다.
          </p>
          <button className="text-link" onClick={() => navigate("Evaluation")}>
            평가 방식 알아보기 <ArrowUpRight size={14} />
          </button>
        </article>
      </div>
      <div className="section-heading leaderboard-heading">
        <div>
          <div className="section-kicker">THE COMMUNITY IN MOTION</div>
          <h2 className="section-title smaller">Leaderboard</h2>
        </div>
        <button className="text-link" onClick={() => navigate("Leaderboard")}>
          View full leaderboard <ArrowRight size={15} />
        </button>
      </div>
      <LeaderboardTable entries={board?.entries ?? null} live={live} />
      <div className="about-banner">
        <div className="about-logo">
          <img src="/admin-logo.png" alt="ADMIN" />
        </div>
        <div>
          <small>CHUNGNAM NATIONAL UNIVERSITY</small>
          <h3>함께 배우고, 더 멀리 도전합니다.</h3>
          <p>
            충남대학교 컴퓨터인공지능학부 동아리 ADMIN이 만드는 열린 AI 실험의 장.
          </p>
        </div>
        <span className="about-symbol">↗</span>
      </div>
    </>
  );
}
