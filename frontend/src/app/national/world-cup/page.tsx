import { redirect } from "next/navigation";

/**
 * World Cup 2026 ended on 2026-07-19 (Spain 1-0 Argentina), so the Monte Carlo
 * simulation page has nothing left to predict. The route is kept as a redirect
 * to the retrospective review rather than deleted, so existing inbound links and
 * search results land on the tournament's lasting content.
 *
 * Deliberately a temporary (307) redirect, NOT a permanent (308) one: this route
 * is meant to come back for the next national-team tournament, and browsers /
 * CDNs cache a 308 indefinitely — which would keep redirecting users away from
 * the restored simulation page.
 *
 * The full simulation UI lives in git history — restore it (and re-add the
 * sitemap entry + point the nav link back here) when the next tournament starts.
 * Frozen artifacts: backend/data/models/national/archive/wc2026/
 * Pipeline steps re-enable with WC_ACTIVE=1 in .env.
 */
export default function WorldCupPage(): never {
  redirect("/national/world-cup/review");
}
