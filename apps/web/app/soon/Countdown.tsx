"use client";
import { useEffect, useState } from "react";
import { ArrowUpRight } from "lucide-react";
import AdminLogin from "./AdminLogin";

// Nothing here may hint at the competition topic: only that it is an AI inference
// model challenge. The topic is revealed when the site opens.

const SECOND = 1000;
const DAY = 86_400_000;
const KST = 9 * 3_600_000;

const pad = (n: number) => String(n).padStart(2, "0");

// Calendar days between two instants in Korea time, so the day before is D-1.
function dDay(now: number, launch: number) {
  return Math.floor((launch + KST) / DAY) - Math.floor((now + KST) / DAY);
}

function launchLabel(launch: number) {
  const d = new Date(launch + KST);
  const weekday = "일월화수목금토"[d.getUTCDay()];
  return `${d.getUTCFullYear()}.${pad(d.getUTCMonth() + 1)}.${pad(d.getUTCDate())} (${weekday}) ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} KST`;
}

// A small fully connected network drawn behind the D-day number.
const LAYER_X = [70, 230, 390, 550];
const LAYERS = [4, 6, 6, 3].map((size, l) =>
  Array.from({ length: size }, (_, i) => [
    LAYER_X[l],
    210 + (i - (size - 1) / 2) * 62,
  ]),
);

function Network() {
  return (
    <svg className="soon-net" viewBox="0 0 620 420">
      <g className="soon-net-edges">
        {LAYERS.slice(1).flatMap((layer, l) =>
          layer.flatMap(([x2, y2], j) =>
            LAYERS[l].map(([x1, y1], i) => (
              <line key={`${l}-${i}-${j}`} x1={x1} y1={y1} x2={x2} y2={y2} />
            )),
          ),
        )}
      </g>
      {LAYERS.flat().map(([x, y], i) => (
        <circle
          key={i}
          cx={x}
          cy={y}
          r={7}
          style={{ animationDelay: `${(i * 0.37) % 3}s` }}
        />
      ))}
    </svg>
  );
}

export default function Countdown({
  launchAt,
  serverNow,
  applyUrl,
}: {
  launchAt: number;
  serverNow: number;
  applyUrl: string | null;
}) {
  const [now, setNow] = useState(serverNow),
    [login, setLogin] = useState(false);
  useEffect(() => {
    // Follow the server's clock so a wrong device clock cannot skew the countdown.
    const offset = serverNow - Date.now();
    const tick = () =>
      setNow(Math.floor((Date.now() + offset) / SECOND) * SECOND);
    tick();
    const timer = window.setInterval(tick, 250);
    return () => window.clearInterval(timer);
  }, [serverNow]);

  const done = now >= launchAt;
  useEffect(() => {
    if (!done) return;
    // Past the launch time the server sends the competition site instead.
    const timer = window.setTimeout(() => window.location.reload(), 1500);
    return () => window.clearTimeout(timer);
  }, [done]);

  const left = Math.max(0, launchAt - now);
  const days = dDay(now, launchAt);
  const units: [number, string][] = [
    [Math.floor(left / DAY), "DAYS"],
    [Math.floor(left / 3_600_000) % 24, "HOURS"],
    [Math.floor(left / 60_000) % 60, "MINUTES"],
    [Math.floor(left / SECOND) % 60, "SECONDS"],
  ];
  return (
    <div className="soon">
      <div className="soon-grid" aria-hidden />
      <header className="soon-header">
        <span className="soon-brand">
          <img src="/admin-logo.png" alt="ADMIN" />
          <span className="soon-brand-divider" />
          <span>AI CHALLENGE</span>
        </span>
        <button
          type="button"
          className="soon-login"
          onClick={() => setLogin(true)}
        >
          운영진 로그인
        </button>
      </header>
      <main className="soon-main">
        <div className="soon-art" aria-hidden>
          <Network />
        </div>
        <div className="soon-eyebrow">
          <span className="soon-dot" />
          ADMIN AI CHALLENGE 2026
        </div>
        <h1
          className="soon-dday"
          aria-label={days > 0 ? `대회 시작 ${days}일 전` : "대회 당일"}
        >
          {days > 0 ? `D-${days}` : "D-DAY"}
        </h1>
        <h2 className="soon-title">
          AI <span>Inference</span> Model Challenge
        </h2>
        <p className="soon-sub">The topic will be revealed on launch day.</p>
        <div
          className="soon-clock"
          role="timer"
          aria-label="대회 시작까지 남은 시간"
        >
          {units.map(([value, label]) => (
            <div className="soon-unit" key={label}>
              <strong>{pad(value)}</strong>
              <span>{label}</span>
            </div>
          ))}
        </div>
        {applyUrl && (
          <a
            className="soon-apply"
            href={applyUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            참가 신청하기 <ArrowUpRight size={18} />
          </a>
        )}
        <p className="soon-date">
          <span className="soon-dot" />
          {launchLabel(launchAt)} OPEN
        </p>
        <p className="soon-korean">
          충남대학교 컴퓨터인공지능학부 동아리 ADMIN이 준비한 AI 추론 모델 챌린지.
          <br />
          어떤 문제에 도전하게 될지는 대회 당일 공개됩니다.
        </p>
      </main>
      <p className="soon-footer">충남대학교 컴퓨터인공지능학부 동아리 ADMIN</p>
      {login && <AdminLogin onClose={() => setLogin(false)} />}
    </div>
  );
}
