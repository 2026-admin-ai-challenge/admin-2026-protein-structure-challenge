"use client";
import { useState } from "react";
import { ShieldCheck } from "lucide-react";
import type { Settings, User } from "../types";
import AccountsSection from "./admin/AccountsSection";
import AuditSection from "./admin/AuditSection";
import AwardsSection from "./admin/AwardsSection";
import DatasetSection from "./admin/DatasetSection";
import SettingsSection from "./admin/SettingsSection";
import SubmissionsSection from "./admin/SubmissionsSection";

const SECTIONS = [
  ["overview", "현황·설정"],
  ["accounts", "팀·계정"],
  ["submissions", "제출·대기열"],
  ["awards", "특별상"],
  ["dataset", "데이터"],
  ["audit", "조작 기록"],
] as const;
type Section = (typeof SECTIONS)[number][0];

export default function AdminPanel({
  user,
  settings,
  onLogin,
  onChanged,
}: {
  user: User | null;
  settings: Settings | undefined;
  onLogin: () => void;
  // Tells the page to reload competition status and the public leaderboard.
  onChanged: () => void;
}) {
  const [section, setSection] = useState<Section>("overview");
  const finalized = settings?.finalized ?? false;
  return (
    <div className="page-content">
      <div className="section-kicker">ORGANIZER WORKSPACE</div>
      <h2 className="section-title">Competition control.</h2>
      {user?.role !== "ADMIN" ? (
        <div className="sign-in-card">
          <ShieldCheck size={30} />
          <h3>관리자 권한이 필요합니다</h3>
          <button className="btn primary" onClick={onLogin}>
            Log in
          </button>
        </div>
      ) : (
        <>
          <div className="admin-nav" role="tablist" aria-label="관리 메뉴">
            {SECTIONS.map(([key, label]) => (
              <button
                key={key}
                role="tab"
                aria-selected={section === key}
                className={section === key ? "selected" : ""}
                onClick={() => setSection(key)}
              >
                {label}
              </button>
            ))}
          </div>
          {section === "overview" && <SettingsSection onChanged={onChanged} />}
          {section === "accounts" && (
            <AccountsSection finalized={finalized} onChanged={onChanged} />
          )}
          {section === "submissions" && (
            <SubmissionsSection finalized={finalized} onChanged={onChanged} />
          )}
          {section === "awards" && <AwardsSection finalized={finalized} />}
          {section === "dataset" && <DatasetSection onChanged={onChanged} />}
          {section === "audit" && <AuditSection />}
        </>
      )}
    </div>
  );
}
