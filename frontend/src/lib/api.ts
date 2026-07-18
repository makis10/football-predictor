// Server-side (SSR/RSC): talk directly to the backend container.
// Client-side (browser): use the Next.js proxy route so only ONE public URL
// is needed — works both locally and when the site is shared via a tunnel
// (cloudflared). The proxy at /api/proxy/* forwards to the backend
// server-side, so visitors never need to reach backend:8000 directly.
const API_URL =
  typeof window === "undefined"
    ? (process.env.INTERNAL_API_URL ?? "http://localhost:8000")  // SSR: direct
    : "/api/proxy";                                          // browser: proxy

// For "use client" components, which only ever run in the browser: same
// proxy path as API_URL's browser branch above, exported so those files
// don't each redefine their own (and risk falling back to an unreachable
// localhost:8000 if NEXT_PUBLIC_API_URL is ever unset at build time).
export const CLIENT_API_URL = "/api/proxy";

// ── Types ─────────────────────────────────────────────────────────────────────

/**
 * Flat prediction data embedded inside a Match when include_predictions=true.
 * Using flat column names avoids extra serialisation work on the backend.
 */
export interface PredictionEmbed {
  home_win_prob: number;
  draw_prob: number;
  away_win_prob: number;
  over_2_5_prob: number;
  goals_prediction: "OVER" | "UNDER";
  model_version: string;
  confidence: "high" | "medium" | "low";
  suggested_market: string | null;
  ev_score: number | null;
  /** Both teams absent from training history → not a real prediction (identical
   *  default output for every such fixture). UI shows an "insufficient data" note. */
  insufficient_data?: boolean;
}

export interface Match {
  id: number;
  league: string;
  season: string;
  match_date: string;
  /** UTC kick-off time as "HH:MM:SS" (or null for legacy fixtures). */
  kickoff_time: string | null;
  /**
   * Full UTC kick-off instant (ISO), when known. Unlike kickoff_time it can
   * represent kick-offs whose UTC calendar date differs from match_date
   * (late US games). Set for national fixtures; club rows omit it.
   */
  kickoff_utc?: string | null;
  home_team: string;
  away_team: string;
  home_goals: number | null;
  away_goals: number | null;
  result: "H" | "D" | "A" | null;
  created_at: string;
  /** European tie round, e.g. "2nd Qualifying Round" (null for domestic leagues). */
  round?: string | null;
  /** Present when the matches endpoint is called with include_predictions=true */
  prediction?: PredictionEmbed | null;
}

export interface WinProbabilities {
  home_win: number;
  draw: number;
  away_win: number;
}

export interface GoalsPrediction {
  over_2_5_probability: number;
  prediction: "OVER" | "UNDER";
}

/** Full prediction response from /predictions/{match_id} */
export interface Prediction {
  match_id: number;
  home_team: string;
  away_team: string;
  league: string;
  match_date: string;
  win_probabilities: WinProbabilities;
  goals: GoalsPrediction;
  btts_prob: number | null;
  model_version: string;
  confidence: "high" | "medium" | "low";
  suggested_market: string | null;
  ev_score: number | null;
  insufficient_data?: boolean;
}

// ── Odds / Analysis types ─────────────────────────────────────────────────────

export interface BookmakerFairProbs {
  home_win:  number | null;
  draw:      number | null;
  away_win:  number | null;
  over_2_5:  number | null;
  under_2_5: number | null;
  btts_yes:  number | null;   // GG fair probability
  btts_no:   number | null;   // NG fair probability
}

export interface BookmakerRawOdds {
  home_win:  number | null;
  draw:      number | null;
  away_win:  number | null;
  over_2_5:  number | null;
  under_2_5: number | null;
  btts_yes:  number | null;   // GG avg decimal odds
  btts_no:   number | null;   // NG avg decimal odds
}

export interface BookmakerData {
  fair_probs:     BookmakerFairProbs;
  raw_odds:       BookmakerRawOdds;
  bookmakers:     string[];
  num_bookmakers: number;
}

export interface ModelProbs {
  home_win: number;
  draw:     number;
  away_win: number;
  over_2_5: number;
  btts:     number | null;   // Both Teams To Score — Poisson-derived
}

export interface InjuredPlayer {
  name:   string;
  type:   "Injured" | "Suspended" | "Questionable";
  reason: string;
}

export interface InjuryData {
  home: InjuredPlayer[];
  away: InjuredPlayer[];
}

/** Delta between the two most recent odds snapshots (latest − previous).
 *  Positive = drifted out. Negative = shortened (steam). null = no data yet. */
export interface OddsMovement {
  home_delta:         number | null;
  draw_delta:         number | null;
  away_delta:         number | null;
  over_delta:         number | null;
  snapshot_age_hours: number | null;
}

export interface CorrectScoreProb {
  score: string;   // e.g. "1-0"
  prob:  number;   // e.g. 0.18
}

export interface PoissonStats {
  over_1_5:           number;
  under_1_5:          number;
  over_2_5:           number;   // Poisson-derived (may differ from XGBoost model.over_2_5)
  under_2_5:          number;
  over_3_5:           number;
  under_3_5:          number;
  home_over_1_5:      number;
  home_under_1_5:     number;
  away_over_1_5:      number;
  away_under_1_5:     number;
  top_scores:         CorrectScoreProb[];
  most_likely_score:  string | null;
  btts_and_over_2_5:  number;
  btts_and_under_2_5: number;
  home_win_and_btts:  number;
  away_win_and_btts:  number;
  home_win_and_ng:    number;   // home wins, only home scores (1-0, 2-0…)
  away_win_and_ng:    number;   // away wins, only away scores (0-1, 0-2…)
}

