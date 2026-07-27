import { redirect } from "next/navigation";

/**
 * World Cup 2026 ended on 2026-07-19 (Spain 1-0 Argentina). The retrospective
 * review has been retired from the live site along with the simulation page —
 * this route now redirects to the homepage so any lingering inbound
 * links land somewhere useful.
 *
 * Temporary (307), NOT permanent (308), on purpose: the review UI lives in git
 * history and can be restored for the next national-team tournament, and a 308
 * would be cached by browsers/CDNs and keep redirecting past the restored page.
 *
 * The underlying data (predictions + results) stays in the DB. Frozen artifacts:
 * backend/data/models/national/archive/wc2026/
 */
export default function WorldCupReviewPage(): never {
  // Straight to home — /national itself only redirects to / anyway.
  redirect("/");
}
