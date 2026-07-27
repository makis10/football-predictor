import { redirect } from "next/navigation";

/**
 * World Cup 2026 ended on 2026-07-19 (Spain 1-0 Argentina). Both the Monte Carlo
 * simulation and the retrospective review have been retired from the live site;
 * this route redirects to the homepage so existing inbound links and
 * search results land somewhere useful.
 *
 * Temporary (307), NOT permanent (308), on purpose: the simulation UI lives in
 * git history and is meant to come back for the next national-team tournament,
 * and a 308 would be cached by browsers/CDNs and keep redirecting users past the
 * restored page.
 *
 * Restore for the next tournament: bring back the sim + review pages from git,
 * re-add the sitemap entries and nav link, and set WC_ACTIVE=1 in .env to
 * re-enable the pipeline steps.
 * Frozen artifacts: backend/data/models/national/archive/wc2026/
 */
export default function WorldCupPage(): never {
  // Straight to home — /national itself only redirects to / anyway.
  redirect("/");
}