export interface WatchMarket {
  market:      string;             // "GG @ 2.33"
  /** Expected value: return per unit staked (model_prob × odds − 1), e.g. 21.2 = +21.2%.
   *  NOT a probability — never render it alongside market_pct as if it were one. */
  ev_pct:      number;
  model_pct:   number | null;      // our model's probability for this market
  market_pct:  number | null;      // de-vigged bookmaker probability (same units as model_pct)
}

export interface MatchAnalysis {
  match_id:          number;
  home_team:         string;
  away_team:         string;
  model:             ModelProbs;
  bookmakers:        BookmakerData | null;
  injuries:          InjuryData | null;
  analysis:          string;
  suggested_market:  string | null;          // primary pick (backwards compat)
  suggested_markets: string[];               // ranked list, up to 2
  watch_markets?:    WatchMarket[];           // model edge, unproven — shadow-tracked
  h_elo?:            number | null;           // Elo ratings (club + national)
  a_elo?:            number | null;
  exp_home_cards?:   number | null;           // team props (club + national)
  exp_away_cards?:   number | null;
  exp_home_corners?: number | null;
  exp_away_corners?: number | null;
  corners_over_9_5_prob?: number | null;
  poisson_stats:     PoissonStats | null;    // extended stats from λ_home/λ_away
  has_odds_data:     boolean;
  has_injury_data:   boolean;
  odds_movement:     OddsMovement | null;
}

// ── Stats / Accuracy Tracking types ──────────────────────────────────────────

export interface AccuracySlice {
  total: number;
  result_correct: number;
  goals_correct: number;
  both_correct: number;
  result_accuracy: number;
  goals_accuracy: number;
  both_accuracy: number;
}

export interface RollingAccuracy {
  last_7d: AccuracySlice;
  last_30d: AccuracySlice;
  all_time: AccuracySlice;
}

export interface LeagueBreakdown {
  league: string;
  total: number;
  result_correct: number;
  goals_correct: number;
  both_correct: number;
  result_accuracy: number;
  goals_accuracy: number;
  both_accuracy: number;
}

export interface ConfidenceBreakdown {
  confidence: string;
  total: number;
  result_correct: number;
  result_accuracy: number;
}

export interface PredictedOutcomeBreakdown {
  predicted: string;
  total: number;
  correct: number;
  accuracy: number;
}

export interface DrawStats {
  total_draws: number;
  predicted_draws: number;
  correctly_predicted: number;
  recall: number;
  precision: number;
}

export interface CalibrationBucket {
  bucket_min: number;
  bucket_max: number;
  predicted_prob: number;
  actual_rate: number;
  count: number;
}

export interface ResultCalibration {
  home: CalibrationBucket[];
  draw: CalibrationBucket[];
  away: CalibrationBucket[];
}

export interface ModelVersionStats {
  model_version: string;
  total: number;
  result_accuracy: number;
  goals_accuracy: number;
}

export interface TopPicksStats {
  total: number;
  correct: number;
  accuracy: number;
  result_picks: number;
  result_correct: number;
  result_accuracy: number;
  goals_picks: number;
  goals_correct: number;
  goals_accuracy: number;
  avg_pick_prob: number;
  vs_overall_accuracy: number;  // delta vs all-time overall accuracy
}

export interface BTTSStats {
  total_gg: number;
  total_ng: number;
  predicted_gg: number;
  predicted_ng: number;
  correctly_predicted_gg: number;
  correctly_predicted_ng: number;
  gg_recall: number;
  ng_recall: number;
  gg_precision: number;
  overall_accuracy: number;
}

export interface ROIStats {
  stake_per_bet: number;
  // Strategy = bet only the EV-suggested market; the rest is the
  // bet-everything model-health baseline (expected ≈ −vig).
  strategy_bets: number;
  strategy_staked: number;
  strategy_return: number;
  strategy_pnl: number;
  strategy_roi_pct: number;
  result_bets: number;
  result_staked: number;
  result_return: number;
  result_pnl: number;
  result_roi_pct: number;
  goals_bets: number;
  goals_staked: number;
  goals_return: number;
  goals_pnl: number;
  goals_roi_pct: number;
  btts_bets: number;
  btts_staked: number;
  btts_return: number;
  btts_pnl: number;
  btts_roi_pct: number;
  total_bets: number;
  total_staked: number;
  total_return: number;
  total_pnl: number;
  total_roi_pct: number;
  // Fair-value ROI (bookmaker vig removed) — pure model skill vs the fair line.
  fair_available: boolean;
  result_pnl_fair: number;
  result_roi_fair_pct: number;
  goals_pnl_fair: number;
  goals_roi_fair_pct: number;
  btts_pnl_fair: number;
  btts_roi_fair_pct: number;
  total_pnl_fair: number;
  total_roi_fair_pct: number;
  goals_fair_is_estimated: boolean;
}

export interface EVDataPoint {
  date: string;
  daily_ev: number;
  daily_pnl: number;
  daily_pnl_fair: number;
  cumulative_ev: number;
  cumulative_pnl: number;
  cumulative_pnl_fair: number;
}

export interface CLVStats {
  bets: number;
  avg_clv_pct: number;
  beat_close_pct: number;
}

export interface InjuryAdjustmentStats {
  matches: number;
  raw_result_accuracy: number;
  adj_result_accuracy: number;
  raw_goals_accuracy: number;
  adj_goals_accuracy: number;
}

