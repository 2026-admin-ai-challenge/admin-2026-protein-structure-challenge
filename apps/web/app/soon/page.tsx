import { redirect } from "next/navigation";
import Countdown from "./Countdown";
import { applyUrl, launchAt } from "../launch";
import "./soon.css";

// Rendered per request so it always counts from the current time.
export const dynamic = "force-dynamic";

export default function Page() {
  const launch = launchAt();
  const now = Date.now();
  if (now >= launch) redirect("/");
  return <Countdown launchAt={launch} serverNow={now} applyUrl={applyUrl()} />;
}
