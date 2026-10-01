import { ArrowUpRight, Github, Lock } from "lucide-react";

// Add confirmed project participants here as the team grows.
const contributors = [
  { username: "Hottae0", role: "프로젝트 개발", initial: "H" },
];

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
          <h3>프로젝트 기여자 <span>{contributors.length}</span></h3>
          <ul>
            {contributors.map((contributor) => (
              <li key={contributor.username}>
                <a className="footer-contributor" href={`https://github.com/${contributor.username}`} target="_blank" rel="noopener noreferrer" aria-label={`${contributor.username} GitHub 프로필 (새 탭)`}>
                  <span className="contributor-avatar" aria-hidden="true">{contributor.initial}</span>
                  <span className="contributor-info"><strong>{contributor.username}</strong><span>{contributor.role}</span></span>
                  <Github size={17} aria-hidden="true" />
                  <ArrowUpRight size={14} aria-hidden="true" />
                </a>
              </li>
            ))}
          </ul>
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
