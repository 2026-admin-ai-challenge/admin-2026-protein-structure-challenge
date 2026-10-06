import type { Metadata } from "next";
import "../globals.css";
export const metadata: Metadata = {
  title: "ADMIN AI Challenge 2026 · Protein Structure",
  description:
    "충남대학교 컴퓨터인공지능학부 동아리 ADMIN의 단백질 구조 분류 경진대회. CATH S40 서열·3D 좌표로 도전하세요.",
};
export default function SiteLayout({ children }: { children: React.ReactNode }) {
  return children;
}