export interface RegimeSlice {
  regime: string;                 // "anchored" | "pure-model" | "pure-unified" | …
  from_date: string | null;
  to_date: string | null;
  stats: AccuracySlice;           // per-era accuracy — no methodology mixing
}

export interface MethodologyInfo {
  cutoff: string;          // ISO date the current market-independent model began
  settled_before: number;  // settled predictions from the prior (anchored) model
  settled_after: number;   // settled predictions from the current model
  regimes?: RegimeSlice[];
}

export interface StatsResponse {
  methodology: MethodologyInfo | null;
  rolling: RollingAccuracy;
  top_picks: TopPicksStats | null;
  by_league: LeagueBreakdown[];
  by_confidence: ConfidenceBreakdown[];                    // club only
  by_confidence_national?: ConfidenceBreakdown[];          // separate label semantics
  injury_adjustment?: InjuryAdjustmentStats | null;
  by_predicted_outcome: PredictedOutcomeBreakdown[];
  draw_stats: DrawStats;
  btts_stats: BTTSStats | null;
  calibration: CalibrationBucket[];
  btts_calibration: CalibrationBucket[];
  result_calibration: ResultCalibration | null;
  by_model_version: ModelVersionStats[];
  roi: ROIStats | null;
  clv: CLVStats | null;
  ev_series: EVDataPoint[];
  computed_at: string;
}

// ── Fetch helpers ─────────────────────────────────────────────────────────────

async function apiFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    cache: "no-store", // always fetch fresh — backend handles its own caching
  });
  if (!res.ok) {
    throw new Error(`API ${path} → ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

// ── Public API ────────────────────────────────────────────────────────────────

export async function getMatches(
  league?: string,
  limit = 40,
  offset = 0,
  status?: "upcoming" | "past",
  includePredictions = false,
  daysBack?: number,
  daysOffset?: number,
  daysAhead?: number,
  minOdds?: number,
  minConfidence?: string,
): Promise<Match[]> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (league) params.set("league", league);
  if (status) params.set("status", status);
  if (includePredictions) params.set("include_predictions", "true");
  if (daysBack != null) params.set("days_back", String(daysBack));
  if (daysOffset != null && daysOffset > 0) params.set("days_offset", String(daysOffset));
  if (daysAhead != null) params.set("days_ahead", String(daysAhead));
  if (minOdds != null) params.set("min_odds", String(minOdds));
  if (minConfidence) params.set("min_confidence", minConfidence);
  return apiFetch<Match[]>(`/matches?${params}`);
}

export function buildExportUrl(opts: {
  format?: "csv" | "json";
  league?: string;
  status?: string;
  minOdds?: number;
  minConfidence?: string;
  daysAhead?: number;
}): string {
  const params = new URLSearchParams();
  if (opts.format) params.set("format", opts.format);
  if (opts.league) params.set("league", opts.league);
  if (opts.status) params.set("status", opts.status);
  if (opts.minOdds != null) params.set("min_odds", String(opts.minOdds));
  if (opts.minConfidence) params.set("min_confidence", opts.minConfidence);
  if (opts.daysAhead != null) params.set("days_ahead", String(opts.daysAhead));
  return `${API_URL}/matches/export?${params}`;
}

export async function getMatch(id: number): Promise<Match> {
  return apiFetch<Match>(`/matches/${id}`);
}

export async function getPrediction(matchId: number): Promise<Prediction> {
  return apiFetch<Prediction>(`/predictions/${matchId}`);
}

export async function getStats(league?: string): Promise<StatsResponse> {
  const params = league ? `?league=${encodeURIComponent(league)}` : "";
  const res = await fetch(`${API_URL}/stats${params}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Stats → ${res.status} ${res.statusText}`);
  return res.json() as Promise<StatsResponse>;
}

export async function getPostmortem(matchId: number): Promise<{ analysis: string }> {
  const res = await fetch(`${API_URL}/predictions/${matchId}/postmortem`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Postmortem ${matchId} → ${res.status}`);
  return res.json() as Promise<{ analysis: string }>;
}

export async function getAnalysis(matchId: number): Promise<MatchAnalysis> {
  // No ISR cache — always fresh (odds change, and backend has its own 1h cache)
  const res = await fetch(`${API_URL}/predictions/${matchId}/analysis`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Analysis ${matchId} → ${res.status}`);
  return res.json() as Promise<MatchAnalysis>;
}

export async function getNationalAnalysis(predictionId: number): Promise<MatchAnalysis> {
  const res = await fetch(`${API_URL}/national/predictions/${predictionId}/analysis`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`National analysis ${predictionId} → ${res.status}`);
  return res.json() as Promise<MatchAnalysis>;
}

// ── Chat types ────────────────────────────────────────────────────────────────

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatResponse {
  reply: string;
}

// ── Chat API ──────────────────────────────────────────────────────────────────

export async function sendChat(
  message: string,
  history: ChatMessage[] = [],
): Promise<ChatResponse> {
  const res = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, history }),
    cache: "no-store",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Chat error ${res.status}`);
  }
  return res.json() as Promise<ChatResponse>;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

