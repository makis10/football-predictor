/**
 * /stats — Model accuracy & monitoring dashboard.
 * Server component: always SSR (force-dynamic); backend caches the data for 6h.
 */
import { Suspense } from "react";
import { getStats, getNationalStats, INTERNATIONAL_LEAGUE, type NationalStatsResponse } from "@/lib/api";
import { StatCard } from "@/components/stats/StatCard";
import { AccuracyBar } from "@/components/stats/AccuracyBar";
import { LeagueTable } from "@/components/stats/LeagueTable";
import { CalibrationChart } from "@/components/stats/CalibrationChart";
import { BTTSCalibrationChart } from "@/components/stats/BTTSCalibrationChart";
import { ResultCalibrationChart } from "@/components/stats/ResultCalibrationChart";
import { ROICard } from "@/components/stats/ROICard";
import { EVChart } from "@/components/stats/EVChart";
import LeagueFilter from "@/components/LeagueFilter";

// SSR every request — backend has its own 6h in-process cache so this is fast.
export const dynamic = "force-dynamic";

interface PageProps {
  searchParams: Promise<{ league?: string }>;
}

function pct(v: number) {
  return `${Math.round(v * 100)}%`;
}

function accentForAccuracy(v: number): "green" | "yellow" | "red" {
  if (v >= 0.57) return "green";
  if (v >= 0.48) return "yellow";
  return "red";
}

