// Always SSR — match state (score, analysis, odds) changes in real time.
export const dynamic = "force-dynamic";

import Link from "next/link";
import { notFound } from "next/navigation";
import {
  getMatch,
  getPrediction,
  confidenceColor,
  confidenceDot,
  formatDate,
  formatKickoff,
  hasMatchEnded,
  leagueFlag,
  leagueLabel,
} from "@/lib/api";
import { WinProbabilityBars, GoalsProbabilityBar, BttsProbabilityBar } from "@/components/PredictionBar";
import MatchAnalysisPanel from "@/components/MatchAnalysis";
import LogBetButton from "@/components/LogBetButton";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function MatchDetailPage({ params }: Props) {
  const id = Number((await params).id);
  if (isNaN(id)) notFound();

  let match, prediction;
  try {
    match = await getMatch(id);
  } catch {
    notFound();
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

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      {/* Back */}
      <Link
        href="/"
        className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-300 transition-colors"
      >
        ← Back to matches
      </Link>

      {/* Match header card */}
      <div className="card p-6 space-y-4">
        <div className="flex items-center justify-between text-sm text-gray-500">
          <span>
            {leagueFlag(match.league)} {leagueLabel(match.league)}
          </span>
          <span className="badge bg-pitch-800 text-gray-400">{match.season}</span>
        </div>

        <div className="flex items-center gap-4">
          {/* Home team */}
          <div className="flex-1 text-center space-y-1">
            <p className="text-xl font-bold text-white leading-tight">
              {match.home_team}
            </p>
            <p className="text-xs text-gray-500">Home</p>
          </div>

          {/* Score / vs */}
          <div className="text-center shrink-0">
            {hasResult ? (
              <p className="text-4xl font-black tabular-nums text-white">
                {match.home_goals} – {match.away_goals}
              </p>
            ) : (
              <p className="text-2xl font-bold text-gray-600">vs</p>
            )}
            {/* The full date sits in the listing header; show the kick-off
                time here (rendered in the user's local timezone).  Fall back
                to the date for legacy fixtures with no kick-off time. */}
            <p className="text-xs text-gray-600 mt-1 tabular-nums">
              {kickoff ?? formatDate(match.match_date)}
            </p>
          </div>

          {/* Away team */}
          <div className="flex-1 text-center space-y-1">
            <p className="text-xl font-bold text-white leading-tight">
              {match.away_team}
            </p>
            <p className="text-xs text-gray-500">Away</p>
          </div>
        </div>
      </div>

      {/* Prediction card */}
      {prediction ? (
        <>
          {/* Confidence + model info */}
          <div className="flex items-center justify-between px-1">
            <div className="flex items-center gap-2 text-sm">
              <span
                className={`w-2 h-2 rounded-full ${confidenceDot(prediction.confidence)}`}
              />
              <span className={`font-medium capitalize ${confidenceColor(prediction.confidence)}`}>
                {prediction.confidence} confidence
              </span>
            </div>
            <span className="text-xs text-gray-600">
              Model v{prediction.model_version}
            </span>
          </div>

          {/* Win/Draw/Loss */}
          <div className="card p-5 space-y-3">
            <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
              Win · Draw · Loss
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
              <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
                Goals · Over / Under 2.5
              </h2>
              <span
                className={`badge font-semibold ${
                  prediction.goals.prediction === "OVER"
                    ? "bg-orange-500/20 text-orange-400"
                    : "bg-sky-600/20 text-sky-400"
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
                <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
                  GG / NG · Both Teams to Score
                </h2>
                <span
                  className={`badge font-semibold ${
                    prediction.btts_prob >= 0.5
                      ? "bg-emerald-500/20 text-emerald-400"
                      : "bg-rose-500/20 text-rose-400"
                  }`}
                >
                  {prediction.btts_prob >= 0.5 ? "GG" : "NG"}
                </span>
              </div>
              <BttsProbabilityBar bttsProb={prediction.btts_prob} />
            </div>
          )}

          {/* Bookmaker comparison + Claude analysis — only for matches that
              are still genuinely "upcoming".  Suppress after kickoff+2h so we
              don't burn Claude / Odds-API credits re-analysing games that are
              already decided, even if the result hasn't been scraped yet. */}
          {!hasEnded && (
            <MatchAnalysisPanel
              matchId={id}
              homeTeam={match.home_team}
              awayTeam={match.away_team}
            />
          )}

          {/* Log bet */}
          <LogBetButton
            matchId={id}
            suggestedMarket={prediction.suggested_market ?? null}
          />

          {/* Disclaimer */}
          <p className="text-xs text-gray-600 text-center px-4">
            Predictions are for entertainment only. Model accuracy: ~52% (result) · ~58% (over/under).
          </p>
        </>
      ) : (
        <div className="card p-6 text-center text-gray-500">
          <p className="text-3xl mb-2">🤖</p>
          <p>Prediction unavailable for this match.</p>
          <p className="text-sm mt-1">Make sure the ML models are trained.</p>
        </div>
      )}
    </div>
  );
}