export const LEAGUES = [
  { code: "EPL",          label: "Premier League",    flag: "🏴󠁧󠁢󠁥󠁮󠁧󠁿" },
  { code: "Championship", label: "Championship",      flag: "🏴󠁧󠁢󠁥󠁮󠁧󠁿" },
  { code: "LeagueOne",    label: "League One",        flag: "🏴󠁧󠁢󠁥󠁮󠁧󠁿" },
  { code: "LaLiga",       label: "La Liga",            flag: "🇪🇸" },
  { code: "SerieA",       label: "Serie A",            flag: "🇮🇹" },
  { code: "Bundesliga",   label: "Bundesliga",         flag: "🇩🇪" },
  { code: "Ligue1",       label: "Ligue 1",            flag: "🇫🇷" },
  { code: "GreekSL",      label: "Super League",       flag: "🇬🇷" },
  { code: "PrimeiraLiga", label: "Primeira Liga",      flag: "🇵🇹" },
  { code: "Eredivisie",   label: "Eredivisie",         flag: "🇳🇱" },
  { code: "BrazilSerieA", label: "Brasileirão",        flag: "🇧🇷" },
  { code: "CL",           label: "Champions League",  flag: "⭐" },
  { code: "EL",           label: "Europa League",     flag: "🟠" },
  { code: "ECL",          label: "Conference League", flag: "🟢" },
  { code: "ClubFriendly", label: "Club Friendlies",   flag: "🤝" },
] as const;

export type LeagueCode = (typeof LEAGUES)[number]["code"];

/** Synthetic league code used for national-team fixtures merged into the
 *  club fixture lists. Not a real league in LEAGUES — routed to /national. */
export const INTERNATIONAL_LEAGUE = "International";

/**
 * Resolve a user-supplied league string (query param — any case) to its
 * canonical code, or undefined when we don't cover that league. Callers must
 * NOT forward an unresolved code to the API: the backend answers 400 for
 * unknown leagues, which the fixture grids used to swallow and misreport as
 * "Could not reach the API" (e.g. ?league=Brasileirao — a league we simply
 * don't carry).
 */
export function canonicalLeagueCode(input?: string): string | undefined {
  if (!input) return undefined;
  const low = input.toLowerCase();
  if (low === INTERNATIONAL_LEAGUE.toLowerCase()) return INTERNATIONAL_LEAGUE;
  return LEAGUES.find((l) => l.code.toLowerCase() === low)?.code;
}

export function leagueLabel(code: string): string {
  if (code === INTERNATIONAL_LEAGUE) return "International";
  return LEAGUES.find((l) => l.code === code)?.label ?? code;
}

export function leagueFlag(code: string): string {
  if (code === INTERNATIONAL_LEAGUE) return "🌍";
  return LEAGUES.find((l) => l.code === code)?.flag ?? "🌍";
}

/** Compact European tie-round label: "1st Qualifying Round" → "Q1",
 *  "Play-off Round" → "PO". Group stage / knockout / domestic (null) → null. */
export function roundLabel(round?: string | null): string | null {
  if (!round) return null;
  const m = round.match(/(\d+)(?:st|nd|rd|th)?\s+Qualifying/i);
  if (m) return `Q${m[1]}`;
  if (/play-?off/i.test(round)) return "PO";
  return null;
}

/** Detail-page link for a match card. National fixtures live under /national. */
export function matchHref(m: Match): string {
  return m.league === INTERNATIONAL_LEAGUE
    ? `/national/${m.id}`
    : `/matches/${m.id}`;
}

/** YYYY-MM-DD (Europe/Athens) offset by `offsetDays` from now. */
export function athensDate(offsetDays = 0): string {
  const d = new Date(Date.now() + offsetDays * 86_400_000);
  return d.toLocaleDateString("en-CA", { timeZone: DISPLAY_TZ });
}

export function confidenceColor(confidence: string): string {
  if (confidence === "high")   return "text-green-400";
  if (confidence === "medium") return "text-yellow-400";
  return "text-gray-400";
}

export function confidenceDot(confidence: string): string {
  if (confidence === "high")   return "bg-green-400";
  if (confidence === "medium") return "bg-yellow-400";
  return "bg-gray-500";
}

// All date/time rendering is locked to Greece so output is identical whether
// the code runs server-side (SSR), in Athens, or in any other timezone — the
// app is a Greek-audience product.
export const DISPLAY_TZ = "Europe/Athens";

export function formatDate(dateStr: string): string {
  // Anchor at noon UTC so the Europe/Athens-rendered weekday/day never slips
  // across midnight because of the timezone offset.
  const d = new Date(`${dateStr}T12:00:00Z`);
  return d.toLocaleDateString("en-GB", {
    timeZone: DISPLAY_TZ,
    weekday:  "short",
    day:      "numeric",
    month:    "short",
  });
}

/**
 * Long-form day header, e.g. "Σάββατο, 18 Απριλίου 2026".  Used above the
 * per-day fixture grids.  Locked to Europe/Athens so SSR and client render
 * identically regardless of where the request originates.
 */
export function formatLongDate(dateStr: string, locale = "el-GR"): string {
  const d = new Date(`${dateStr}T12:00:00Z`);
  return d.toLocaleDateString(locale, {
    timeZone: DISPLAY_TZ,
    weekday:  "long",
    day:      "numeric",
    month:    "long",
    year:     "numeric",
  });
}

/**
 * Format a UTC kick-off time ("HH:MM:SS") for display in Greece.  A 17:30 UTC
 * match is rendered as "20:30" (EEST) — every user sees the same Greek clock
 * time regardless of where the browser is, and SSR output matches the client.
 * Returns null when no time is known.
 */
