/**
 * Lightweight bilingual (English / Greek) i18n for the App Router.
 *
 * Works in BOTH server and client components off a single flat message table:
 *   - Server components: `getServerT()` from `@/lib/i18n-server` (reads the cookie).
 *   - Client components: `useT()` from `@/components/LanguageProvider`.
 *
 * The active language is stored in a first-party `locale` cookie so server and
 * client render the same thing (no hydration mismatch). The header flag toggle
 * writes the cookie and refreshes.
 *
 * Keys are namespaced with dots (e.g. "nav.upcoming", "roi.header"). Missing
 * keys fall back to English, then to the raw key — so a half-translated build
 * never renders blank.
 */

export type Lang = "en" | "el";

export const LOCALE_COOKIE = "locale";
export const DEFAULT_LANG: Lang = "en";

export function normalizeLang(v: string | undefined | null): Lang {
  return v === "el" ? "el" : "en";
}

type Table = Record<string, string>;

/** Interpolate {name} placeholders. */
function interpolate(s: string, vars?: Record<string, string | number>): string {
  if (!vars) return s;
  return s.replace(/\{(\w+)\}/g, (_, k) => (k in vars ? String(vars[k]) : `{${k}}`));
}

export type TFunc = (key: string, vars?: Record<string, string | number>) => string;

export function getT(lang: Lang): TFunc {
  const table: Table = messages[lang] ?? messages[DEFAULT_LANG];
  const fallback: Table = messages[DEFAULT_LANG];
  return (key, vars) => {
    const raw = table[key] ?? fallback[key] ?? key;
    return interpolate(raw, vars);
  };
}

// ── Message tables ─────────────────────────────────────────────────────────────
// EN is the source of truth; EL mirrors every key. Keep the two blocks in sync.

