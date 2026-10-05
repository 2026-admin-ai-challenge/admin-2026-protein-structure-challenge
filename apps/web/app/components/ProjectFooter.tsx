import { ArrowUpRight, Github, Lock } from "lucide-react";

// Add confirmed project participants here as the team grows.
const lead = { username: "Hottae0", initial: "H", title: "프로젝트 총괄", role: "데이터셋·평가 기준 구축" };

type Member = { username: string; initial: string; role?: string };
type Team = { id: string; name: string; role: string; members: Member[] };

// A member role overrides the team role when set.
const teams: Team[] = [
  {
    id: "web",
    name: "웹사이트 팀",
    role: "웹사이트·운영 API 개발",
    members: [
      { username: "ImmoC-hub", initial: "I", role: "채점 인프라 · 배포 운영" },
      { username: "Seohee7472", initial: "S", role: "제출 API · 접수 검증" },
      { username: "llmdlng", initial: "L", role: "관리자 화면 · 리더보드" },
      { username: "disfos990", initial: "D", role: "참가자 화면 · 제출 UX" },
    ],
  },
  {
    id: "data",
    name: "데이터 팀",
    role: "데이터셋·평가 기준 구축",
    members: [
      { username: "Yun-seoung", initial: "Y", role: "예측 검증 · 제출 신뢰성" },
      { username: "Seoyun-Ban", initial: "S", role: "모델 비교 · 성능 기준선" },
      { username: "tacocat404", initial: "T", role: "데이터 품질 · 이상치 분석" },
      { username: "hoseongdev", initial: "H", role: "데이터 분할 · 누출 검증" },
    ],
  },
];

const contributorCount = 1 + teams.reduce((count, team) => count + team.members.length, 0);

const profileProps = (username: string) => ({
  href: `https://github.com/${username}`,
  target: "_blank",
  rel: "noopener noreferrer",
  "aria-label": `${username} GitHub 프로필 (새 탭)`,
});

export default function ProjectFooter() {
  return (
    <footer className="container project-footer">
      <div className="footer-project">
        <div className="footer-project-intro">
          <span className="footer-eyebrow">MADE TOGETHER</span>
          <h2>함께 만드는 AI 챌린지.</h2>
          <p>충남대학교 AI 동아리 ADMIN의 아이디어와 기여로 만들어집니다.</p>
          <a className="footer-github" href="https://github.com/2026-admin-ai-challenge/admin-2026-protein-structure-challenge" target="_blank" rel="noopener noreferrer">
            <Github size={17} aria-hidden="true" />
            <span>GitHub 프로젝트</span>
            <span className="footer-private"><Lock size={11} aria-hidden="true" /> Private</span>
            <ArrowUpRight size={14} aria-hidden="true" />
          </a>
          <p className="footer-access-note">대회 운영 중에는 저장소 접근 권한이 필요합니다.</p>
        </div>
        <div className="footer-contributors">
          <h3>프로젝트 기여자 <span>{contributorCount}</span></h3>
          <a className="footer-contributor footer-lead" {...profileProps(lead.username)}>
            <span className="contributor-avatar" aria-hidden="true">{lead.initial}</span>
            <span className="contributor-info">
              <span className="lead-name"><strong>{lead.username}</strong><span className="lead-badge">팀장</span></span>
              <span>{lead.title} · <span className="lead-role">{lead.role}</span></span>
            </span>
            <Github size={19} aria-hidden="true" />
            <ArrowUpRight size={15} aria-hidden="true" />
          </a>
          <div className="contributor-teams">
            {teams.map((team) => (
              <section className={`contributor-team team-${team.id}`} key={team.id} aria-label={team.name}>
                <h4>{team.name} <span>{team.members.length}</span></h4>
                <ul>
                  {team.members.map((member) => (
                    <li key={member.username}>
                      <a className="footer-contributor" {...profileProps(member.username)}>
                        <span className="contributor-avatar" aria-hidden="true">{member.initial}</span>
                        <span className="contributor-info"><strong>{member.username}</strong><span>{member.role ?? team.role}</span></span>
                        <Github size={17} aria-hidden="true" />
                        <ArrowUpRight size={14} aria-hidden="true" />
                      </a>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        </div>
      </div>
      <div className="footer-bottom">
        <div className="footer-brand">
          <img src="/admin-logo.png" alt="ADMIN" />
          <span>Built by curiosity. Powered by community.</span>
        </div>
        <span>© 2026 ADMIN · Chungnam National University</span>
        <a href="https://www.cathdb.info/" target="_blank" rel="noopener noreferrer">Data by CATH <ArrowUpRight size={12} aria-hidden="true" /></a>
      </div>
    </footer>
  );
}