export function formatKickoff(
  dateStr: string,
  kickoffTime: string | null,
): string | null {
  if (!kickoffTime) return null;
  const iso = `${dateStr}T${kickoffTime.length === 5 ? kickoffTime + ":00" : kickoffTime}Z`;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;
  return d.toLocaleTimeString("en-GB", {
    timeZone: DISPLAY_TZ,
    hour:     "2-digit",
    minute:   "2-digit",
    hour12:   false,
  });
}

/**
 * Format a full UTC kick-off instant (ISO string) as Greek wall-clock time,
 * e.g. "05:00". Used for national fixtures where kickoff_utc is a complete
 * datetime (US evening games cross midnight in UTC, so date+time-of-day
 * composition would render the wrong moment). Returns null when absent.
 */
export function formatKickoffUtc(iso: string | null, matchDate?: string): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;
  const time = d.toLocaleTimeString("en-GB", {
    timeZone: DISPLAY_TZ,
    hour:     "2-digit",
    minute:   "2-digit",
    hour12:   false,
  });
  // When the Greek calendar day differs from the listed matchday (late US
  // games land in the small hours of the next day in Athens), flag it.
  if (matchDate) {
    const athensDay = d.toLocaleDateString("en-CA", { timeZone: DISPLAY_TZ });
    if (athensDay > matchDate) return `${time} +1`;
  }
  return time;
}

/**
 * Format a full kick-off date + time in Greece, e.g. "Sat 18 Apr, 20:30".
 * Useful for match-detail headers where a single line should convey both.
 */
export function formatKickoffDateTime(
  dateStr: string,
  kickoffTime: string | null,
): string {
  const time = formatKickoff(dateStr, kickoffTime);
  const date = formatDate(dateStr);
  return time ? `${date}, ${time}` : date;
}

/**
 * Returns true when the match has been under way for 2+ hours and can safely
 * be considered finished even if the score hasn't been scraped yet.  Used to
 * suppress the live Claude analysis panel — there's no point re-calling the
 * API after the match is decided.  The 2-hour rule uses absolute time, so
 * the Greek-display timezone doesn't affect this calculation.  Falls back to
 * false when kickoff_time is unknown (legacy fixtures).
 */
export function hasMatchEnded(
  dateStr: string,
  kickoffTime: string | null,
): boolean {
  if (!kickoffTime) return false;
  const iso = `${dateStr}T${kickoffTime.length === 5 ? kickoffTime + ":00" : kickoffTime}Z`;
  return hasMatchEndedUtc(iso);
}

/**
 * Like hasMatchEnded but from a full UTC kick-off instant (ISO). Correct for
 * fixtures whose UTC date differs from the listed match_date (late US games),
 * where the date+time-of-day form would build the wrong moment. Returns false
 * when the instant is unknown.
 */
export function hasMatchEndedUtc(kickoffUtc: string | null): boolean {
  if (!kickoffUtc) return false;
  const kickoff = new Date(kickoffUtc);
  if (isNaN(kickoff.getTime())) return false;
  return Date.now() >= kickoff.getTime() + 2 * 60 * 60 * 1000;
}

// ── National team types ───────────────────────────────────────────────────────

export interface NationalPrediction {
  id: number;
  match_date: string;
  /** Full UTC kick-off instant (ISO) — null when no odds event matched yet. */
  kickoff_utc: string | null;
  home_team: string;
  away_team: string;
  tournament: string;
  neutral: boolean;
  home_win_prob: number;
  draw_prob: number;
  away_win_prob: number;
  prediction: string;           // "H" | "D" | "A"
  confidence: string;           // "HIGH" | "MEDIUM" | "LOW"
  over_2_5_prob: number;
  btts_prob: number | null;
  bm_home_odds: number | null;
  bm_draw_odds: number | null;
  bm_away_odds: number | null;
  bm_over_odds: number | null;
  bm_btts_yes_odds: number | null;
  bm_btts_no_odds: number | null;
  num_bookmakers: number | null;
  ev_score: number | null;
  suggested_market: string | null;
  exp_home_cards: number | null;
  exp_away_cards: number | null;
  exp_home_corners: number | null;
  exp_away_corners: number | null;
  corners_over_9_5_prob: number | null;
  most_likely_score: string | null;
  top_scores: { score: string; prob: number }[] | null;
  h_elo: number | null;
  a_elo: number | null;
  actual_result: string | null;
  actual_home_goals: number | null;
  actual_away_goals: number | null;
  // Settlement ("what we caught") — populated only for finished matches.
  actual_home_corners: number | null;
  actual_away_corners: number | null;
  corners_hit: boolean | null;
  actual_home_cards: number | null;
  actual_away_cards: number | null;
  cards_hit: boolean | null;
  score_hit: boolean | null;
  score_in_top: boolean | null;
}

export interface NationalPredictionList {
  count: number;
  predictions: NationalPrediction[];
}

export interface NationalDrawStats {
  total_draws: number;
  predicted_draws: number;
  recall: number;
  precision: number;
}

export interface NationalTournamentStats {
  tournament: string;
  total: number;
  result_accuracy: number;
  over_accuracy: number;
  both_accuracy: number;
  result_correct: number;
  over_correct: number;
  both_correct: number;
}

export interface NationalConfidenceStats {
  confidence: string;
  total: number;
  result_correct: number;
  result_accuracy: number;
}

export interface NationalStatsResponse {
  total: number;
  result_accuracy: number;
  result_correct: number;
  over_accuracy: number;
  over_correct: number;
  both_correct: number;
  both_accuracy: number;
  draw_stats: NationalDrawStats;
  by_tournament: NationalTournamentStats[];
  by_confidence: NationalConfidenceStats[];
}