const en: Table = {
  // Header / nav
  "brand": "Football Predictor",
  "nav.upcoming": "Upcoming",
  "nav.recent": "Recent Results",
  "nav.projections": "🔮 Projections",
  "nav.worldCup": "🏆 World Cup 2026",
  "nav.stats": "📊 Stats",

  // Footer
  "footer.disclaimer": "ML predictions for entertainment only · ~52% result / ~58% O/U accuracy ·",
  "footer.notFinancial": "Not financial advice",
  "footer.coffee": "☕ Buy me a coffee",

  // Language toggle
  "lang.english": "English",
  "lang.greek": "Greek",

  // Notification bell
  "bell.aria": "Platform updates",
  "bell.title": "🔔 Platform updates",
  "bell.subtitle": "Fixes & improvements to the predictor",
  "bell.close": "Close",
  "bell.tag.new": "New",
  "bell.tag.improvement": "Improved",
  "bell.tag.fix": "Fixed",

  // ── Stats page ──
  "stats.unavailable.title": "Stats unavailable",
  "stats.unavailable.body": "No completed matches with predictions yet — check back after the next match day.",
  "stats.intl.title": "📊 International Model Accuracy",
  "stats.intl.subtitle": "National team predictions · {n} completed matches.",
  "stats.intl.empty": "No international results yet.",
  "stats.allTimeN": "All Time · {n} matches",
  "stats.resultAccuracy": "Result Accuracy",
  "stats.ouAccuracy": "O/U Accuracy",
  "stats.bothCorrect": "Both Correct",
  "stats.matchesTracked": "Matches Tracked",
  "stats.correctFrac": "{c} / {t} correct",
  "stats.frac": "{c} / {t}",
  "stats.withStored": "with stored predictions",
  "stats.byTournament": "By Tournament",
  "stats.byConfidence": "By Confidence Level",
  "stats.drawPrediction": "Draw Prediction",
  "stats.totalDraws": "Total Draws",
  "stats.drawPredictions": "Draw Predictions",
  "stats.drawRecall": "Draw Recall",
  "stats.drawPrecision": "Draw Precision",
  "stats.actualDraws": "actual draws",
  "stats.predictedAsDraw": "predicted as draw",
  "stats.ofActualDrawsCaught": "of actual draws caught",
  "stats.ofDrawPredsCorrect": "of draw preds correct",
  "stats.nMatches": "{n} matches",
  "stats.resultAccuracyBar": "Result accuracy",
  "stats.title": "📊 Model Accuracy",
  "stats.subtitle": "Live accuracy tracking across all completed matches with ML predictions. Refreshed every hour · last computed {when}.",
  "stats.methodology.title": "⚠️ Model change — {cutoff}",
  "stats.methodology.body": "The model became market-independent on {cutoff} (market features + anchoring removed). The {before} games before then were served by the old (anchored) model, while {after} by the current one. The “All Time” numbers below mix the two methodologies — the rolling 7d/30d are more representative of the current model.",
  "stats.methodology.regime": "Model period",
  "stats.methodology.now": "now",
  "stats.injury.title": "🩹 Injury adjustment — measured effect",
  "stats.injury.body": "Same {n} games, same model — only the injury layer changes.",
  "stats.topPicks.title": "Top AI Picks — historical accuracy",
  "stats.topPicks.caption": "Top 3 per day · high confidence → higher probability",
  "stats.topPicks.accuracy": "Accuracy",
  "stats.topPicks.correctN": "{c} / {t} correct",
  "stats.topPicks.vsOverall": "Vs Overall",
  "stats.topPicks.diffFrom": "diff from {pct} overall",
  "stats.topPicks.avgProb": "Avg Probability",
  "stats.topPicks.topPickConfidence": "top pick confidence",
  "stats.topPicks.totalPicks": "Total Picks",
  "stats.topPicks.perMatchDay": "~3 per match day",
  "stats.topPicks.result": "1×2 Result",
  "stats.topPicks.ou": "Over/Under 2.5",
  "stats.topPicks.picks": "{n} picks",
  "stats.topPicks.note": "Same logic as the home page: top 3 matches per day ranked by high confidence → highest outcome probability. Counts whether the predicted outcome (Home Win / Away Win / Draw / Over / Under) was correct.",
  "stats.rollingPerformance": "Rolling Performance",
  "stats.last7": "Last 7 days",
  "stats.last30": "Last 30 days",
  "stats.result": "Result",
  "stats.ou": "O/U",
  "stats.both": "Both",
  "stats.byLeague": "By League",
  "stats.intlByTournament": "🌍 International — By Tournament",
  "stats.byConfidenceClub": "(club leagues)",
  "stats.confHelp": "High confidence = max outcome probability ≥ 55% AND signal on O/U · Medium ≥ 42% · Low < 42%",
  "stats.internationals": "Internationals",
  "stats.intlScale": "(separate scale: HIGH = p ≥ 65%)",
  "stats.byPredictedOutcome": "By Predicted Outcome",
  "stats.matchResult": "Match Result",
  "stats.homeWin": "🏠 Home win",
  "stats.draw": "🤝 Draw",
  "stats.awayWin": "✈️ Away win",
  "stats.overUnder": "Over / Under 2.5",
  "stats.over25": "⬆️ Over 2.5",
  "stats.under25": "⬇️ Under 2.5",
  "stats.totalDrawsSub": "actual draws in dataset",
  "stats.drawPredictionsSub": "matches predicted as draw",
  "stats.drawRecallSub": "of actual draws caught",
  "stats.drawPrecisionSub": "of draw predictions correct",
  "stats.drawNote": "Draws ({pct} of matches) are the hardest outcome to predict. Recall = what fraction of actual draws we caught · Precision = how reliable our draw calls are.",
  "stats.bttsTitle": "Goal / No Goal (BTTS)",
  "stats.bttsIntro": "{gg} = both teams scored at least 1 goal. {ng} = at least one team didn't score. The prediction is made via the Poisson model (from the stored λ).",
  "stats.bttsGG": "GG (Goal Goal)",
  "stats.bttsNG": "NG (No Goal)",
  "stats.bttsSample": "Sample",
  "stats.bttsCompletedWithLambda": "completed matches with λ",
  "stats.bttsOverallAcc": "Overall Accuracy",
  "stats.bttsCorrectGGNG": "{c} / {t} correct (GG+NG)",
  "stats.bttsGGAcc": "GG Accuracy",
  "stats.bttsGGPredsCorrect": "{c} / {t} GG predictions correct",
  "stats.bttsGGRecall": "GG Recall",
  "stats.bttsNGRecall": "NG Recall",
  "stats.bttsGGRecallSub": "Of {t} actual GG, we caught {c}",
  "stats.bttsNGRecallSub": "Of {t} actual NG, we caught {c}",
  "stats.bttsGGPredictions": "GG Predictions",
  "stats.bttsNGPredictions": "NG Predictions",
  "stats.bttsGGPredictedSub": "matches we predicted GG",
  "stats.bttsNGPredictedSub": "matches we predicted NG",
  "stats.roiTracker": "ROI Tracker",
  "stats.roiEmpty": "💰 ROI tracking starts once bookmaker odds are stored at prediction time.",
  "stats.roiEmptySub": "Re-run compute_predictions.py for upcoming matches to begin accumulating data.",
  "stats.cumEV": "Cumulative EV vs P&L",
  "stats.calibration": "Calibration",
  "stats.byModelVersion": "By Model Version",
  "stats.version": "Version",
  "stats.games": "Games",
  "stats.resultPct": "Result %",
  "stats.ouPct": "O/U %",

  // ── ROI card ──
  "roi.header": "💰 ROI Tracker — Value Strategy",
  "roi.subtitle": "Only ⚡ suggested bets · €{stake} flat · {n} bets",
  "roi.noStrategy": "No settled suggested bets yet",
  "roi.strategyRoi": "Strategy ROI",
  "roi.clvTitle": "📉 Closing Line Value",
  "roi.clvSub": "{n} bets with closing snapshot · positive CLV = real edge",
  "roi.beatClose": "beat close {pct}%",
  "roi.fairTitle": "🎯 Fair-value ROI — no vig",
  "roi.fairSub": "Same bets at fair (de-vigged) odds · model quality vs market",
  "roi.fairSuffix": "fair",
  "roi.vsWithVig": "vs −€{amt} ({pct}%) with vig",
  "roi.modelBaseline": "Model baseline (bet everything · {n} bets)",
  "roi.colWithVig": "with vig",
  "roi.colModelFair": "model (fair)",
  "roi.vig": "vig {amt}",
  "roi.market.result": "1×2 Result",
  "roi.market.goals": "Over 2.5 Goals",
  "roi.market.btts": "GG (BTTS)",
  "roi.bttsPending": "No stored BTTS odds yet",
  "roi.pending": "pending",
  "roi.betsStaked": "{bets} bets · €{staked} staked",
  "roi.decomp.real": "Real result (with vig)",
  "roi.decomp.model": "↳ from correct model results",
  "roi.decomp.vig": "↳ lost to vig (bookmaker margin)",
  "roi.disclaimer": "Strategy = flat stake only on ⚡ suggested value bets (with market-shrunk EV gate). The baseline bets on every prediction and is expected ≈ −vig — it's a model-health signal, not a strategy. Fair-value = same bets at de-vigged odds (Result & BTTS exactly; *O/U with a hypothetical 4% overround since we don't store under-2.5 odds). It's not an achievable return — nowhere can you bet at fair odds — but it cleanly measures model quality.",

  // ── Home page ──
  "home.wcReview.label": "World Cup 2026 review",
  "home.wcReview.mid": "— the model got",
  "home.wcReview.suffix": "of results right across {n} matches",
  "home.wcReview.cta": "See →",

  // ── Match card / prediction bars ──
  "matchCard.insufficient": "ℹ️ Insufficient data — unknown teams",
  "pred.ggLabel": "GG (both teams score)",
  "pred.ngLabel": "NG (at least one doesn't score)",

  // ── Recent result card ──
  "recent.loadFail": "Failed to load analysis.",
  "recent.analyzing": "Analyzing…",
  "recent.closeAnalysis": "▲ Close analysis",
  "recent.whyFail": "🔍 Why did it fail?",

  // ── Locked match card ──
  "locked.membersOnly": "Members-only prediction —",
  "locked.signupFree": "sign up free",

  // ── EV chart ──
  "ev.empty": "📈 Cumulative EV chart will appear once bookmaker odds are stored for completed matches.",
  "ev.emptySub": "Run compute_predictions.py to populate odds going forward.",
  "ev.title": "📈 Cumulative EV vs P&L",
  "ev.flatStake": "€10 flat stake · {n} days tracked",
  "ev.expectedValue": "Expected Value",
  "ev.actualPnl": "Actual P&L",
  "ev.fairPnl": "Fair P&L (no vig)",

  // ── Match detail (club) ──
  "match.insufficient.title": "Insufficient data for a prediction",
  "match.insufficient.body": "One or both teams aren't in the model's training history (usually qualifiers or teams from leagues we don't cover). The probabilities would just be default values — so we don't show them.",

  // ── National match detail ──
  "nat.cards.hitYes": "estimate ±1.5 ✓",
  "nat.cards.hitNo": "outside ±1.5",
  "nat.actualTotal": "Actual · total {n}",
  "nat.caught": "caught",
  "nat.missed": "missed",
  "nat.top6": "top-6",
  "nat.likelyScores": "🎯 Likely Scores",
  "nat.actualScore": "Actual score:",

  // ── Projection panels ──
  "proj.league.title": "🔮 Season Projection",
  "proj.league.desc": "{sims} simulations of the {n} remaining matches, from current Elo and standings. Doesn't account for transfers or injuries.",
  "proj.team": "Team",
  "proj.league.title2": "Title",
  "proj.league.releg": "Releg.",
  "proj.league.xpts": "xPts",
  "proj.eu.title": "🏆 Winner Projection",
  "proj.eu.desc": "{sims} simulations: {n} league-phase matches remaining, then playoff + knockouts to the final. The bracket comes from the standings order — the real draw hasn't happened.",
  "proj.eu.win": "Win",
  "proj.eu.final": "Final",
  "proj.eu.r16": "Ro16",
  "proj.eu.more": "+ {n} teams below 1%.",

  // ── Locked detail panel ──
  "locked.detail.title": "The full prediction for {home} – {away} is available to members only",
  "locked.detail.body": "1×2 probabilities, goals, BTTS, likely scores, comparison with 25 bookmakers and AI analysis — all free with an account. The day's top 3 picks always stay open on the home page.",
  "locked.detail.signup": "Free sign up",
  "locked.detail.login": "Log in",
  "locked.detail.seePre": "See the",
  "locked.detail.accuracy": "model accuracy",
  "locked.detail.seeMid": "and the",
  "locked.detail.recent": "recent results",
  "locked.detail.seeSuf": "— public, no sign-up.",

  // ── Player props panel ──
  "props.score": "Score",
  "props.scoreDef": "= scores",
  "props.shots": "Shots",
  "props.shotsDef": "= 1+ shot on target",
  "props.assist": "Assist",
  "props.assistDef": "= provides an assist.",
  "props.title": "👤 Player Stats",
  "props.descPre": "Per-player probability to:",
  "props.settledNote": "Below each probability: ✓/✗ what we caught + the actual number.",
  "props.methodNote": "(recency-weighted rates × expected goals)",

  // ── Standings table ──
  "st.title": "📋 Standings",
  "st.final": "final",
  "st.team": "Team",
  "st.p": "P",
  "st.w": "W",
  "st.d": "D",
  "st.l": "L",
  "st.gd": "GD",
  "st.pts": "Pts",
  "zone.championsLeague": "Champions League",
  "zone.promotion": "Promotion",
  "zone.europe": "Europe",
  "zone.libertadores": "Libertadores",
  "zone.round16": "Round of 16",
  "zone.playoff": "Play-off",
  "zone.relegation": "Relegation",
  "zone.eliminated": "Eliminated",

  // ── Projections browser ──
  "proj.filter.all": "All",
  "proj.filter.domestic": "Leagues",
  "proj.filter.european": "Europe",
  "proj.empty.title": "No projections available right now.",
  "proj.empty.body": "Long-term projections light up once each competition's season kicks off.",
  "proj.eu.pending.title": "Available after the league-phase draw",
  "proj.eu.pending.body": "The 36 participants are decided in the qualifiers being played now — a 'title probability' before the field is finalised would be invention, not estimation. The projection lights up automatically once the league-phase matches are in (late August).",

  // ── Projections page ──
  "projPage.title": "🔮 Long-term Projections",
  "projPage.desc": "Title, Europe and relegation probabilities per competition — Monte Carlo from current Elo and standings.",

  // ── World Cup group qualification ──
  "wc.groupQual": "📊 Group Qualification",
  "wc.first": "1st",
  "wc.firstDef": "= group winner",
  "wc.top2": "Top-2",
  "wc.top2Def": "= direct qualification",
  "wc.qualify": "Qualify",
  "wc.qualifyDef": "= top-2 or one of the 8 best 3rd-placed.",
  "wc.qualCol": "Qual",

  // ── Projection history chart ──
  "hist.title": "📈 Odds Evolution",
  "hist.empty": "The odds history appears after a few daily simulations — one snapshot per day.",
  "hist.legend": "(— model · - - market)",

  // ── Match analysis panel ──
  "ma.lockedCta": "🔒 Bookmaker comparison and AI analysis are members-only.",
  "ma.signup": "Free sign up",
  "ma.poissonGap": "⚠ Poisson ↔ XGBoost gap {pp}pp — indicative",
  "ma.analyticStats": "Analytic Stats",
  "ma.likelyScores": "Likely Scores",
  "ma.teal": "Teal = belongs to the dominant combo · Scores sum to 100%",
  "ma.comboMarkets": "Combo Markets",
  "ma.eg": "e.g.",
  "ma.aiAnalysis": "AI Analysis",
  "ma.win": "{team} win",
  "ma.draw": "Draw",
  "ma.ggFull": "GG (both teams score)",
  "ma.mostLikely": "Most likely outcome",
  "ma.watched": "Under watch (unproven)",
  "ma.modelVs": " · model {m}% vs market {k}%",
  "ma.marketOnly": " · market {k}%",
  "ma.watchNote": "The model sees edge here, but this market has no proven track record on the current model yet — we log it and it'll be promoted to a suggestion only if the data justifies it.",

  // ── Chat box ──
  "chat.suggest1": "Give me 3 high-confidence picks",
  "chat.suggest2": "Which of today's matches are over 2.5?",
  "chat.suggest3": "Best EPL matches this week?",
  "chat.suggest4": "Which draws are most likely?",
  "chat.error": "Something went wrong.",
  "chat.askMe": "Ask me about the match predictions",
  "chat.placeholder": "Type your question…",
  "chat.enterHint": "Enter to send · Shift+Enter for a new line",

  // ── Contact button ──
  "contact.emptyMsg": "Write a message first.",
  "contact.genericErr": "Something went wrong. Try again.",
  "contact.sendFail": "Failed to send. Check your connection.",
  "contact.title": "Send me ideas / suggestions",
  "contact.heading": "✉️ Contact",
  "contact.thanks": "Thanks! Your message was sent.",
  "contact.close": "Close",
  "contact.blurb": "Send me your ideas or suggestions for Football Predictor. I read them all.",
  "contact.placeholder": "Your idea / suggestion…",
  "contact.cancel": "Cancel",
  "contact.send": "Send",
  "contact.sending": "Sending…",

  // ── World Cup review ──
  "rev.outcome.H": "home win",
  "rev.outcome.D": "draw",
  "rev.outcome.A": "away win",
  "rev.emptyTitle": "Review not available yet.",
  "rev.emptyBody": "Fills in as World Cup matches complete.",
  "rev.settled": "Settled matches",
  "rev.settledSub": "with prediction + result",
  "rev.resultAcc": "Result accuracy",
  "rev.resultAccSub": "{c}/{t} correct (1×2)",
  "rev.highConf": "High-confidence",
  "rev.highConfSub": "{n} sure calls (≥55%)",
  "rev.ou": "Over/Under 2.5",
  "rev.ouSub": "{n} matches",
  "rev.champFav": "🏆 The model's title favourite (before the knockouts):",
  "rev.champProb": "({pct} probability)",
  "rev.sureCalls": "✅ Sure calls that landed",
  "rev.footPre": "Predictions were made before each match by the market-independent model (talent-adjusted Elo). See also the",
  "rev.detailedAcc": "detailed accuracy",
  "rev.title": "World Cup 2026 — Review",
  "rev.subtitle": "How the model did in the tournament.",
  "rev.backNational": "National teams →",

  // ── Admin: training ──
  "adminTr.deltaVsActual": "Δ = {pp}pp vs actual",
  "adminTr.subtitle": "Test-set accuracy, recall & calibration per retrain · times in Europe/Athens",
  "adminTr.dailyRetrain": "Retrain daily ~06:00 (self-correct on yesterday's results)",
  "adminTr.weeklyRetrain": "Retrain weekly (Mondays ~06:00) — off-season it changes slowly",
  "adminTr.noRuns": "No training runs yet. They'll appear after the next weekly retrain.",

  // ── Admin: gate changes ──
  "gate.descPre": "Every time a market enters (promoted) or leaves (demoted) the suggestable set, it's logged here — the same event that fires the",
  "gate.descPost": "webhook. Most recent first.",
  "gate.empty": "No changes yet. The base markets (Home Win / Draw) start proven; promotions/demotions show up here as a record builds.",

  // ── Admin: dashboard ──
  "admin.newMessages": "New messages",
  "admin.userMessages": "✉️ User messages",
  "admin.newBadge": "{n} new",

  // ── Admin: markets ──
  "markets.empty": "No recorded tickets yet.",

  // ── Admin: feedback ──
  "fb.empty": "No messages yet.",
  "fb.new": "NEW",
  "fb.reply": "Reply ↗",
  "fb.markRead": "Mark as read",
};