export default async function StatsPage({ searchParams }: PageProps) {
  const league = (await searchParams).league;
  // Case-insensitive: hand-typed/shared URLs use ?league=international (lowercase)
  // while the filter emits "International" — both must hit the national view,
  // otherwise the value leaks to the club /stats query as an unknown league
  // and the page renders all-zeros.
  const isInternational =
    league?.toLowerCase() === INTERNATIONAL_LEAGUE.toLowerCase();

  let stats;
  let nationalStats: NationalStatsResponse | null = null;

  if (!isInternational) {
    try {
      stats = await getStats(league);
    } catch {
      return (
        <div className="text-center py-16 text-gray-500">
          <p className="text-4xl mb-4">📊</p>
          <p className="text-lg font-medium text-gray-400">Stats unavailable</p>
          <p className="text-sm mt-1">
            No completed matches with predictions yet — check back after the next match day.
          </p>
        </div>
      );
    }
  }

  // Always fetch national stats (best-effort — used both for the international
  // filter view and for the "By Tournament" section on the all-leagues page).
  try {
    nationalStats = await getNationalStats();
  } catch {
    // non-fatal — page degrades gracefully without national data
  }

  // ── International-only view ───────────────────────────────────────────────
  if (isInternational) {
    if (!nationalStats || nationalStats.total === 0) {
      return (
        <div className="space-y-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-100 mb-1">📊 International Model Accuracy</h1>
          </div>
          <Suspense>
            <LeagueFilter active={league} basePath="/stats" />
          </Suspense>
          <div className="text-center py-16 text-gray-500">
            <p className="text-4xl mb-3">🌍</p>
            <p className="font-medium">No international results yet.</p>
          </div>
        </div>
      );
    }

    const ns = nationalStats;
    return (
      <div className="space-y-10">
        <div>
          <h1 className="text-2xl font-bold text-gray-100 mb-1">📊 International Model Accuracy</h1>
          <p className="text-sm text-gray-500">
            National team predictions · {ns.total} completed matches.
          </p>
        </div>

        <Suspense>
          <LeagueFilter active={league} basePath="/stats" />
        </Suspense>

        {/* Overall hero cards */}
        <section>
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
            All Time · {ns.total} matches
          </h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatCard
              label="Result Accuracy"
              value={pct(ns.result_accuracy)}
              sub={`${ns.result_correct} / ${ns.total} correct`}
              accent={accentForAccuracy(ns.result_accuracy)}
            />
            <StatCard
              label="O/U Accuracy"
              value={pct(ns.over_accuracy)}
              sub={`${ns.over_correct} / ${ns.total} correct`}
              accent={accentForAccuracy(ns.over_accuracy)}
            />
            <StatCard
              label="Both Correct"
              value={pct(ns.both_accuracy)}
              sub={`${ns.both_correct} / ${ns.total}`}
              accent={accentForAccuracy(ns.both_accuracy)}
            />
            <StatCard
              label="Matches Tracked"
              value={ns.total.toLocaleString()}
              sub="with stored predictions"
              accent="gray"
            />
          </div>
        </section>

        {/* By tournament */}
        {ns.by_tournament.length > 0 && (
          <section>
            <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
              By Tournament
            </h2>
            <LeagueTable
              rows={ns.by_tournament.map((t) => ({
                league:          t.tournament,
                total:           t.total,
                result_correct:  t.result_correct,
                goals_correct:   t.over_correct,
                both_correct:    t.both_correct,
                result_accuracy: t.result_accuracy,
                goals_accuracy:  t.over_accuracy,
                both_accuracy:   t.both_accuracy,
              }))}
            />
          </section>
        )}

        {/* By confidence */}
        {ns.by_confidence.length > 0 && (
          <section>
            <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
              By Confidence Level
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              {ns.by_confidence.map((c) => (
                <div
                  key={c.confidence}
                  className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-4 space-y-2"
                >
                  <p className="text-sm font-semibold capitalize text-gray-300">
                    {c.confidence === "HIGH" && "🟢 "}
                    {c.confidence === "MEDIUM" && "🟡 "}
                    {c.confidence === "LOW" && "🔴 "}
                    {c.confidence.toLowerCase()}
                    <span className="ml-2 text-xs font-normal text-gray-500">
                      {c.total} matches
                    </span>
                  </p>
                  <AccuracyBar
                    label="Result accuracy"
                    value={c.result_accuracy}
                    color={
                      c.confidence === "HIGH"   ? "bg-green-500" :
                      c.confidence === "MEDIUM" ? "bg-yellow-500" :
                      "bg-gray-500"
                    }
                  />
                  <p className="text-xs text-gray-500">
                    {c.result_correct} / {c.total} correct
                  </p>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Draw stats */}
        {ns.draw_stats && (
          <section>
            <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
              Draw Prediction
            </h2>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <StatCard label="Total Draws"      value={ns.draw_stats.total_draws}     sub="actual draws" accent="gray" />
              <StatCard label="Draw Predictions" value={ns.draw_stats.predicted_draws}  sub="predicted as draw" accent="gray" />
              <StatCard label="Draw Recall"      value={pct(ns.draw_stats.recall)}     sub="of actual draws caught" accent={accentForAccuracy(ns.draw_stats.recall)} />
              <StatCard label="Draw Precision"   value={pct(ns.draw_stats.precision)}  sub="of draw preds correct" accent={accentForAccuracy(ns.draw_stats.precision)} />
            </div>
          </section>
        )}
      </div>
    );
  }

  // ── Club stats (all leagues / specific league) ────────────────────────────
  // stats is defined here: isInternational=false and getStats() succeeded (else we returned early).
  const s   = stats!;
  const all = s.rolling.all_time;
  const last30 = s.rolling.last_30d;
  const last7  = s.rolling.last_7d;

  const draw = s.draw_stats;
  const btts = s.btts_stats;
  const topPicks = s.top_picks;
  const confHigh   = s.by_confidence.find((c) => c.confidence === "high");
  const confMedium = s.by_confidence.find((c) => c.confidence === "medium");
  const confLow    = s.by_confidence.find((c) => c.confidence === "low");

  // Predicted outcomes — result only
  const resultOutcomes = s.by_predicted_outcome.filter((o) =>
    ["H", "D", "A"].includes(o.predicted)
  );
  const goalsOutcomes = s.by_predicted_outcome.filter((o) =>
    ["OVER", "UNDER"].includes(o.predicted)
  );

  const computedAt = new Date(s.computed_at).toLocaleString("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Europe/Athens",
  });

  return (
    <div className="space-y-10">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-100 mb-1">📊 Model Accuracy</h1>
        <p className="text-sm text-gray-500">
          Live accuracy tracking across all completed matches with ML predictions.
          Refreshed every hour · last computed {computedAt}.
        </p>
      </div>

      {/* Methodology cutoff — honest flag: all-time numbers mix two models */}
      {s.methodology && s.methodology.settled_before > 0 && (
        <div className="rounded-xl border border-amber-700/40 bg-amber-950/20 p-4 text-sm">
          <p className="font-semibold text-amber-300 mb-1">⚠️ Αλλαγή μοντέλου — {s.methodology.cutoff}</p>
          <p className="text-gray-300 leading-relaxed">
            Το μοντέλο έγινε <span className="font-medium text-gray-100">market-independent</span> στις{" "}
            {s.methodology.cutoff} (αφαιρέθηκαν market features + anchoring). Τα{" "}
            <span className="font-medium text-gray-100">{s.methodology.settled_before}</span> παιχνίδια πριν
            σερβιρίστηκαν από το παλιό (anchored) μοντέλο, ενώ{" "}
            <span className="font-medium text-gray-100">{s.methodology.settled_after}</span> από το τωρινό.
            Τα «All Time» νούμερα παρακάτω αναμειγνύουν τις δύο μεθοδολογίες — τα rolling 7d/30d είναι πιο
            αντιπροσωπευτικά του τωρινού μοντέλου.
          </p>
          {/* Per-regime accuracy — no methodology mixing within a row */}
          {s.methodology.regimes && s.methodology.regimes.length > 0 && (
            <div className="mt-3 space-y-1">
              <div className="grid grid-cols-[1fr_4.5rem_4.5rem_3.5rem] gap-2 text-[11px] text-gray-500 uppercase tracking-wide">
                <span>Περίοδος μοντέλου</span>
                <span className="text-right">1×2</span>
                <span className="text-right">O/U</span>
                <span className="text-right">N</span>
              </div>
              {s.methodology.regimes.map((r) => (
                <div
                  key={r.regime}
                  className="grid grid-cols-[1fr_4.5rem_4.5rem_3.5rem] gap-2 text-sm items-center"
                >
                  <span className="text-gray-300">
                    {r.regime}
                    <span className="text-gray-600 text-xs">
                      {" "}({r.from_date ?? "…"} → {r.to_date ?? "τώρα"})
                    </span>
                  </span>
                  <span className="text-right tabular-nums text-gray-200">
                    {(r.stats.result_accuracy * 100).toFixed(1)}%
                  </span>
                  <span className="text-right tabular-nums text-gray-200">
                    {(r.stats.goals_accuracy * 100).toFixed(1)}%
                  </span>
                  <span className="text-right tabular-nums text-gray-500">{r.stats.total}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Injury adjustment: raw vs adjusted accuracy (same rows) */}
      {s.injury_adjustment && s.injury_adjustment.matches >= 5 && (
        <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-4 text-sm">
          <p className="font-semibold text-gray-300 mb-1">🩹 Injury adjustment — μετρημένη επίδραση</p>
          <p className="text-gray-400 text-xs mb-2">
            Ίδια {s.injury_adjustment.matches} παιχνίδια, ίδιο μοντέλο — μόνο το injury layer αλλάζει.
          </p>
          <div className="flex gap-6 tabular-nums">
            <span>
              1×2: raw {(s.injury_adjustment.raw_result_accuracy * 100).toFixed(1)}% →{" "}
              <span className={s.injury_adjustment.adj_result_accuracy >= s.injury_adjustment.raw_result_accuracy ? "text-green-400" : "text-red-400"}>
                adj {(s.injury_adjustment.adj_result_accuracy * 100).toFixed(1)}%
              </span>
            </span>
            <span>
              O/U: raw {(s.injury_adjustment.raw_goals_accuracy * 100).toFixed(1)}% →{" "}
              <span className={s.injury_adjustment.adj_goals_accuracy >= s.injury_adjustment.raw_goals_accuracy ? "text-green-400" : "text-red-400"}>
                adj {(s.injury_adjustment.adj_goals_accuracy * 100).toFixed(1)}%
              </span>
            </span>
          </div>
        </div>
      )}

      {/* League filter */}
      <Suspense>
        <LeagueFilter active={league} basePath="/stats" />
      </Suspense>

      {/* ── Top AI Picks ──────────────────────────────────────────────────── */}
      {topPicks && (
        <section className="rounded-xl border border-amber-700/40 bg-amber-950/20 p-5">
          <div className="flex items-center gap-2 mb-4">
            <span className="text-lg">⚡</span>
            <h2 className="text-sm font-semibold text-amber-300 uppercase tracking-wide">
              Top AI Picks — ιστορική ακρίβεια
            </h2>
            <span className="ml-auto text-xs text-gray-500">
              Top 3 ανά ημέρα · high confidence → μεγαλύτερη πιθανότητα
            </span>
          </div>

          {/* Hero cards */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
            <div className="rounded-lg bg-pitch-800/80 border border-amber-700/30 p-4 text-center">
              <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Ακρίβεια</p>
              <p className={`text-3xl font-bold ${
                topPicks.accuracy >= 0.57 ? "text-green-400" :
                topPicks.accuracy >= 0.48 ? "text-yellow-400" : "text-red-400"
              }`}>
                {pct(topPicks.accuracy)}
              </p>
              <p className="text-xs text-gray-500 mt-1">{topPicks.correct} / {topPicks.total} σωστές</p>
            </div>

            <div className="rounded-lg bg-pitch-800/80 border border-amber-700/30 p-4 text-center">
              <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Vs Γενική</p>
              <p className={`text-3xl font-bold ${
                topPicks.vs_overall_accuracy > 0.02 ? "text-green-400" :
                topPicks.vs_overall_accuracy > -0.02 ? "text-yellow-400" : "text-red-400"
              }`}>
                {topPicks.vs_overall_accuracy >= 0 ? "+" : ""}{pct(topPicks.vs_overall_accuracy)}
              </p>
              <p className="text-xs text-gray-500 mt-1">διαφορά από {pct(all.result_accuracy)} overall</p>
            </div>

            <div className="rounded-lg bg-pitch-800/80 border border-amber-700/30 p-4 text-center">
              <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Μέση Πιθανότητα</p>
              <p className="text-3xl font-bold text-amber-400">
                {Math.round(topPicks.avg_pick_prob * 100)}%
              </p>
              <p className="text-xs text-gray-500 mt-1">confidence του top pick</p>
            </div>

            <div className="rounded-lg bg-pitch-800/80 border border-amber-700/30 p-4 text-center">
              <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Σύνολο Picks</p>
              <p className="text-3xl font-bold text-gray-100">{topPicks.total}</p>
              <p className="text-xs text-gray-500 mt-1">~3 ανά ημέρα παιχνιδιών</p>
            </div>
          </div>

          {/* Breakdown by market */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {topPicks.result_picks > 0 && (
              <div className="rounded-lg bg-pitch-800/60 border border-pitch-700 p-3">
                <p className="text-xs font-semibold text-gray-400 uppercase mb-2">1×2 Αποτέλεσμα</p>
                <div className="flex items-end justify-between">
                  <div>
                    <p className={`text-2xl font-bold ${
                      topPicks.result_accuracy >= 0.57 ? "text-green-400" :
                      topPicks.result_accuracy >= 0.48 ? "text-yellow-400" : "text-red-400"
                    }`}>{pct(topPicks.result_accuracy)}</p>
                    <p className="text-xs text-gray-500">{topPicks.result_correct}/{topPicks.result_picks} σωστές</p>
                  </div>
                  <p className="text-xs text-gray-600">{topPicks.result_picks} picks</p>
                </div>
              </div>
            )}
            {topPicks.goals_picks > 0 && (
              <div className="rounded-lg bg-pitch-800/60 border border-pitch-700 p-3">
                <p className="text-xs font-semibold text-gray-400 uppercase mb-2">Over/Under 2.5</p>
                <div className="flex items-end justify-between">
                  <div>
                    <p className={`text-2xl font-bold ${
                      topPicks.goals_accuracy >= 0.57 ? "text-green-400" :
                      topPicks.goals_accuracy >= 0.48 ? "text-yellow-400" : "text-red-400"
                    }`}>{pct(topPicks.goals_accuracy)}</p>
                    <p className="text-xs text-gray-500">{topPicks.goals_correct}/{topPicks.goals_picks} σωστές</p>
                  </div>
                  <p className="text-xs text-gray-600">{topPicks.goals_picks} picks</p>
                </div>
              </div>
            )}
          </div>

          <p className="text-[10px] text-gray-600 mt-3 leading-relaxed">
            Ίδια λογική με την αρχική σελίδα: top 3 αγώνες ανά ημέρα ταξινομημένοι κατά high confidence
            → μεγαλύτερη πιθανότητα αποτελέσματος. Μετράει αν η προβλεπόμενη έκβαση (Home Win / Away Win / Draw / Over / Under)
            ήταν σωστή.
          </p>
        </section>
      )}

      {/* ── All-time hero cards ────────────────────────────────────────────── */}
      <section>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
          All Time · {all.total} matches
        </h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <StatCard
            label="Result Accuracy"
            value={pct(all.result_accuracy)}
            sub={`${all.result_correct} / ${all.total} correct`}
            accent={accentForAccuracy(all.result_accuracy)}
          />
          <StatCard
            label="O/U Accuracy"
            value={pct(all.goals_accuracy)}
            sub={`${all.goals_correct} / ${all.total} correct`}
            accent={accentForAccuracy(all.goals_accuracy)}
          />
          <StatCard
            label="Both Correct"
            value={pct(all.both_accuracy)}
            sub={`${all.both_correct} / ${all.total}`}
            accent={accentForAccuracy(all.both_accuracy)}
          />
          <StatCard
            label="Matches Tracked"
            value={all.total.toLocaleString()}
            sub="with stored predictions"
            accent="gray"
          />
        </div>
      </section>

      {/* ── Rolling windows ────────────────────────────────────────────────── */}
      <section>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
          Rolling Performance
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {/* Last 7 days */}
          <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-4 space-y-3">
            <p className="text-sm font-semibold text-gray-300">
              Last 7 days
              <span className="ml-2 text-xs font-normal text-gray-500">
                {last7.total} matches
              </span>
            </p>
            <AccuracyBar label="Result" value={last7.result_accuracy} color="bg-green-500" />
            <AccuracyBar label="O/U"    value={last7.goals_accuracy}  color="bg-blue-500" />
            <AccuracyBar label="Both"   value={last7.both_accuracy}   color="bg-purple-500" />
          </div>

          {/* Last 30 days */}
          <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-4 space-y-3">
            <p className="text-sm font-semibold text-gray-300">
              Last 30 days
              <span className="ml-2 text-xs font-normal text-gray-500">
                {last30.total} matches
              </span>
            </p>
            <AccuracyBar label="Result" value={last30.result_accuracy} color="bg-green-500" />
            <AccuracyBar label="O/U"    value={last30.goals_accuracy}  color="bg-blue-500" />
            <AccuracyBar label="Both"   value={last30.both_accuracy}   color="bg-purple-500" />
          </div>
        </div>
      </section>

      {/* ── By league ─────────────────────────────────────────────────────── */}
      <section>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
          By League
        </h2>
        <LeagueTable rows={s.by_league} />
      </section>

      {/* ── International — By Tournament ─────────────────────────────────── */}
      {nationalStats && nationalStats.by_tournament.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
            🌍 International — By Tournament
          </h2>
          <LeagueTable
            rows={nationalStats.by_tournament.map((t) => ({
              league:          t.tournament,
              total:           t.total,
              result_correct:  t.result_correct,
              goals_correct:   t.over_correct,
              both_correct:    t.both_correct,
              result_accuracy: t.result_accuracy,
              goals_accuracy:  t.over_accuracy,
              both_accuracy:   t.both_accuracy,
            }))}
          />
        </section>
      )}

      {/* ── By confidence ─────────────────────────────────────────────────── */}
      {/* Club-only: the national pipeline defines the label with a different
          formula/thresholds, so the tiers are NOT comparable — shown separately. */}
      <section>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
          By Confidence Level <span className="text-gray-600 normal-case">(club leagues)</span>
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {[confHigh, confMedium, confLow].filter(Boolean).map((c) => (
            <div
              key={c!.confidence}
              className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-4 space-y-2"
            >
              <p className="text-sm font-semibold capitalize text-gray-300">
                {c!.confidence === "high" && "🟢 "}
                {c!.confidence === "medium" && "🟡 "}
                {c!.confidence === "low" && "🔴 "}
                {c!.confidence}
                <span className="ml-2 text-xs font-normal text-gray-500">
                  {c!.total} matches
                </span>
              </p>
              <AccuracyBar
                label="Result accuracy"
                value={c!.result_accuracy}
                color={
                  c!.confidence === "high"   ? "bg-green-500" :
                  c!.confidence === "medium" ? "bg-yellow-500" :
                  "bg-gray-500"
                }
              />
              <p className="text-xs text-gray-500">
                {c!.result_correct} / {c!.total} correct
              </p>
            </div>
          ))}
        </div>
        <p className="text-xs text-gray-600 mt-2">
          High confidence = max outcome probability ≥ 55% ΚΑΙ σήμα στο O/U · Medium ≥ 42% · Low &lt; 42%
        </p>

        {/* National — different label semantics (p_max ≥ 0.65 → HIGH, no O/U term) */}
        {s.by_confidence_national && s.by_confidence_national.some((c) => c.total > 0) && (
          <div className="mt-4">
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
              Internationals <span className="text-gray-600 normal-case">(ξεχωριστή κλίμακα: HIGH = p ≥ 65%)</span>
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              {s.by_confidence_national.filter((c) => c.total > 0).map((c) => (
                <div
                  key={`nat-${c.confidence}`}
                  className="rounded-xl border border-pitch-700 bg-pitch-800/40 p-4 space-y-2"
                >
                  <p className="text-sm font-semibold capitalize text-gray-300">
                    {c.confidence === "high" && "🟢 "}
                    {c.confidence === "medium" && "🟡 "}
                    {c.confidence === "low" && "🔴 "}
                    {c.confidence}
                    <span className="ml-2 text-xs font-normal text-gray-500">{c.total} matches</span>
                  </p>
                  <AccuracyBar
                    label="Result accuracy"
                    value={c.result_accuracy}
                    color={
                      c.confidence === "high"   ? "bg-green-500" :
                      c.confidence === "medium" ? "bg-yellow-500" :
                      "bg-gray-500"
                    }
                  />
                  <p className="text-xs text-gray-500">{c.result_correct} / {c.total} correct</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      {/* ── Predicted outcome breakdown ───────────────────────────────────── */}
      <section>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
          By Predicted Outcome
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {/* Result outcomes */}
          <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-4 space-y-3">
            <p className="text-sm font-semibold text-gray-300">Match Result</p>
            {resultOutcomes.map((o) => (
              <div key={o.predicted} className="space-y-1">
                <AccuracyBar
                  label={
                    o.predicted === "H" ? "🏠 Home win" :
                    o.predicted === "D" ? "🤝 Draw" :
                    "✈️ Away win"
                  }
                  value={o.accuracy}
                  color={
                    o.predicted === "H" ? "bg-green-500" :
                    o.predicted === "D" ? "bg-gray-500" :
                    "bg-blue-500"
                  }
                />
                <p className="text-xs text-gray-500 pl-1">
                  {o.correct} / {o.total} correct
                </p>
              </div>
            ))}
          </div>

          {/* O/U outcomes */}
          <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-4 space-y-3">
            <p className="text-sm font-semibold text-gray-300">Over / Under 2.5</p>
            {goalsOutcomes.map((o) => (
              <div key={o.predicted} className="space-y-1">
                <AccuracyBar
                  label={o.predicted === "OVER" ? "⬆️ Over 2.5" : "⬇️ Under 2.5"}
                  value={o.accuracy}
                  color={o.predicted === "OVER" ? "bg-orange-500" : "bg-sky-500"}
                />
                <p className="text-xs text-gray-500 pl-1">
                  {o.correct} / {o.total} correct
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Draw specialist stats ──────────────────────────────────────────── */}
      <section>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
          Draw Prediction
        </h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <StatCard
            label="Total Draws"
            value={draw.total_draws}
            sub="actual draws in dataset"
            accent="gray"
          />
          <StatCard
            label="Draw Predictions"
            value={draw.predicted_draws}
            sub="matches predicted as draw"
            accent="gray"
          />
          <StatCard
            label="Draw Recall"
            value={pct(draw.recall)}
            sub="of actual draws caught"
            accent={accentForAccuracy(draw.recall)}
          />
          <StatCard
            label="Draw Precision"
            value={pct(draw.precision)}
            sub="of draw predictions correct"
            accent={accentForAccuracy(draw.precision)}
          />
        </div>
        <p className="text-xs text-gray-600 mt-2">
          Draws ({pct(draw.total_draws / (all.total || 1))} of matches) are the hardest outcome to predict.
          Recall = what fraction of actual draws we caught · Precision = how reliable our draw calls are.
        </p>
      </section>

      {/* ── BTTS (Goal / No Goal) stats ───────────────────────────────────── */}
      {btts && (
        <section>
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
            Goal / No Goal (BTTS)
          </h2>

          {/* What is GG/NG */}
          <div className="rounded-xl border border-pitch-700 bg-pitch-800/40 p-3 mb-3 text-xs text-gray-400 leading-relaxed">
            <span className="font-semibold text-gray-300">GG (Goal Goal)</span> = και οι δύο ομάδες σκόραραν τουλάχιστον 1 γκολ.{" "}
            <span className="font-semibold text-gray-300">NG (No Goal)</span> = τουλάχιστον μία ομάδα δεν σκόραρε.{" "}
            Η πρόβλεψη γίνεται μέσω του Poisson μοντέλου (από τα αποθηκευμένα λ).
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-3">
            <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-4 text-center">
              <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Δείγμα</p>
              <p className="text-2xl font-bold text-gray-100">{btts.total_gg + btts.total_ng}</p>
              <p className="text-xs text-gray-500 mt-1">ολοκληρωμένοι αγώνες με λ</p>
              <div className="flex justify-center gap-4 mt-2 text-xs">
                <span className="text-green-400 font-semibold">{btts.total_gg} GG</span>
                <span className="text-gray-500">/</span>
                <span className="text-red-400 font-semibold">{btts.total_ng} NG</span>
              </div>
            </div>
            <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-4 text-center">
              <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Συνολική Ακρίβεια</p>
              <p className={`text-2xl font-bold ${accentForAccuracy(btts.overall_accuracy) === "green" ? "text-green-400" : accentForAccuracy(btts.overall_accuracy) === "yellow" ? "text-yellow-400" : "text-red-400"}`}>
                {pct(btts.overall_accuracy)}
              </p>
              <p className="text-xs text-gray-500 mt-1">
                {btts.correctly_predicted_gg + btts.correctly_predicted_ng} / {btts.total_gg + btts.total_ng} σωστές (GG+NG)
              </p>
            </div>
            <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-4 text-center">
              <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">GG Ακρίβεια</p>
              <p className={`text-2xl font-bold ${accentForAccuracy(btts.gg_precision) === "green" ? "text-green-400" : accentForAccuracy(btts.gg_precision) === "yellow" ? "text-yellow-400" : "text-red-400"}`}>
                {pct(btts.gg_precision)}
              </p>
              <p className="text-xs text-gray-500 mt-1">
                {btts.correctly_predicted_gg} / {btts.predicted_gg} GG προβλέψεων σωστές
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-4">
              <p className="text-xs text-gray-500 mb-1">GG Recall</p>
              <p className={`text-xl font-bold ${accentForAccuracy(btts.gg_recall) === "green" ? "text-green-400" : accentForAccuracy(btts.gg_recall) === "yellow" ? "text-yellow-400" : "text-red-400"}`}>
                {pct(btts.gg_recall)}
              </p>
              <p className="text-xs text-gray-600 mt-1 leading-tight">
                Από {btts.total_gg} πραγματικά GG, πιάσαμε τα {btts.correctly_predicted_gg}
              </p>
            </div>
            <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-4">
              <p className="text-xs text-gray-500 mb-1">NG Recall</p>
              <p className={`text-xl font-bold ${accentForAccuracy(btts.ng_recall) === "green" ? "text-green-400" : accentForAccuracy(btts.ng_recall) === "yellow" ? "text-yellow-400" : "text-red-400"}`}>
                {pct(btts.ng_recall)}
              </p>
              <p className="text-xs text-gray-600 mt-1 leading-tight">
                Από {btts.total_ng} πραγματικά NG, πιάσαμε τα {btts.correctly_predicted_ng}
              </p>
            </div>
            <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-4">
              <p className="text-xs text-gray-500 mb-1">GG Predictions</p>
              <p className="text-xl font-bold text-gray-200">{btts.predicted_gg}</p>
              <p className="text-xs text-gray-600 mt-1 leading-tight">αγώνες που προβλέψαμε GG</p>
            </div>
            <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-4">
              <p className="text-xs text-gray-500 mb-1">NG Predictions</p>
              <p className="text-xl font-bold text-gray-200">{btts.predicted_ng}</p>
              <p className="text-xs text-gray-600 mt-1 leading-tight">αγώνες που προβλέψαμε NG</p>
            </div>
          </div>
        </section>
      )}

      {/* ── ROI Tracker ───────────────────────────────────────────────────── */}
      <section>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
          ROI Tracker
        </h2>
        {s.roi ? (
          <ROICard roi={s.roi} bttsStats={s.btts_stats} clv={s.clv} />
        ) : (
          <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-6 text-center">
            <p className="text-sm text-gray-500">
              💰 ROI tracking starts once bookmaker odds are stored at prediction time.
            </p>
            <p className="text-xs text-gray-600 mt-1">
              Re-run <code className="font-mono bg-pitch-700 px-1 rounded">compute_predictions.py</code> for upcoming matches to begin accumulating data.
            </p>
          </div>
        )}
      </section>

      {/* ── Cumulative EV Chart ────────────────────────────────────────────── */}
      <section>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
          Cumulative EV vs P&L
        </h2>
        <EVChart series={s.ev_series} />
      </section>

      {/* ── Calibration charts ────────────────────────────────────────────── */}
      <section>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
          Calibration
        </h2>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <CalibrationChart buckets={s.calibration} />
          <ResultCalibrationChart data={s.result_calibration ?? null} />
          {s.btts_calibration.length >= 2 && (
            <BTTSCalibrationChart buckets={s.btts_calibration} />
          )}
        </div>
      </section>

      {/* ── Model version history ──────────────────────────────────────────── */}
      {s.by_model_version.length > 1 && (
        <section>
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
            By Model Version
          </h2>
          <div className="overflow-x-auto rounded-xl border border-pitch-700">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-pitch-800 text-gray-400 text-xs uppercase tracking-wide">
                  <th className="px-4 py-3 text-left">Version</th>
                  <th className="px-4 py-3 text-right">Games</th>
                  <th className="px-4 py-3 text-right">Result %</th>
                  <th className="px-4 py-3 text-right">O/U %</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-pitch-700">
                {s.by_model_version.map((mv) => (
                  <tr key={mv.model_version} className="hover:bg-pitch-800/50 transition-colors">
                    <td className="px-4 py-3 font-mono text-gray-300">{mv.model_version}</td>
                    <td className="px-4 py-3 text-right text-gray-400">{mv.total}</td>
                    <td className={`px-4 py-3 text-right font-semibold ${accentForAccuracy(mv.result_accuracy) === "green" ? "text-green-400" : accentForAccuracy(mv.result_accuracy) === "yellow" ? "text-yellow-400" : "text-red-400"}`}>
                      {pct(mv.result_accuracy)}
                    </td>
                    <td className={`px-4 py-3 text-right font-semibold ${accentForAccuracy(mv.goals_accuracy) === "green" ? "text-green-400" : accentForAccuracy(mv.goals_accuracy) === "yellow" ? "text-yellow-400" : "text-red-400"}`}>
                      {pct(mv.goals_accuracy)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
