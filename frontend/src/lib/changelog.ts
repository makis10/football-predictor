/**
 * Platform changelog — surfaced through the header notification bell.
 *
 * Newest first. `id` must be unique and stable (used for the "read" marker).
 * Keep entries short and user-facing — what changed and why it matters, not
 * internal implementation detail. Bump the list when something user-visible
 * ships; the bell shows a badge for entries newer than the reader's last visit.
 */
export type ChangeTag = "new" | "fix" | "improvement";

export interface ChangelogEntry {
  id: string;        // stable unique id, e.g. "2026-06-30-eliminated-teams"
  date: string;      // ISO "YYYY-MM-DD"
  tag: ChangeTag;
  title: string;
  body: string;
}

export const CHANGELOG: ChangelogEntry[] = [
  {
    id: "2026-06-30-fair-value-roi",
    date: "2026-06-30",
    tag: "new",
    title: "Fair-value ROI — performance without the bookmaker margin",
    body: "The ROI tracker now shows what our picks would return at fair (de-vigged) odds. At fair value the model is essentially break-even — the negative real-money ROI is the bookmaker's built-in commission, not a model error. A new amber line on the EV chart shows this fair P&L; the gap to actual P&L is the commission paid.",
  },
  {
    id: "2026-06-30-btts-stats",
    date: "2026-06-30",
    tag: "new",
    title: "Goal / No Goal (BTTS) stats & calibration",
    body: "The Stats page now tracks our Both-Teams-To-Score predictions — accuracy, recall, precision, ROI and a calibration chart — alongside the result and over/under markets.",
  },
  {
    id: "2026-06-30-top-picks-accuracy",
    date: "2026-06-30",
    tag: "new",
    title: "Top AI Picks accuracy",
    body: "A dedicated Stats section shows how the 3 daily Top Picks (shown on the home page) have actually performed over time, versus the overall hit rate.",
  },
  {
    id: "2026-06-30-live-results-source",
    date: "2026-06-30",
    tag: "improvement",
    title: "Faster, more accurate live results",
    body: "During a live tournament, final scores and penalty-shootout winners now come straight from the live data feed (instead of waiting ~1 day for the open dataset), so results, eliminations and stats update the same day.",
  },
  {
    id: "2026-06-30-eliminated-teams",
    date: "2026-06-30",
    tag: "fix",
    title: "Knocked-out teams leave the title race",
    body: "Once a team loses a knockout match, the World Cup simulation removes it from the Champion-probability list instead of leaving it with a stray percentage.",
  },
  {
    id: "2026-06-30-golden-boot-availability",
    date: "2026-06-30",
    tag: "improvement",
    title: "Golden Boot respects injuries & suspensions",
    body: "Injured or suspended players (from the official injury feed) are now excluded from the top-scorer projection, refreshed daily.",
  },
  {
    id: "2026-06-30-club-form-props",
    date: "2026-06-30",
    tag: "improvement",
    title: "Player props now weigh club form",
    body: "Scorer / shots / assist rates are anchored to each player's current club-season output, so low-cap players are no longer flattened to a league average.",
  },
  {
    id: "2026-06-30-champion-trend",
    date: "2026-06-30",
    tag: "new",
    title: "World Cup champion-odds trend chart",
    body: "The World Cup page now charts how each contender's title odds move day-by-day as real results come in.",
  },
  {
    id: "2026-06-30-stats-methodology",
    date: "2026-06-30",
    tag: "improvement",
    title: "Honest model-change note on Stats",
    body: "The accuracy page flags that all-time numbers blend an older and the current model; the rolling 7d/30d figures best reflect today's model.",
  },
  {
    id: "2026-06-30-recent-accuracy",
    date: "2026-06-30",
    tag: "fix",
    title: "Recent-results accuracy matches Stats",
    body: "Recent Results and the Stats page now grade predictions with one shared rule, so their accuracy figures can't drift apart.",
  },
  {
    id: "2026-06-17-market-independent",
    date: "2026-06-17",
    tag: "improvement",
    title: "Fully market-independent model",
    body: "The match model no longer uses bookmaker odds as inputs — predictions are purely model-driven, and value is measured against the market rather than borrowed from it.",
  },
];