const el: Table = {
  // Header / nav
  "brand": "Football Predictor",
  "nav.upcoming": "Προσεχή",
  "nav.recent": "Πρόσφατα Αποτελέσματα",
  "nav.projections": "🔮 Προβλέψεις",
  "nav.worldCup": "🏆 Μουντιάλ 2026",
  "nav.stats": "📊 Στατιστικά",

  // Footer
  "footer.disclaimer": "Προβλέψεις ML μόνο για ψυχαγωγία · ~52% αποτέλεσμα / ~58% ακρίβεια O/U ·",
  "footer.notFinancial": "Δεν αποτελεί οικονομική συμβουλή",
  "footer.coffee": "☕ Κέρνα με έναν καφέ",

  // Language toggle
  "lang.english": "Αγγλικά",
  "lang.greek": "Ελληνικά",

  // Notification bell
  "bell.aria": "Ενημερώσεις πλατφόρμας",
  "bell.title": "🔔 Ενημερώσεις πλατφόρμας",
  "bell.subtitle": "Διορθώσεις & βελτιώσεις στον predictor",
  "bell.close": "Κλείσιμο",
  "bell.tag.new": "Νέο",
  "bell.tag.improvement": "Βελτίωση",
  "bell.tag.fix": "Διόρθωση",

  // ── Stats page ──
  "stats.unavailable.title": "Στατιστικά μη διαθέσιμα",
  "stats.unavailable.body": "Δεν υπάρχουν ακόμα ολοκληρωμένοι αγώνες με προβλέψεις — ξαναδοκίμασε μετά την επόμενη αγωνιστική.",
  "stats.intl.title": "📊 Ακρίβεια Μοντέλου (Εθνικές)",
  "stats.intl.subtitle": "Προβλέψεις εθνικών ομάδων · {n} ολοκληρωμένοι αγώνες.",
  "stats.intl.empty": "Δεν υπάρχουν ακόμα διεθνή αποτελέσματα.",
  "stats.allTimeN": "Συνολικά · {n} αγώνες",
  "stats.resultAccuracy": "Ακρίβεια Αποτελέσματος",
  "stats.ouAccuracy": "Ακρίβεια O/U",
  "stats.bothCorrect": "Και τα δύο σωστά",
  "stats.matchesTracked": "Αγώνες σε παρακολούθηση",
  "stats.correctFrac": "{c} / {t} σωστά",
  "stats.frac": "{c} / {t}",
  "stats.withStored": "με αποθηκευμένες προβλέψεις",
  "stats.byTournament": "Ανά Διοργάνωση",
  "stats.byConfidence": "Ανά Επίπεδο Βεβαιότητας",
  "stats.drawPrediction": "Πρόβλεψη Ισοπαλίας",
  "stats.totalDraws": "Σύνολο Ισοπαλιών",
  "stats.drawPredictions": "Προβλέψεις Ισοπαλίας",
  "stats.drawRecall": "Draw Recall",
  "stats.drawPrecision": "Draw Precision",
  "stats.actualDraws": "πραγματικές ισοπαλίες",
  "stats.predictedAsDraw": "προβλέφθηκαν ως ισοπαλία",
  "stats.ofActualDrawsCaught": "των πραγματικών ισοπαλιών πιάστηκαν",
  "stats.ofDrawPredsCorrect": "των προβλέψεων ισοπαλίας σωστές",
  "stats.nMatches": "{n} αγώνες",
  "stats.resultAccuracyBar": "Ακρίβεια αποτελέσματος",
  "stats.title": "📊 Ακρίβεια Μοντέλου",
  "stats.subtitle": "Ζωντανή παρακολούθηση ακρίβειας σε όλους τους ολοκληρωμένους αγώνες με προβλέψεις ML. Ανανέωση κάθε ώρα · τελευταίος υπολογισμός {when}.",
  "stats.methodology.title": "⚠️ Αλλαγή μοντέλου — {cutoff}",
  "stats.methodology.body": "Το μοντέλο έγινε market-independent στις {cutoff} (αφαιρέθηκαν market features + anchoring). Τα {before} παιχνίδια πριν σερβιρίστηκαν από το παλιό (anchored) μοντέλο, ενώ {after} από το τωρινό. Τα «Συνολικά» νούμερα παρακάτω αναμειγνύουν τις δύο μεθοδολογίες — τα rolling 7d/30d είναι πιο αντιπροσωπευτικά του τωρινού μοντέλου.",
  "stats.methodology.regime": "Περίοδος μοντέλου",
  "stats.methodology.now": "τώρα",
  "stats.injury.title": "🩹 Injury adjustment — μετρημένη επίδραση",
  "stats.injury.body": "Ίδια {n} παιχνίδια, ίδιο μοντέλο — μόνο το injury layer αλλάζει.",
  "stats.topPicks.title": "Top AI Picks — ιστορική ακρίβεια",
  "stats.topPicks.caption": "Top 3 ανά ημέρα · high confidence → μεγαλύτερη πιθανότητα",
  "stats.topPicks.accuracy": "Ακρίβεια",
  "stats.topPicks.correctN": "{c} / {t} σωστές",
  "stats.topPicks.vsOverall": "Vs Γενική",
  "stats.topPicks.diffFrom": "διαφορά από {pct} overall",
  "stats.topPicks.avgProb": "Μέση Πιθανότητα",
  "stats.topPicks.topPickConfidence": "confidence του top pick",
  "stats.topPicks.totalPicks": "Σύνολο Picks",
  "stats.topPicks.perMatchDay": "~3 ανά ημέρα παιχνιδιών",
  "stats.topPicks.result": "1×2 Αποτέλεσμα",
  "stats.topPicks.ou": "Over/Under 2.5",
  "stats.topPicks.picks": "{n} picks",
  "stats.topPicks.note": "Ίδια λογική με την αρχική σελίδα: top 3 αγώνες ανά ημέρα ταξινομημένοι κατά high confidence → μεγαλύτερη πιθανότητα αποτελέσματος. Μετράει αν η προβλεπόμενη έκβαση (Home Win / Away Win / Draw / Over / Under) ήταν σωστή.",
  "stats.rollingPerformance": "Κυλιόμενη Απόδοση",
  "stats.last7": "Τελευταίες 7 ημέρες",
  "stats.last30": "Τελευταίες 30 ημέρες",
  "stats.result": "Αποτέλεσμα",
  "stats.ou": "O/U",
  "stats.both": "Και τα δύο",
  "stats.byLeague": "Ανά Πρωτάθλημα",
  "stats.intlByTournament": "🌍 Διεθνείς — Ανά Διοργάνωση",
  "stats.byConfidenceClub": "(πρωταθλήματα συλλόγων)",
  "stats.confHelp": "High confidence = μέγιστη πιθανότητα έκβασης ≥ 55% ΚΑΙ σήμα στο O/U · Medium ≥ 42% · Low < 42%",
  "stats.internationals": "Διεθνείς",
  "stats.intlScale": "(ξεχωριστή κλίμακα: HIGH = p ≥ 65%)",
  "stats.byPredictedOutcome": "Ανά Προβλεπόμενη Έκβαση",
  "stats.matchResult": "Αποτέλεσμα Αγώνα",
  "stats.homeWin": "🏠 Νίκη γηπεδούχου",
  "stats.draw": "🤝 Ισοπαλία",
  "stats.awayWin": "✈️ Νίκη φιλοξενούμενου",
  "stats.overUnder": "Over / Under 2.5",
  "stats.over25": "⬆️ Over 2.5",
  "stats.under25": "⬇️ Under 2.5",
  "stats.totalDrawsSub": "πραγματικές ισοπαλίες στο σύνολο",
  "stats.drawPredictionsSub": "αγώνες που προβλέφθηκαν ως ισοπαλία",
  "stats.drawRecallSub": "των πραγματικών ισοπαλιών πιάστηκαν",
  "stats.drawPrecisionSub": "των προβλέψεων ισοπαλίας σωστές",
  "stats.drawNote": "Οι ισοπαλίες ({pct} των αγώνων) είναι η δυσκολότερη έκβαση για πρόβλεψη. Recall = τι ποσοστό των πραγματικών ισοπαλιών πιάσαμε · Precision = πόσο αξιόπιστες είναι οι προβλέψεις ισοπαλίας μας.",
  "stats.bttsTitle": "Goal / No Goal (BTTS)",
  "stats.bttsIntro": "{gg} = και οι δύο ομάδες σκόραραν τουλάχιστον 1 γκολ. {ng} = τουλάχιστον μία ομάδα δεν σκόραρε. Η πρόβλεψη γίνεται μέσω του Poisson μοντέλου (από τα αποθηκευμένα λ).",
  "stats.bttsGG": "GG (Goal Goal)",
  "stats.bttsNG": "NG (No Goal)",
  "stats.bttsSample": "Δείγμα",
  "stats.bttsCompletedWithLambda": "ολοκληρωμένοι αγώνες με λ",
  "stats.bttsOverallAcc": "Συνολική Ακρίβεια",
  "stats.bttsCorrectGGNG": "{c} / {t} σωστές (GG+NG)",
  "stats.bttsGGAcc": "GG Ακρίβεια",
  "stats.bttsGGPredsCorrect": "{c} / {t} GG προβλέψεων σωστές",
  "stats.bttsGGRecall": "GG Recall",
  "stats.bttsNGRecall": "NG Recall",
  "stats.bttsGGRecallSub": "Από {t} πραγματικά GG, πιάσαμε τα {c}",
  "stats.bttsNGRecallSub": "Από {t} πραγματικά NG, πιάσαμε τα {c}",
  "stats.bttsGGPredictions": "GG Predictions",
  "stats.bttsNGPredictions": "NG Predictions",
  "stats.bttsGGPredictedSub": "αγώνες που προβλέψαμε GG",
  "stats.bttsNGPredictedSub": "αγώνες που προβλέψαμε NG",
  "stats.roiTracker": "ROI Tracker",
  "stats.roiEmpty": "💰 Η παρακολούθηση ROI ξεκινά μόλις αποθηκευτούν αποδόσεις πράκτορα κατά την πρόβλεψη.",
  "stats.roiEmptySub": "Ξανατρέξε το compute_predictions.py για προσεχείς αγώνες ώστε να αρχίσει η συλλογή δεδομένων.",
  "stats.cumEV": "Σωρευτικό EV vs P&L",
  "stats.calibration": "Calibration",
  "stats.byModelVersion": "Ανά Έκδοση Μοντέλου",
  "stats.version": "Έκδοση",
  "stats.games": "Αγώνες",
  "stats.resultPct": "Αποτέλεσμα %",
  "stats.ouPct": "O/U %",

  // ── ROI card ──
  "roi.header": "💰 ROI Tracker — Value Strategy",
  "roi.subtitle": "Μόνο τα ⚡ suggested bets · €{stake} flat · {n} bets",
  "roi.noStrategy": "Δεν υπάρχουν ακόμα διευθετημένα suggested bets",
  "roi.strategyRoi": "Strategy ROI",
  "roi.clvTitle": "📉 Closing Line Value",
  "roi.clvSub": "{n} bets με closing snapshot · θετικό CLV = πραγματικό edge",
  "roi.beatClose": "beat close {pct}%",
  "roi.fairTitle": "🎯 Fair-value ROI — χωρίς γκανιότα",
  "roi.fairSub": "Ίδια στοιχήματα σε δίκαιες (de-vigged) αποδόσεις · ποιότητα μοντέλου vs αγορά",
  "roi.fairSuffix": "fair",
  "roi.vsWithVig": "vs −€{amt} ({pct}%) με γκανιότα",
  "roi.modelBaseline": "Model baseline (bet σε όλα · {n} bets)",
  "roi.colWithVig": "με γκανιότα",
  "roi.colModelFair": "μοντέλο (fair)",
  "roi.vig": "γκανιότα {amt}",
  "roi.market.result": "1×2 Result",
  "roi.market.goals": "Over 2.5 Goals",
  "roi.market.btts": "GG (BTTS)",
  "roi.bttsPending": "Δεν υπάρχουν αποθηκευμένες αποδόσεις BTTS ακόμα",
  "roi.pending": "pending",
  "roi.betsStaked": "{bets} bets · €{staked} staked",
  "roi.decomp.real": "Πραγματικό αποτέλεσμα (με γκανιότα)",
  "roi.decomp.model": "↳ από σωστά αποτελέσματα μοντέλου",
  "roi.decomp.vig": "↳ χαμένα σε γκανιότα (προμήθεια πράκτορα)",
  "roi.disclaimer": "Strategy = flat stake μόνο στα ⚡ suggested value bets (με market-shrunk EV gate). Το baseline ποντάρει σε κάθε πρόβλεψη και αναμένεται ≈ −γκανιότα — είναι δείκτης υγείας μοντέλου, όχι στρατηγική. Fair-value = ίδια στοιχήματα σε de-vigged αποδόσεις (Result & BTTS ακριβώς· *O/U με υποθετικό 4% overround αφού δεν αποθηκεύουμε under-2.5 odds). Δεν είναι εφικτή απόδοση — πουθενά δεν ποντάρεις σε fair odds — αλλά μετρά καθαρά την ποιότητα του μοντέλου.",

  // ── Home page ──
  "home.wcReview.label": "World Cup 2026 review",
  "home.wcReview.mid": "— το μοντέλο πέτυχε",
  "home.wcReview.suffix": "των αποτελεσμάτων σε {n} αγώνες",
  "home.wcReview.cta": "Δες →",

  // ── Match card / prediction bars ──
  "matchCard.insufficient": "ℹ️ Ανεπαρκή δεδομένα — άγνωστες ομάδες",
  "pred.ggLabel": "GG (και οι δύο σκοράρουν)",
  "pred.ngLabel": "NG (τουλάχιστον μία δεν σκοράρει)",

  // ── Recent result card ──
  "recent.loadFail": "Αποτυχία φόρτωσης ανάλυσης.",
  "recent.analyzing": "Αναλύω…",
  "recent.closeAnalysis": "▲ Κλείσιμο ανάλυσης",
  "recent.whyFail": "🔍 Γιατί απέτυχε;",

  // ── Locked match card ──
  "locked.membersOnly": "Πρόβλεψη μόνο για μέλη —",
  "locked.signupFree": "κάνε δωρεάν εγγραφή",

  // ── EV chart ──
  "ev.empty": "📈 Το γράφημα σωρευτικού EV θα εμφανιστεί μόλις αποθηκευτούν αποδόσεις πράκτορα για ολοκληρωμένους αγώνες.",
  "ev.emptySub": "Τρέξε το compute_predictions.py για να συμπληρωθούν αποδόσεις στο εξής.",
  "ev.title": "📈 Σωρευτικό EV vs P&L",
  "ev.flatStake": "€10 flat stake · {n} ημέρες σε παρακολούθηση",
  "ev.expectedValue": "Expected Value",
  "ev.actualPnl": "Actual P&L",
  "ev.fairPnl": "Fair P&L (χωρίς γκανιότα)",

  // ── Match detail (club) ──
  "match.insufficient.title": "Ανεπαρκή δεδομένα για πρόβλεψη",
  "match.insufficient.body": "Μία ή και οι δύο ομάδες δεν υπάρχουν στο ιστορικό εκπαίδευσης του μοντέλου (συνήθως προκριματικά ή ομάδες από πρωταθλήματα που δεν καλύπτουμε). Οι πιθανότητες θα ήταν απλώς οι default τιμές — δεν τις εμφανίζουμε.",

  // ── National match detail ──
  "nat.cards.hitYes": "εκτίμηση ±1.5 ✓",
  "nat.cards.hitNo": "εκτός ±1.5",
  "nat.actualTotal": "Πραγματικά · σύνολο {n}",
  "nat.caught": "πιάσαμε",
  "nat.missed": "χάσαμε",
  "nat.top6": "top-6",
  "nat.likelyScores": "🎯 Πιθανά Σκορ",
  "nat.actualScore": "Πραγματικό σκορ:",

  // ── Projection panels ──
  "proj.league.title": "🔮 Πρόγνωση Σεζόν",
  "proj.league.desc": "{sims} προσομοιώσεις των {n} αγώνων που απομένουν, από το τρέχον Elo και τη βαθμολογία. Δεν λαμβάνει υπόψη μεταγραφές ή τραυματισμούς.",
  "proj.team": "Ομάδα",
  "proj.league.title2": "Τίτλος",
  "proj.league.releg": "Υποβ.",
  "proj.league.xpts": "xΒαθ.",
  "proj.eu.title": "🏆 Πρόγνωση Κατάκτησης",
  "proj.eu.desc": "{sims} προσομοιώσεις: {n} αγώνες league phase που απομένουν, μετά playoff + νοκ-άουτ μέχρι τον τελικό. Το bracket προκύπτει από τη σειρά κατάταξης — η πραγματική κλήρωση δεν έχει γίνει.",
  "proj.eu.win": "Κατάκτηση",
  "proj.eu.final": "Τελικός",
  "proj.eu.r16": "16άδα",
  "proj.eu.more": "+ {n} ομάδες κάτω από 1%.",

  // ── Locked detail panel ──
  "locked.detail.title": "Η πλήρης πρόβλεψη για το {home} – {away} είναι διαθέσιμη μόνο σε μέλη",
  "locked.detail.body": "Πιθανότητες 1×2, goals, BTTS, πιθανά σκορ, σύγκριση με 25 bookmakers και AI ανάλυση — όλα δωρεάν με έναν λογαριασμό. Τα 3 κορυφαία picks της ημέρας μένουν πάντα ανοιχτά στην αρχική.",
  "locked.detail.signup": "Δωρεάν εγγραφή",
  "locked.detail.login": "Σύνδεση",
  "locked.detail.seePre": "Δες την",
  "locked.detail.accuracy": "ακρίβεια του μοντέλου",
  "locked.detail.seeMid": "και τα",
  "locked.detail.recent": "πρόσφατα αποτελέσματα",
  "locked.detail.seeSuf": "— δημόσια, χωρίς εγγραφή.",

  // ── Player props panel ──
  "props.score": "Σκορ",
  "props.scoreDef": "= σκοράρει",
  "props.shots": "Σουτ",
  "props.shotsDef": "= 1+ σουτ στην εστία",
  "props.assist": "Ασίστ",
  "props.assistDef": "= δώσει ασίστ.",
  "props.title": "👤 Στατιστικά Παικτών",
  "props.descPre": "Πιθανότητα ανά παίκτη να:",
  "props.settledNote": "Κάτω από κάθε πιθανότητα: ✓/✗ τι πιάσαμε + ο πραγματικός αριθμός.",
  "props.methodNote": "(recency-weighted ρυθμοί × αναμενόμενα γκολ)",

  // ── Standings table ──
  "st.title": "📋 Βαθμολογία",
  "st.final": "τελική",
  "st.team": "Ομάδα",
  "st.p": "Α",
  "st.w": "Ν",
  "st.d": "Ι",
  "st.l": "Η",
  "st.gd": "Δ",
  "st.pts": "Β",
  "zone.championsLeague": "Champions League",
  "zone.promotion": "Άνοδος",
  "zone.europe": "Ευρώπη",
  "zone.libertadores": "Libertadores",
  "zone.round16": "Απευθείας 16άδα",
  "zone.playoff": "Play-off 16άδας",
  "zone.relegation": "Υποβιβασμός",
  "zone.eliminated": "Αποκλεισμός",

  // ── Projections browser ──
  "proj.filter.all": "Όλα",
  "proj.filter.domestic": "Πρωταθλήματα",
  "proj.filter.european": "Ευρώπη",
  "proj.empty.title": "Δεν υπάρχουν διαθέσιμες προγνώσεις αυτή τη στιγμή.",
  "proj.empty.body": "Οι μακροχρόνιες προγνώσεις ανάβουν μόλις ξεκινήσει η σεζόν κάθε διοργάνωσης.",
  "proj.eu.pending.title": "Διαθέσιμο μετά την κλήρωση της league phase",
  "proj.eu.pending.body": "Οι 36 συμμετέχοντες της διοργάνωσης κρίνονται στα προκριματικά που παίζονται τώρα — μια «πιθανότητα κατάκτησης» πριν οριστικοποιηθεί το πεδίο θα ήταν εφεύρεση, όχι εκτίμηση. Η πρόβλεψη ανάβει αυτόματα μόλις μπουν οι αγώνες της league phase (τέλη Αυγούστου).",

  // ── Projections page ──
  "projPage.title": "🔮 Μακροχρόνιες Προγνώσεις",
  "projPage.desc": "Πιθανότητες κατάκτησης, Ευρώπης και υποβιβασμού ανά διοργάνωση — Monte Carlo από το τρέχον Elo και τη βαθμολογία.",

  // ── World Cup group qualification ──
  "wc.groupQual": "📊 Πρόκριση Ομίλων",
  "wc.first": "1ος",
  "wc.firstDef": "= πρώτη θέση ομίλου",
  "wc.top2": "Top-2",
  "wc.top2Def": "= απευθείας πρόκριση",
  "wc.qualify": "Πρόκριση",
  "wc.qualifyDef": "= top-2 ή ένας από τους 8 καλύτερους 3ους.",
  "wc.qualCol": "Πρόκρ",

  // ── Projection history chart ──
  "hist.title": "📈 Εξέλιξη Αποδόσεων",
  "hist.empty": "Το ιστορικό αποδόσεων εμφανίζεται μετά από μερικές ημερήσιες προσομοιώσεις — ένα στιγμιότυπο την ημέρα.",
  "hist.legend": "(— μοντέλο · - - αγορά)",

  // ── Match analysis panel ──
  "ma.lockedCta": "🔒 Η σύγκριση με bookmakers και η AI ανάλυση είναι διαθέσιμες μόνο σε μέλη.",
  "ma.signup": "Δωρεάν εγγραφή",
  "ma.poissonGap": "⚠ Poisson ↔ XGBoost διαφορά {pp}pp — ενδεικτικά",
  "ma.analyticStats": "Αναλυτικές Στατιστικές",
  "ma.likelyScores": "Πιθανά Σκορ",
  "ma.teal": "Teal = ανήκει στο dominant combo · Τα scores αθροίζονται σε 100%",
  "ma.comboMarkets": "Συνδυαστικές Αγορές",
  "ma.eg": "π.χ.",
  "ma.aiAnalysis": "Ανάλυση AI",
  "ma.win": "Νίκη {team}",
  "ma.draw": "Ισοπαλία",
  "ma.ggFull": "GG (Και οι δύο σκοράρουν)",
  "ma.mostLikely": "Πιθανότερο αποτέλεσμα",
  "ma.watched": "Υπό παρακολούθηση (αναπόδεικτο)",
  "ma.modelVs": " · μοντέλο {m}% vs αγορά {k}%",
  "ma.marketOnly": " · αγορά {k}%",
  "ma.watchNote": "Το μοντέλο βλέπει edge εδώ, αλλά αυτή η αγορά δεν έχει ακόμα αποδεδειγμένο ιστορικό στο τρέχον μοντέλο — την καταγράφουμε και θα προωθηθεί σε πρόταση μόνο αν τα δεδομένα τη δικαιώσουν.",

  // ── Chat box ──
  "chat.suggest1": "Δώσε μου 3 προτάσεις με high confidence",
  "chat.suggest2": "Ποια παιχνίδια σήμερα είναι over 2.5;",
  "chat.suggest3": "Καλύτερα παιχνίδια EPL αυτή την εβδομάδα;",
  "chat.suggest4": "Ποιες ισοπαλίες είναι πιο πιθανές;",
  "chat.error": "Κάτι πήγε στραβά.",
  "chat.askMe": "Ρώτησέ με για τις προβλέψεις των αγώνων",
  "chat.placeholder": "Γράψε την ερώτησή σου…",
  "chat.enterHint": "Enter αποστολή · Shift+Enter νέα γραμμή",

  // ── Contact button ──
  "contact.emptyMsg": "Γράψε ένα μήνυμα πρώτα.",
  "contact.genericErr": "Κάτι πήγε στραβά. Δοκίμασε ξανά.",
  "contact.sendFail": "Αποτυχία αποστολής. Έλεγξε τη σύνδεσή σου.",
  "contact.title": "Στείλε μου ιδέες / προτάσεις",
  "contact.heading": "✉️ Επικοινωνία",
  "contact.thanks": "Ευχαριστώ! Το μήνυμά σου στάλθηκε.",
  "contact.close": "Κλείσιμο",
  "contact.blurb": "Στείλε μου τις ιδέες ή προτάσεις σου για το Football Predictor. Τις διαβάζω όλες.",
  "contact.placeholder": "Η ιδέα / πρότασή σου…",
  "contact.cancel": "Άκυρο",
  "contact.send": "Αποστολή",
  "contact.sending": "Αποστολή…",

  // ── World Cup review ──
  "rev.outcome.H": "νίκη γηπεδούχου",
  "rev.outcome.D": "ισοπαλία",
  "rev.outcome.A": "νίκη φιλοξ.",
  "rev.emptyTitle": "Το review δεν είναι διαθέσιμο ακόμα.",
  "rev.emptyBody": "Θα γεμίσει καθώς ολοκληρώνονται αγώνες του Παγκοσμίου.",
  "rev.settled": "Settled matches",
  "rev.settledSub": "με πρόβλεψη + αποτέλεσμα",
  "rev.resultAcc": "Result accuracy",
  "rev.resultAccSub": "{c}/{t} σωστά (1×2)",
  "rev.highConf": "High-confidence",
  "rev.highConfSub": "{n} σίγουρες κλήσεις (≥55%)",
  "rev.ou": "Over/Under 2.5",
  "rev.ouSub": "{n} αγώνες",
  "rev.champFav": "🏆 Το φαβορί του μοντέλου για τον τίτλο (πριν τους νοκ-άουτ):",
  "rev.champProb": "({pct} πιθανότητα)",
  "rev.sureCalls": "✅ Σίγουρες κλήσεις που βγήκαν",
  "rev.footPre": "Οι προβλέψεις έγιναν πριν από κάθε αγώνα από το market-independent μοντέλο (talent-adjusted Elo). Δες επίσης τη",
  "rev.detailedAcc": "αναλυτική ακρίβεια",
  "rev.title": "World Cup 2026 — Review",
  "rev.subtitle": "Πώς τα πήγε το μοντέλο στο τουρνουά.",
  "rev.backNational": "Εθνικές ομάδες →",

  // ── Admin: training ──
  "adminTr.deltaVsActual": "Δ = {pp}pp vs actual",
  "adminTr.subtitle": "Test set accuracy, recall & calibration ανά retrain · ώρες σε Europe/Athens",
  "adminTr.dailyRetrain": "Retrain καθημερινά ~06:00 (self-correct στα χθεσινά αποτελέσματα)",
  "adminTr.weeklyRetrain": "Retrain εβδομαδιαία (Δευτέρες ~06:00) — εκτός σεζόν αλλάζει αργά",
  "adminTr.noRuns": "Δεν υπάρχουν ακόμα training runs. Θα εμφανιστούν μετά το επόμενο weekly retrain.",

  // ── Admin: gate changes ──
  "gate.descPre": "Κάθε φορά που ένα market μπαίνει (promoted) ή βγαίνει (demoted) από το suggestable set, καταγράφεται εδώ — το ίδιο συμβάν που στέλνει το",
  "gate.descPost": "webhook. Πιο πρόσφατα πρώτα.",
  "gate.empty": "Καμία αλλαγή ακόμα. Οι base markets (Home Win / Draw) ξεκινούν proven· εδώ εμφανίζονται προβιβασμοί/υποβιβασμοί καθώς μαζεύεται record.",

  // ── Admin: dashboard ──
  "admin.newMessages": "Νέα μηνύματα",
  "admin.userMessages": "✉️ Μηνύματα χρηστών",
  "admin.newBadge": "{n} νέα",

  // ── Admin: markets ──
  "markets.empty": "Δεν υπάρχουν ακόμα καταγεγραμμένα tickets.",

  // ── Admin: feedback ──
  "fb.empty": "Κανένα μήνυμα ακόμα.",
  "fb.new": "ΝΕΟ",
  "fb.reply": "Απάντηση ↗",
  "fb.markRead": "Σήμανση ως διαβασμένο",
};

export const messages: Record<Lang, Table> = { en, el };