export interface NationalTrainingMetrics {
  available: boolean;
  trained_at?: string;
  n_train?: number;
  n_cal?: number;
  n_test?: number;
  test_start?: string;
  result_accuracy?: number;
  result_home_recall?: number;
  result_draw_recall?: number;
  result_away_recall?: number;
  result_home_precision?: number;
  result_draw_precision?: number;
  result_away_precision?: number;
  goals_accuracy?: number;
  goals_over_recall?: number;
  goals_under_recall?: number;
  btts_accuracy?: number;
  btts_gg_recall?: number;
  btts_ng_recall?: number;
  draw_raw_mean?: number;
  draw_cal_mean?: number;
  draw_actual_rate?: number;
  draw_blend_alpha?: number;
}

// ── National team API helpers ─────────────────────────────────────────────────

/** Earliest date with LIVE (pre-match) national predictions — before this is
 *  the 2024+ backfilled replay used for calibration, not user-facing feeds. */
export const NATIONAL_LIVE_SINCE = "2026-06-01";

export async function getNationalPredictions(opts: {
  tournament?: string;
  from?: string;
  to?: string;
  confidence?: string;
  prediction?: string;
  order?: "asc" | "desc";
  limit?: number;
} = {}): Promise<NationalPredictionList> {
  const params = new URLSearchParams();
  if (opts.tournament) params.set("tournament", opts.tournament);
  if (opts.from)       params.set("from", opts.from);
  if (opts.to)         params.set("to", opts.to);
  if (opts.confidence) params.set("confidence", opts.confidence);
  if (opts.prediction) params.set("prediction", opts.prediction);
  if (opts.order)      params.set("order", opts.order);
  if (opts.limit != null) params.set("limit", String(opts.limit));
  return apiFetch<NationalPredictionList>(`/national/predictions?${params}`);
}

export async function getNationalPrediction(id: number): Promise<NationalPrediction> {
  return apiFetch<NationalPrediction>(`/national/predictions/${id}`);
}

// ── Player props ──────────────────────────────────────────────────────────────

export interface PlayerProp {
  team: string;
  player_name: string;
  exp_minutes: number | null;
  exp_goals: number | null;
  p_score: number | null;
  p_sot_1: number | null;
  p_sot_2: number | null;
  p_assist: number | null;
  // Settlement ("what we caught") — only when the match is finished.
  played: boolean | null;
  actual_minutes: number | null;
  actual_goals: number | null;
  actual_sot: number | null;
  actual_assists: number | null;
  score_hit: boolean | null;
  sot_hit: boolean | null;
  assist_hit: boolean | null;
}

export interface PlayerPropsResponse {
  prediction_id: number;
  teams: Record<string, PlayerProp[]>;
  finished?: boolean;
}

export async function getPlayerProps(predictionId: number): Promise<PlayerPropsResponse> {
  return apiFetch<PlayerPropsResponse>(`/national/predictions/${predictionId}/player-props`);
}

/** Club player props — computed live from player_match_stats (no prediction_id). */
export async function getClubPlayerProps(matchId: number): Promise<PlayerPropsResponse> {
  return apiFetch<PlayerPropsResponse>(`/predictions/${matchId}/player-props`);
}

// ── League standings ─────────────────────────────────────────────────────────

export interface StandingRow {
  position: number;
  team: string;
  played: number;
  won: number;
  drawn: number;
  lost: number;
  goals_for: number;
  goals_against: number;
  goal_diff: number;
  points: number;
  /** "top" = Europe/promotion (or UEFA direct R16), "playoff" = UEFA knockout
   *  play-off (9–24), "bottom" = relegation/eliminated, null = mid-table. */
  zone: "top" | "playoff" | "bottom" | null;
}

export interface Standings {
  league: string;
  season: string;
  /** True once the season has no fixtures left — the UI says "final" rather
   *  than implying the table is still moving. */
  is_final: boolean;
  /** What the top zone grants here: "Champions League" / "Promotion" /
   *  "Round of 16" (UEFA league phase) … */
  top_zone: string;
  /** UEFA league phase only: positions 9–24 go to the knockout play-off.
   *  null for domestic leagues, which have no middle zone. */
  playoff_zone: string | null;
  bottom_zone: string;
  top_n: number;
  playoff_to: number;
  bottom_n: number;
  rows: StandingRow[];
}

/** Standings for a league. 404s when the league has no played matches yet. */
export async function getStandings(league: string, season?: string): Promise<Standings> {
  const qs = season ? `?season=${encodeURIComponent(season)}` : "";
  return apiFetch<Standings>(`/standings/${encodeURIComponent(league)}${qs}`);
}

export interface ProjectionTeam {
  team: string;
  p_title: number;
  /** Finishing in the top zone — Champions League, promotion, Libertadores… */
  p_top: number;
  p_relegated: number;
  exp_points: number;
}

export interface LeagueProjection {
  league: string;
  season: string;
  sims: number;
  matches_played: number;
  matches_remaining: number;
  top_zone: string;
  top_n: number;
  bottom_n: number;
  /** Present for play-off leagues (Greek SL): warns that only the regular
   *  season is simulated and the play-offs decide the title. */
  note?: string | null;
  teams: ProjectionTeam[];
}

export interface EuropeanProjectionTeam {
  team: string;
  p_champion: number;
  p_final: number;
  /** Reaching the last 16 (top 8 go direct; 9–24 must win the play-off). */
  p_r16: number;
}

/** A UEFA competition projects to a trophy, not a table position — so it is a
 *  different shape from the domestic one, not a superset of it. */
