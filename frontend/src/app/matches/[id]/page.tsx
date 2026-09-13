// Always SSR — match state (score, analysis, odds) changes in real time.
export const dynamic = "force-dynamic";

import Link from "next/link";
import { notFound } from "next/navigation";
import {
  getMatch,
  getPrediction,
  getFooterAccuracy,
  isNotFound,
  getClubPlayerProps,
  confidenceColor,
  confidenceDot,
  formatDate,
  formatKickoff,
  hasMatchEnded,
  leagueFlag,
  leagueLabel,
  type PlayerProp,
} from "@/lib/api";
import { WinProbabilityBars, GoalsProbabilityBar, BttsProbabilityBar } from "@/components/PredictionBar";
import { getServerT } from "@/lib/i18n-server";
import MatchAnalysisPanel from "@/components/MatchAnalysis";
import PlayerPropsPanel from "@/components/PlayerPropsPanel";
import LogBetButton from "@/components/LogBetButton";
import LockedDetailPanel from "@/components/LockedDetailPanel";
import { getSession } from "@/lib/auth";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function MatchDetailPage({ params }: Props) {
  const t = await getServerT();
  const id = Number((await params).id);
  if (isNaN(id)) notFound();

  let match, prediction;
  try {
    match = await getMatch(id);
  } catch (e) {
    // Only a real 404 is a missing page. Any failure used to become notFound(),
    // so a backend restart served real, public match pages as HTTP 404.
    if (isNotFound(e)) notFound();
    throw e;
  }

  try {
    prediction = await getPrediction(id);
  } catch {
    prediction = null;
  }

  const hasResult =
    match.home_goals !== null && match.away_goals !== null;

  // Once a match has been under way for 2+ hours, treat it as finished even
  // if the score hasn't been scraped yet — no point burning Claude API calls
  // and refetching bookmaker odds for a game whose result is already decided.
  const hasEnded =
    hasResult || hasMatchEnded(match.match_date, match.kickoff_time);

  const kickoff = formatKickoff(match.match_date, match.kickoff_time);

  // Freemium: upcoming-match predictions are members-only. Finished matches
  // stay public — they're the transparency proof. Rendered server-side, so no
  // premium numbers reach the HTML for logged-out visitors.
  if (!hasEnded && !(await getSession())) {
    return (
      <div className="max-w-2xl mx-auto space-y-6">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-sm text-chalk-3 hover:text-chalk-2 transition-colors"
        >
          {t("match.back")}
        </Link>
        <div className="card p-6 space-y-1 text-center">
          <p className="text-xs text-chalk-3">{kickoff}</p>
          <p className="text-lg font-semibold text-chalk">
            {match.home_team} <span className="text-chalk-3">vs</span> {match.away_team}
          </p>
        </div>
        <LockedDetailPanel home={match.home_team} away={match.away_team} t={t} />
      </div>
    );
  }

  // Player props (best-effort — only for club leagues we've ingested). Fetched
  // past the freemium gate so logged-out upcoming views don't pay for it.
  let propTeams: Record<string, PlayerProp[]> = {};
  try {
    propTeams = (await getClubPlayerProps(id)).teams;
  } catch {
    /* none yet */
  }

  // The live record, as the footer states it — never a hardcoded figure: this
  // page said "~52% (result)" while /stats measured 49%.
  const acc = await getFooterAccuracy();

  // The page's own probabilities. For a finished match they are the record; for
  // an upcoming one the analysis panel carries them, and these stand in when
  // that request fails (slow odds feed, 504) — which left the page with no
  // probabilities at all.
  const bars = prediction && !prediction.insufficient_data ? (
            <>
              {/* Win/Draw/Loss */}
              <div className="card p-5 space-y-3">
                <h2 className="text-sm font-semibold text-chalk-2 uppercase tracking-wider">
                  {t("match.section.wdl")}
                </h2>
                <WinProbabilityBars
                  homeTeam={match.home_team}
                  awayTeam={match.away_team}
                  homeWin={prediction.win_probabilities.home_win}
                  draw={prediction.win_probabilities.draw}
                  awayWin={prediction.win_probabilities.away_win}
                />
              </div>

              {/* Goals */}
              <div className="card p-5 space-y-3">
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-semibold text-chalk-2 uppercase tracking-wider">
                    {t("match.section.goals")}
                  </h2>
                  <span
                    className={`badge font-semibold ${
                      prediction.goals.prediction === "OVER"
                        ? "bg-est/20 text-est"
                        : "bg-chalk-2/20 text-chalk-2"
                    }`}
                  >
                    {prediction.goals.prediction} 2.5
                  </span>
                </div>
                <GoalsProbabilityBar overProb={prediction.goals.over_2_5_probability} />
              </div>

              {/* GG / NG — Poisson-derived, loads with the fast prediction endpoint */}
              {prediction.btts_prob != null && (
                <div className="card p-5 space-y-3">
                  <div className="flex items-center justify-between">
                    <h2 className="text-sm font-semibold text-chalk-2 uppercase tracking-wider">
                      {t("match.section.btts")}
                    </h2>
                    {/* The model's own call, at the threshold the training run
                        selected (currently 0.47). This used to be decided here
                        with a hardcoded 0.5, so the badge and the stored label
                        could disagree — and the threshold train.py sweeps every
                        retrain changed nothing anyone saw. */}
                    {/* Absent on a row written before the field existed. Showing
                        "NG" there would be a claim we did not make — the whole
                        point of serving the stored call rather than deciding it
                        here. The probability bar below still renders. */}
                    {prediction.btts_prediction && (
                      <span
                        className={`badge font-semibold ${
                          prediction.btts_prediction === "GG"
                            ? "bg-win/20 text-win"
                            : "bg-lose/20 text-lose"
                        }`}
                      >
                        {prediction.btts_prediction}
                      </span>
                    )}
                  </div>
                  <BttsProbabilityBar bttsProb={prediction.btts_prob}
                                    prediction={prediction.btts_prediction} t={t} />
                </div>
              )}
            </>
  ) : null;

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      {/* Back */}
      <Link
        href="/"
        className="inline-flex items-center gap-1.5 text-sm text-chalk-3 hover:text-chalk-2 transition-colors"
      >
        {t("match.back")}
      </Link>

      {/* Match header card */}
      <div className="card p-6 space-y-4">
        <div className="flex items-center justify-between text-sm text-chalk-3">
          <span>
            {leagueFlag(match.league)} {leagueLabel(match.league)}
          </span>
          <span className="badge bg-ink-700 text-chalk-2">{match.season}</span>
        </div>

        <div className="flex items-center gap-4">
          {/* Home team */}
          <div className="flex-1 text-center space-y-1">
            <p className="text-xl font-bold text-chalk leading-tight">
              {match.home_team}
            </p>
            <p className="text-xs text-chalk-3">{t("match.home")}</p>
          </div>

          {/* Score / vs */}
          <div className="text-center shrink-0">
            {hasResult ? (
              <p className="text-4xl font-black tabular-nums text-chalk">
                {match.home_goals} – {match.away_goals}
              </p>
            ) : (
              <p className="text-2xl font-bold text-chalk-3">vs</p>
            )}
            {/* The full date sits in the listing header; show the kick-off
                time here (rendered in the user's local timezone).  Fall back
                to the date for legacy fixtures with no kick-off time. */}
            <p className="text-xs text-chalk-3 mt-1 tabular-nums">
              {kickoff ?? formatDate(match.match_date)}
            </p>
          </div>

          {/* Away team */}
          <div className="flex-1 text-center space-y-1">
            <p className="text-xl font-bold text-chalk leading-tight">
              {match.away_team}
            </p>
            <p className="text-xs text-chalk-3">{t("match.away")}</p>
          </div>
        </div>
      </div>

      {/* Prediction card */}
      {prediction && prediction.insufficient_data ? (
        <div className="card p-6 text-center text-chalk-2 space-y-2">
          <p className="text-3xl">ℹ️</p>
          <p className="font-medium text-chalk-2">{t("match.insufficient.title")}</p>
          <p className="text-sm text-chalk-3 max-w-md mx-auto">
            {t("match.insufficient.body")}
          </p>
        </div>
      ) : prediction ? (
        <>
          {/* Confidence + model info */}
          <div className="flex items-center justify-between px-1">
            <div className="flex items-center gap-2 text-sm">
              <span
                className={`w-2 h-2 rounded-full ${confidenceDot(prediction.confidence)}`}
              />
              <span className={`font-medium capitalize ${confidenceColor(prediction.confidence)}`}>
                {t("match.confidence", { level: t(`match.conf.${prediction.confidence.toLowerCase()}`) })}
              </span>
            </div>
            <span className="text-xs text-chalk-3">
              {t("match.modelVersion", { v: prediction.model_version })}
            </span>
          </div>

          {/* Bookmaker comparison + Claude analysis + Elo/cards/corners/goals-lines.
              This shared panel is the upcoming-match layout — identical to the
              national page. It already renders Win·Draw·Loss, Over/Under and
              GG/NG, so the standalone bars below are shown ONLY for finished
              matches (where the panel is suppressed to save Claude/Odds credits).
              Keeping both for upcoming would duplicate 1×2/OU and diverge from
              the national layout. */}
          {hasEnded ? bars : (
            <MatchAnalysisPanel
              matchId={id}
              homeTeam={match.home_team}
              awayTeam={match.away_team}
              fallback={bars}
            />
          )}

          {/* Player props (scorer / SoT / assist) — shown when we've priced them */}
          <PlayerPropsPanel teams={propTeams} t={t} />

          {/* Log bet */}
          <LogBetButton
            matchId={id}
            suggestedMarket={prediction.suggested_market ?? null}
          />

          {/* Disclaimer */}
          <p className="text-xs text-chalk-3 text-center px-4">
            {acc
              ? t("match.disclaimer", { n: acc.n, result: acc.result, goals: acc.goals })
              : t("match.disclaimerShort")}
          </p>
        </>
      ) : (
        <div className="card p-6 text-center text-chalk-3">
          <p className="text-3xl mb-2">🤖</p>
          <p>{hasEnded ? t("match.noPrediction.ended") : t("match.noPrediction.upcoming")}</p>
        </div>
      )}
    </div>
  );
}
