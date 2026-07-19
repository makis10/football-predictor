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
import { getServerT } from "@/lib/i18n-server";

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
  const t = await getServerT();
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
          <p className="text-lg font-medium text-gray-400">{t("stats.unavailable.title")}</p>
          <p className="text-sm mt-1">
            {t("stats.unavailable.body")}
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
            <h1 className="text-2xl font-bold text-gray-100 mb-1">{t("stats.intl.title")}</h1>
          </div>
          <Suspense>
            <LeagueFilter active={league} basePath="/stats" />
          </Suspense>
          <div className="text-center py-16 text-gray-500">
            <p className="text-4xl mb-3">🌍</p>
            <p className="font-medium">{t("stats.intl.empty")}</p>
          </div>
        </div>
      );
    }

    const ns = nationalStats;
    return (
      <div className="space-y-10">
        <div>
          <h1 className="text-2xl font-bold text-gray-100 mb-1">{t("stats.intl.title")}</h1>
          <p className="text-sm text-gray-500">
            {t("stats.intl.subtitle", { n: ns.total })}
          </p>
        </div>

        <Suspense>
          <LeagueFilter active={league} basePath="/stats" />
        </Suspense>

        {/* Overall hero cards */}
        <section>
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
            {t("stats.allTimeN", { n: ns.total })}
          </h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatCard
              label={t("stats.resultAccuracy")}
              value={pct(ns.result_accuracy)}
              sub={t("stats.correctFrac", { c: ns.result_correct, t: ns.total })}
              accent={accentForAccuracy(ns.result_accuracy)}
            />
            <StatCard
              label={t("stats.ouAccuracy")}
              value={pct(ns.over_accuracy)}
              sub={t("stats.correctFrac", { c: ns.over_correct, t: ns.total })}
              accent={accentForAccuracy(ns.over_accuracy)}
            />
            <StatCard
              label={t("stats.bothCorrect")}
              value={pct(ns.both_accuracy)}
              sub={t("stats.frac", { c: ns.both_correct, t: ns.total })}
              accent={accentForAccuracy(ns.both_accuracy)}
            />
            <StatCard
              label={t("stats.matchesTracked")}
              value={ns.total.toLocaleString()}
              sub={t("stats.withStored")}
              accent="gray"
            />
          </div>
        </section>

        {/* By tournament */}
        {ns.by_tournament.length > 0 && (
          <section>
            <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
              {t("stats.byTournament")}
            </h2>
            <LeagueTable
              rows={ns.by_tournament.map((row) => ({
                league:          row.tournament,
                total:           row.total,
                result_correct:  row.result_correct,
                goals_correct:   row.over_correct,
                both_correct:    row.both_correct,
                result_accuracy: row.result_accuracy,
                goals_accuracy:  row.over_accuracy,
                both_accuracy:   row.both_accuracy,
              }))}
            />
          </section>
        )}

        {/* By confidence */}
        {ns.by_confidence.length > 0 && (
          <section>
            <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
              {t("stats.byConfidence")}
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
                      {t("stats.nMatches", { n: c.total })}
                    </span>
                  </p>
                  <AccuracyBar
                    label={t("stats.resultAccuracyBar")}
                    value={c.result_accuracy}
                    color={
                      c.confidence === "HIGH"   ? "bg-green-500" :
                      c.confidence === "MEDIUM" ? "bg-yellow-500" :
                      "bg-gray-500"
                    }
                  />
                  <p className="text-xs text-gray-500">
                    {t("stats.correctFrac", { c: c.result_correct, t: c.total })}
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
              {t("stats.drawPrediction")}
            </h2>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <StatCard label={t("stats.totalDraws")}      value={ns.draw_stats.total_draws}     sub={t("stats.actualDraws")} accent="gray" />
              <StatCard label={t("stats.drawPredictions")} value={ns.draw_stats.predicted_draws}  sub={t("stats.predictedAsDraw")} accent="gray" />
              <StatCard label={t("stats.drawRecall")}      value={pct(ns.draw_stats.recall)}     sub={t("stats.ofActualDrawsCaught")} accent={accentForAccuracy(ns.draw_stats.recall)} />
              <StatCard label={t("stats.drawPrecision")}   value={pct(ns.draw_stats.precision)}  sub={t("stats.ofDrawPredsCorrect")} accent={accentForAccuracy(ns.draw_stats.precision)} />
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
        <h1 className="text-2xl font-bold text-gray-100 mb-1">{t("stats.title")}</h1>
        <p className="text-sm text-gray-500">
          {t("stats.subtitle", { when: computedAt })}
        </p>
      </div>

      {/* Methodology cutoff — honest flag: all-time numbers mix two models */}
      {s.methodology && s.methodology.settled_before > 0 && (
        <div className="rounded-xl border border-amber-700/40 bg-amber-950/20 p-4 text-sm">
          <p className="font-semibold text-amber-300 mb-1">{t("stats.methodology.title", { cutoff: s.methodology.cutoff })}</p>
          <p className="text-gray-300 leading-relaxed">
            {t("stats.methodology.body", {
              cutoff: s.methodology.cutoff,
              before: s.methodology.settled_before,
              after: s.methodology.settled_after,
            })}
          </p>
          {/* Per-regime accuracy — no methodology mixing within a row */}
          {s.methodology.regimes && s.methodology.regimes.length > 0 && (
            <div className="mt-3 space-y-1">
              <div className="grid grid-cols-[1fr_4.5rem_4.5rem_3.5rem] gap-2 text-[11px] text-gray-500 uppercase tracking-wide">
                <span>{t("stats.methodology.regime")}</span>
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
                      {" "}({r.from_date ?? "…"} → {r.to_date ?? t("stats.methodology.now")})
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
          <p className="font-semibold text-gray-300 mb-1">{t("stats.injury.title")}</p>
          <p className="text-gray-400 text-xs mb-2">
            {t("stats.injury.body", { n: s.injury_adjustment.matches })}
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
              {t("stats.topPicks.title")}
            </h2>
            <span className="ml-auto text-xs text-gray-500">
              {t("stats.topPicks.caption")}
            </span>
          </div>

          {/* Hero cards */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
            <div className="rounded-lg bg-pitch-800/80 border border-amber-700/30 p-4 text-center">
              <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">{t("stats.topPicks.accuracy")}</p>
              <p className={`text-3xl font-bold ${
                topPicks.accuracy >= 0.57 ? "text-green-400" :
                topPicks.accuracy >= 0.48 ? "text-yellow-400" : "text-red-400"
              }`}>
                {pct(topPicks.accuracy)}
              </p>
              <p className="text-xs text-gray-500 mt-1">{t("stats.topPicks.correctN", { c: topPicks.correct, t: topPicks.total })}</p>
            </div>

            <div className="rounded-lg bg-pitch-800/80 border border-amber-700/30 p-4 text-center">
              <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">{t("stats.topPicks.vsOverall")}</p>
              <p className={`text-3xl font-bold ${
                topPicks.vs_overall_accuracy > 0.02 ? "text-green-400" :
                topPicks.vs_overall_accuracy > -0.02 ? "text-yellow-400" : "text-red-400"
              }`}>
                {topPicks.vs_overall_accuracy >= 0 ? "+" : ""}{pct(topPicks.vs_overall_accuracy)}
              </p>
              <p className="text-xs text-gray-500 mt-1">{t("stats.topPicks.diffFrom", { pct: pct(all.result_accuracy) })}</p>
            </div>

            <div className="rounded-lg bg-pitch-800/80 border border-amber-700/30 p-4 text-center">
              <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">{t("stats.topPicks.avgProb")}</p>
              <p className="text-3xl font-bold text-amber-400">
                {Math.round(topPicks.avg_pick_prob * 100)}%
              </p>
              <p className="text-xs text-gray-500 mt-1">{t("stats.topPicks.topPickConfidence")}</p>
            </div>

            <div className="rounded-lg bg-pitch-800/80 border border-amber-700/30 p-4 text-center">
              <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">{t("stats.topPicks.totalPicks")}</p>
              <p className="text-3xl font-bold text-gray-100">{topPicks.total}</p>
              <p className="text-xs text-gray-500 mt-1">{t("stats.topPicks.perMatchDay")}</p>
            </div>
          </div>

          {/* Breakdown by market */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {topPicks.result_picks > 0 && (
              <div className="rounded-lg bg-pitch-800/60 border border-pitch-700 p-3">
                <p className="text-xs font-semibold text-gray-400 uppercase mb-2">{t("stats.topPicks.result")}</p>
                <div className="flex items-end justify-between">
                  <div>
                    <p className={`text-2xl font-bold ${
                      topPicks.result_accuracy >= 0.57 ? "text-green-400" :
                      topPicks.result_accuracy >= 0.48 ? "text-yellow-400" : "text-red-400"
                    }`}>{pct(topPicks.result_accuracy)}</p>
                    <p className="text-xs text-gray-500">{t("stats.topPicks.correctN", { c: topPicks.result_correct, t: topPicks.result_picks })}</p>
                  </div>
                  <p className="text-xs text-gray-600">{t("stats.topPicks.picks", { n: topPicks.result_picks })}</p>
                </div>
              </div>
            )}
            {topPicks.goals_picks > 0 && (
              <div className="rounded-lg bg-pitch-800/60 border border-pitch-700 p-3">
                <p className="text-xs font-semibold text-gray-400 uppercase mb-2">{t("stats.topPicks.ou")}</p>
                <div className="flex items-end justify-between">
                  <div>
                    <p className={`text-2xl font-bold ${
                      topPicks.goals_accuracy >= 0.57 ? "text-green-400" :
                      topPicks.goals_accuracy >= 0.48 ? "text-yellow-400" : "text-red-400"
                    }`}>{pct(topPicks.goals_accuracy)}</p>
                    <p className="text-xs text-gray-500">{t("stats.topPicks.correctN", { c: topPicks.goals_correct, t: topPicks.goals_picks })}</p>
                  </div>
                  <p className="text-xs text-gray-600">{t("stats.topPicks.picks", { n: topPicks.goals_picks })}</p>
                </div>
              </div>
            )}
          </div>

          <p className="text-[10px] text-gray-600 mt-3 leading-relaxed">
            {t("stats.topPicks.note")}
          </p>
        </section>
      )}

      {/* ── All-time hero cards ────────────────────────────────────────────── */}
      <section>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
          {t("stats.allTimeN", { n: all.total })}
        </h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <StatCard
            label={t("stats.resultAccuracy")}
            value={pct(all.result_accuracy)}
            sub={t("stats.correctFrac", { c: all.result_correct, t: all.total })}
            accent={accentForAccuracy(all.result_accuracy)}
          />
          <StatCard
            label={t("stats.ouAccuracy")}
            value={pct(all.goals_accuracy)}
            sub={t("stats.correctFrac", { c: all.goals_correct, t: all.total })}
            accent={accentForAccuracy(all.goals_accuracy)}
          />
          <StatCard
            label={t("stats.bothCorrect")}
            value={pct(all.both_accuracy)}
            sub={t("stats.frac", { c: all.both_correct, t: all.total })}
            accent={accentForAccuracy(all.both_accuracy)}
          />
          <StatCard
            label={t("stats.matchesTracked")}
            value={all.total.toLocaleString()}
            sub={t("stats.withStored")}
            accent="gray"
          />
        </div>
      </section>

      {/* ── Rolling windows ────────────────────────────────────────────────── */}
      <section>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
          {t("stats.rollingPerformance")}
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {/* Last 7 days */}
          <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-4 space-y-3">
            <p className="text-sm font-semibold text-gray-300">
              {t("stats.last7")}
              <span className="ml-2 text-xs font-normal text-gray-500">
                {t("stats.nMatches", { n: last7.total })}
              </span>
            </p>
            <AccuracyBar label={t("stats.result")} value={last7.result_accuracy} color="bg-green-500" />
            <AccuracyBar label={t("stats.ou")}     value={last7.goals_accuracy}  color="bg-blue-500" />
            <AccuracyBar label={t("stats.both")}   value={last7.both_accuracy}   color="bg-purple-500" />
          </div>

          {/* Last 30 days */}
          <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-4 space-y-3">
            <p className="text-sm font-semibold text-gray-300">
              {t("stats.last30")}
              <span className="ml-2 text-xs font-normal text-gray-500">
                {t("stats.nMatches", { n: last30.total })}
              </span>
            </p>
            <AccuracyBar label={t("stats.result")} value={last30.result_accuracy} color="bg-green-500" />
            <AccuracyBar label={t("stats.ou")}     value={last30.goals_accuracy}  color="bg-blue-500" />
            <AccuracyBar label={t("stats.both")}   value={last30.both_accuracy}   color="bg-purple-500" />
          </div>
        </div>
      </section>

      {/* ── By league ─────────────────────────────────────────────────────── */}
      <section>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
          {t("stats.byLeague")}
        </h2>
        <LeagueTable rows={s.by_league} />
      </section>

      {/* ── International — By Tournament ─────────────────────────────────── */}
      {nationalStats && nationalStats.by_tournament.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
            {t("stats.intlByTournament")}
          </h2>
          <LeagueTable
            rows={nationalStats.by_tournament.map((row) => ({
              league:          row.tournament,
              total:           row.total,
              result_correct:  row.result_correct,
              goals_correct:   row.over_correct,
              both_correct:    row.both_correct,
              result_accuracy: row.result_accuracy,
              goals_accuracy:  row.over_accuracy,
              both_accuracy:   row.both_accuracy,
            }))}
          />
        </section>
      )}

      {/* ── By confidence ─────────────────────────────────────────────────── */}
      {/* Club-only: the national pipeline defines the label with a different
          formula/thresholds, so the tiers are NOT comparable — shown separately. */}
      <section>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
          {t("stats.byConfidence")} <span className="text-gray-600 normal-case">{t("stats.byConfidenceClub")}</span>
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
                  {t("stats.nMatches", { n: c!.total })}
                </span>
              </p>
              <AccuracyBar
                label={t("stats.resultAccuracyBar")}
                value={c!.result_accuracy}
                color={
                  c!.confidence === "high"   ? "bg-green-500" :
                  c!.confidence === "medium" ? "bg-yellow-500" :
                  "bg-gray-500"
                }
              />
              <p className="text-xs text-gray-500">
                {t("stats.correctFrac", { c: c!.result_correct, t: c!.total })}
              </p>
            </div>
          ))}
        </div>
        <p className="text-xs text-gray-600 mt-2">
          {t("stats.confHelp")}
        </p>

        {/* National — different label semantics (p_max ≥ 0.65 → HIGH, no O/U term) */}
        {s.by_confidence_national && s.by_confidence_national.some((c) => c.total > 0) && (
          <div className="mt-4">
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
              {t("stats.internationals")} <span className="text-gray-600 normal-case">{t("stats.intlScale")}</span>
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
                    <span className="ml-2 text-xs font-normal text-gray-500">{t("stats.nMatches", { n: c.total })}</span>
                  </p>
                  <AccuracyBar
                    label={t("stats.resultAccuracyBar")}
                    value={c.result_accuracy}
                    color={
                      c.confidence === "high"   ? "bg-green-500" :
                      c.confidence === "medium" ? "bg-yellow-500" :
                      "bg-gray-500"
                    }
                  />
                  <p className="text-xs text-gray-500">{t("stats.correctFrac", { c: c.result_correct, t: c.total })}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      {/* ── Predicted outcome breakdown ───────────────────────────────────── */}
      <section>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
          {t("stats.byPredictedOutcome")}
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {/* Result outcomes */}
          <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-4 space-y-3">
            <p className="text-sm font-semibold text-gray-300">{t("stats.matchResult")}</p>
            {resultOutcomes.map((o) => (
              <div key={o.predicted} className="space-y-1">
                <AccuracyBar
                  label={
                    o.predicted === "H" ? t("stats.homeWin") :
                    o.predicted === "D" ? t("stats.draw") :
                    t("stats.awayWin")
                  }
                  value={o.accuracy}
                  color={
                    o.predicted === "H" ? "bg-green-500" :
                    o.predicted === "D" ? "bg-gray-500" :
                    "bg-blue-500"
                  }
                />
                <p className="text-xs text-gray-500 pl-1">
                  {t("stats.correctFrac", { c: o.correct, t: o.total })}
                </p>
              </div>
            ))}
          </div>

          {/* O/U outcomes */}
          <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-4 space-y-3">
            <p className="text-sm font-semibold text-gray-300">{t("stats.overUnder")}</p>
            {goalsOutcomes.map((o) => (
              <div key={o.predicted} className="space-y-1">
                <AccuracyBar
                  label={o.predicted === "OVER" ? t("stats.over25") : t("stats.under25")}
                  value={o.accuracy}
                  color={o.predicted === "OVER" ? "bg-orange-500" : "bg-sky-500"}
                />
                <p className="text-xs text-gray-500 pl-1">
                  {t("stats.correctFrac", { c: o.correct, t: o.total })}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Draw specialist stats ──────────────────────────────────────────── */}
      <section>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
          {t("stats.drawPrediction")}
        </h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <StatCard
            label={t("stats.totalDraws")}
            value={draw.total_draws}
            sub={t("stats.totalDrawsSub")}
            accent="gray"
          />
          <StatCard
            label={t("stats.drawPredictions")}
            value={draw.predicted_draws}
            sub={t("stats.drawPredictionsSub")}
            accent="gray"
          />
          <StatCard
            label={t("stats.drawRecall")}
            value={pct(draw.recall)}
            sub={t("stats.drawRecallSub")}
            accent={accentForAccuracy(draw.recall)}
          />
          <StatCard
            label={t("stats.drawPrecision")}
            value={pct(draw.precision)}
            sub={t("stats.drawPrecisionSub")}
            accent={accentForAccuracy(draw.precision)}
          />
        </div>
        <p className="text-xs text-gray-600 mt-2">
          {t("stats.drawNote", { pct: pct(draw.total_draws / (all.total || 1)) })}
        </p>
      </section>

      {/* ── BTTS (Goal / No Goal) stats ───────────────────────────────────── */}
      {btts && (
        <section>
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
            {t("stats.bttsTitle")}
          </h2>

          {/* What is GG/NG */}
          <div className="rounded-xl border border-pitch-700 bg-pitch-800/40 p-3 mb-3 text-xs text-gray-400 leading-relaxed">
            {t("stats.bttsIntro", { gg: t("stats.bttsGG"), ng: t("stats.bttsNG") })}
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-3">
            <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-4 text-center">
              <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">{t("stats.bttsSample")}</p>
              <p className="text-2xl font-bold text-gray-100">{btts.total_gg + btts.total_ng}</p>
              <p className="text-xs text-gray-500 mt-1">{t("stats.bttsCompletedWithLambda")}</p>
              <div className="flex justify-center gap-4 mt-2 text-xs">
                <span className="text-green-400 font-semibold">{btts.total_gg} GG</span>
                <span className="text-gray-500">/</span>
                <span className="text-red-400 font-semibold">{btts.total_ng} NG</span>
              </div>
            </div>
            <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-4 text-center">
              <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">{t("stats.bttsOverallAcc")}</p>
              <p className={`text-2xl font-bold ${accentForAccuracy(btts.overall_accuracy) === "green" ? "text-green-400" : accentForAccuracy(btts.overall_accuracy) === "yellow" ? "text-yellow-400" : "text-red-400"}`}>
                {pct(btts.overall_accuracy)}
              </p>
              <p className="text-xs text-gray-500 mt-1">
                {t("stats.bttsCorrectGGNG", { c: btts.correctly_predicted_gg + btts.correctly_predicted_ng, t: btts.total_gg + btts.total_ng })}
              </p>
            </div>
            <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-4 text-center">
              <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">{t("stats.bttsGGAcc")}</p>
              <p className={`text-2xl font-bold ${accentForAccuracy(btts.gg_precision) === "green" ? "text-green-400" : accentForAccuracy(btts.gg_precision) === "yellow" ? "text-yellow-400" : "text-red-400"}`}>
                {pct(btts.gg_precision)}
              </p>
              <p className="text-xs text-gray-500 mt-1">
                {t("stats.bttsGGPredsCorrect", { c: btts.correctly_predicted_gg, t: btts.predicted_gg })}
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-4">
              <p className="text-xs text-gray-500 mb-1">{t("stats.bttsGGRecall")}</p>
              <p className={`text-xl font-bold ${accentForAccuracy(btts.gg_recall) === "green" ? "text-green-400" : accentForAccuracy(btts.gg_recall) === "yellow" ? "text-yellow-400" : "text-red-400"}`}>
                {pct(btts.gg_recall)}
              </p>
              <p className="text-xs text-gray-600 mt-1 leading-tight">
                {t("stats.bttsGGRecallSub", { t: btts.total_gg, c: btts.correctly_predicted_gg })}
              </p>
            </div>
            <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-4">
              <p className="text-xs text-gray-500 mb-1">{t("stats.bttsNGRecall")}</p>
              <p className={`text-xl font-bold ${accentForAccuracy(btts.ng_recall) === "green" ? "text-green-400" : accentForAccuracy(btts.ng_recall) === "yellow" ? "text-yellow-400" : "text-red-400"}`}>
                {pct(btts.ng_recall)}
              </p>
              <p className="text-xs text-gray-600 mt-1 leading-tight">
                {t("stats.bttsNGRecallSub", { t: btts.total_ng, c: btts.correctly_predicted_ng })}
              </p>
            </div>
            <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-4">
              <p className="text-xs text-gray-500 mb-1">{t("stats.bttsGGPredictions")}</p>
              <p className="text-xl font-bold text-gray-200">{btts.predicted_gg}</p>
              <p className="text-xs text-gray-600 mt-1 leading-tight">{t("stats.bttsGGPredictedSub")}</p>
            </div>
            <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-4">
              <p className="text-xs text-gray-500 mb-1">{t("stats.bttsNGPredictions")}</p>
              <p className="text-xl font-bold text-gray-200">{btts.predicted_ng}</p>
              <p className="text-xs text-gray-600 mt-1 leading-tight">{t("stats.bttsNGPredictedSub")}</p>
            </div>
          </div>
        </section>
      )}

      {/* ── ROI Tracker ───────────────────────────────────────────────────── */}
      <section>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
          {t("stats.roiTracker")}
        </h2>
        {s.roi ? (
          <ROICard roi={s.roi} bttsStats={s.btts_stats} clv={s.clv} t={t} />
        ) : (
          <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-6 text-center">
            <p className="text-sm text-gray-500">
              {t("stats.roiEmpty")}
            </p>
            <p className="text-xs text-gray-600 mt-1">
              {t("stats.roiEmptySub")}
            </p>
          </div>
        )}
      </section>

      {/* ── Cumulative EV Chart ────────────────────────────────────────────── */}
      <section>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
          {t("stats.cumEV")}
        </h2>
        <EVChart series={s.ev_series} />
      </section>

      {/* ── Calibration charts ────────────────────────────────────────────── */}
      <section>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
          {t("stats.calibration")}
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
            {t("stats.byModelVersion")}
          </h2>
          <div className="overflow-x-auto rounded-xl border border-pitch-700">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-pitch-800 text-gray-400 text-xs uppercase tracking-wide">
                  <th className="px-4 py-3 text-left">{t("stats.version")}</th>
                  <th className="px-4 py-3 text-right">{t("stats.games")}</th>
                  <th className="px-4 py-3 text-right">{t("stats.resultPct")}</th>
                  <th className="px-4 py-3 text-right">{t("stats.ouPct")}</th>
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