export interface EuropeanProjection {
  league: string;
  season: string;
  sims: number;
  matches_played: number;
  matches_remaining: number;
  teams: EuropeanProjectionTeam[];
}

export type SeasonProjection = LeagueProjection | EuropeanProjection;

/** Discriminates the two projection shapes: only the domestic one names a
 *  top zone (Champions League / Promotion / …). */
export function isEuropeanProjection(p: SeasonProjection): p is EuropeanProjection {
  return !("top_zone" in p);
}

export interface ProjectionHistoryTeam {
  team: string;
  /** Model title (league) or champion (European) probability that day. */
  prob: number;
  /** De-vigged bookmaker probability, when a market was offered. */
  market_pct?: number | null;
}

export interface ProjectionHistorySnapshot {
  date: string;
  league: string;
  season: string | null;
  matches_remaining: number | null;
  teams: ProjectionHistoryTeam[];
}

export interface ProjectionHistory {
  available: boolean;
  snapshots: ProjectionHistorySnapshot[];
}

/** Daily model-vs-market odds history for a competition's title race. Always
 *  200 (with available:false until the first snapshot is stored). */
export async function getProjectionHistory(league: string): Promise<ProjectionHistory> {
  return apiFetch<ProjectionHistory>(
    `/standings/${encodeURIComponent(league)}/projection/history`,
  );
}

/** Monte Carlo season projection. 404s when there is nothing honest to project:
 *  a finished season, a play-off format whose fixtures we refuse to guess
 *  (Greek Super League), or a UEFA competition still in qualifying — where the
 *  league-phase field doesn't exist yet. */
export async function getLeagueProjection(league: string): Promise<SeasonProjection> {
  return apiFetch<SeasonProjection>(`/standings/${encodeURIComponent(league)}/projection`);
}

/**
 * Adapt a NationalPrediction into the club `Match` shape so it can render in
 * the shared MatchCard / TopPicks UI and be merged into the home fixture list.
 * league is set to INTERNATIONAL_LEAGUE so matchHref() routes it to /national.
 */
export function nationalToMatch(np: NationalPrediction): Match {
  // MatchCard composes match_date + kickoff_time as a single UTC moment, so a
  // bare time-of-day is only safe when the UTC calendar date equals our local
  // match_date — US evening games cross midnight in UTC and would render the
  // wrong moment; those fall back to the date label.
  const kickoffTime =
    np.kickoff_utc && np.kickoff_utc.slice(0, 10) === np.match_date
      ? np.kickoff_utc.slice(11, 19)
      : null;

  // Group/display by the Athens calendar day the match is actually played, not
  // the source "matchday": a late kick-off (e.g. 00:00 UTC = 03:00 Athens) is
  // the NEXT day locally. Using the source date put such games under the wrong
  // (yesterday) header and dropped them from "Upcoming" once that day passed.
  const displayDate = np.kickoff_utc
    ? new Date(np.kickoff_utc).toLocaleDateString("en-CA", { timeZone: DISPLAY_TZ })
    : np.match_date;

  return {
    id:           np.id,
    league:       INTERNATIONAL_LEAGUE,
    season:       "",
    match_date:   displayDate,
    kickoff_time: kickoffTime,
    // Full instant — lets MatchCard show a real time ("04:00 +1") even when
    // the UTC date crosses midnight and kickoff_time above had to be null.
    kickoff_utc:  np.kickoff_utc ?? null,
    home_team:    np.home_team,
    away_team:    np.away_team,
    home_goals:   np.actual_home_goals,
    away_goals:   np.actual_away_goals,
    result:       (np.actual_result as Match["result"]) ?? null,
    created_at:   "",
    prediction: {
      home_win_prob:    np.home_win_prob,
      draw_prob:        np.draw_prob,
      away_win_prob:    np.away_win_prob,
      over_2_5_prob:    np.over_2_5_prob,
      goals_prediction: np.over_2_5_prob >= 0.5 ? "OVER" : "UNDER",
      model_version:    "national",
      confidence:       (np.confidence?.toLowerCase() as PredictionEmbed["confidence"]) ?? "low",
      suggested_market: np.suggested_market,
      ev_score:         np.ev_score,
    },
  };
}

/** Upcoming national fixtures within [from, to], adapted to Match shape. */
export async function getUpcomingNationalMatches(
  from: string,
  to: string,
  limit = 200,
  minOdds?: number,
): Promise<Match[]> {
  // Fetch a day EARLIER than the local "from": a match dated (source) yesterday
  // can kick off after midnight UTC and still be in the future (e.g. 00:00 UTC =
  // 03:00 Athens). We then decide "upcoming" by the kickoff INSTANT, not the
  // source match_date — a 2 h grace keeps a just-started game briefly visible.
  const fetchFrom = new Date(new Date(`${from}T00:00:00Z`).getTime() - 86_400_000)
    .toISOString()
    .slice(0, 10);
  const { predictions } = await getNationalPredictions({ from: fetchFrom, to, limit });
  const cutoffMs = Date.now() - 2 * 60 * 60 * 1000;
  return predictions
    .filter((np) => np.actual_result == null)   // not yet settled
    .filter((np) => !np.kickoff_utc || new Date(np.kickoff_utc).getTime() >= cutoffMs)
    .filter((np) => {
      if (minOdds == null) return true;
      // Same semantics as the club min-odds filter: the bookmaker odds of the
      // model's PICKED (argmax) outcome must be ≥ minOdds. Matches with no
      // bookmaker odds can't satisfy a threshold → excluded.
      const cands: { prob: number; odds: number | null }[] = [
        { prob: np.home_win_prob, odds: np.bm_home_odds },
        { prob: np.draw_prob,     odds: np.bm_draw_odds },
        { prob: np.away_win_prob, odds: np.bm_away_odds },
      ];
      cands.sort((a, b) => b.prob - a.prob);
      const pickOdds = cands[0].odds;
      return pickOdds != null && pickOdds >= minOdds;
    })
    .map(nationalToMatch);
}

