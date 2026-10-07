import type { Metadata } from "next";
// Holds neither the site's styles nor its copy: the pre-launch countdown renders under
// this layout and must not reveal the competition topic, even in the page source.
// The site adds both in (site)/layout.tsx.
export const metadata: Metadata = {
  title: "ADMIN AI Challenge 2026",
  description: "충남대학교 컴퓨터인공지능학부 동아리 ADMIN의 AI 추론 모델 챌린지.",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
