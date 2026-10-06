// Until the competition opens, only signed-in admins see the site (proxy.ts); everyone
// else gets a D-day countdown that keeps the topic hidden. LAUNCH_AT (ISO 8601, e.g.
// 2026-11-01T09:00:00+09:00) moves the opening; a past time opens the site right away.
// apps/api/app/config.py reads the same variable and must keep the same default.
const DEFAULT_LAUNCH = "2026-11-01T13:00:00+09:00";
// Sign-up Google Form linked from the countdown. APPLY_URL overrides it; empty hides the button.
const DEFAULT_APPLY_URL = "";

export function launchAt() {
  const time = Date.parse(process.env.LAUNCH_AT || DEFAULT_LAUNCH);
  // A typo must not open the site early, so fall back to the default.
  return Number.isNaN(time) ? Date.parse(DEFAULT_LAUNCH) : time;
}

export function applyUrl() {
  const url = process.env.APPLY_URL || DEFAULT_APPLY_URL;
  return url.startsWith("https://") ? url : null;
}