/** Past national fixtures (with actual result) within [from, to], adapted to Match shape. */
export async function getPastNationalMatches(
  from: string,
  to: string,
  limit = 200,
): Promise<Match[]> {
  const { predictions } = await getNationalPredictions({ from, to, limit });
  return predictions
    .filter((np) => np.actual_result !== null)  // results only
    .map(nationalToMatch);
}

export async function getNationalTournaments(): Promise<string[]> {
  const data = await apiFetch<{ tournaments: string[] }>("/national/tournaments");
  return data.tournaments;
}

export async function getNationalStats(): Promise<NationalStatsResponse> {
  return apiFetch<NationalStatsResponse>("/national/stats");
}

export async function getNationalTrainingMetrics(): Promise<NationalTrainingMetrics> {
  return apiFetch<NationalTrainingMetrics>("/national/training-metrics");
}

// ── World Cup Monte Carlo simulation ──────────────────────────────────────────

export interface WcSimTeam {
  team: string;
  win_pct: number;
  final_pct: number;
  market_pct: number | null;
}

export interface WcSimPairing {
  team_a: string;
  team_b: string;
  pct: number;
}

export interface WcGoldenBootPlayer {
  player: string;
  team: string;
  /** P(wins the Golden Boot) across simulations. */
  gb_pct: number;
  /** Expected tournament goals. */
  exp_goals: number;
  /** P(scores 4 or more goals). */
  p4plus: number;
  /** De-vigged bookmaker top-scorer probability, or null when no market. */
  market_pct?: number | null;
}

export interface WcGoldenBoot {
  players: WcGoldenBootPlayer[];
  /** P(an unlisted "field" player tops the scoring) — honesty bucket. */
  field_pct: number;
  /** True when shares were restricted to the official call-ups (wc_squads.json). */
  squad_filtered?: boolean;
  /** True when a bookmaker top-scorer market was available to compare against. */
  has_market?: boolean;
  /** True when injured/suspended players were excluded (wc_unavailable.json). */
  availability_filtered?: boolean;
  /** Count of injured/suspended players excluded across all teams. */
  unavailable_count?: number;
}

export interface WcGroupTeam {
  team: string;
  /** P(finish 1st in the group). */
  p_first: number;
  /** P(finish top-2). */
  p_top2: number;
  /** P(qualify — top-2 or one of the 8 best third-placed teams). */
  p_qualify: number;
}

export interface WcSimulation {
  available: boolean;
  generated_at?: string;
  n_sims?: number;
  /** Group games already played that the projection is conditioned on. */
  played_games?: number;
  remaining_games?: number;
  has_market?: boolean;
  /** True once knockouts are simulated on the real bracket (exact pairings). */
  real_bracket?: boolean;
  teams?: WcSimTeam[];
  pairings?: WcSimPairing[];
  golden_boot?: WcGoldenBoot;
  groups?: Record<string, string[]>;
  group_standings?: Record<string, WcGroupTeam[]>;
}

export async function getWcSimulation(): Promise<WcSimulation> {
  return apiFetch<WcSimulation>("/national/wc-simulation");
}

export interface WcHistoryTeam {
  team: string;
  win_pct: number;
  market_pct: number | null;
}

export interface WcHistorySnapshot {
  date: string;            // ISO "YYYY-MM-DD"
  generated_at: string;
  n_sims: number;
  played_games: number;
  teams: WcHistoryTeam[];
}

export interface WcChampionHistory {
  available: boolean;
  snapshots: WcHistorySnapshot[];
}

export async function getWcChampionHistory(): Promise<WcChampionHistory> {
  return apiFetch<WcChampionHistory>("/national/wc-champion-history");
}

export interface MarketRecordRow {
  market: string;
  is_base: boolean;
  proven: boolean;
  demoted: boolean;
  tracked_total: number;
  settled: number;
  wins: number;
  win_pct: number | null;
  roi_pct: number | null;
  samples_to_promote: number;
}

export interface MarketRecord {
  source?: string;
  cutoff: string;
  min_samples: number;
  rolling_window?: number;
  roi_floor_pct: number;
  demote_min_samples: number;
  demote_roi_ceil_pct: number;
  markets: MarketRecordRow[];
}

export interface GateChange {
  at: string;             // ISO timestamp
  source: string;         // "club" | "national"
  promoted: string[];
  demoted: string[];
  now: string[];          // proven set after the change
}

export interface WcReviewHighlight {
  home: string;
  away: string;
  score: string | null;
  pick: string;      // "H" | "D" | "A"
  prob: number;
}

export interface WcReview {
  available: boolean;
  settled?: number;
  result_accuracy?: number;
  result_correct?: number;
  ou_accuracy?: number | null;
  ou_total?: number;
  high_conf_n?: number;
  high_conf_accuracy?: number | null;
  champ_favorite?: { team: string; win_pct: number | null } | null;
  highlights?: WcReviewHighlight[];
}

export async function getWcReview(): Promise<WcReview> {
  return apiFetch<WcReview>("/national/wc-review");
}
