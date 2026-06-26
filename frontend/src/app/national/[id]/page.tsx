export const dynamic = "force-dynamic";

import { notFound } from "next/navigation";
import BackLink from "@/components/BackLink";
import {
  getNationalPrediction,
  getPlayerProps,
  confidenceColor,
  confidenceDot,
  formatDate,
  formatKickoffUtc,
  hasMatchEndedUtc,
  type PlayerProp,
} from "@/lib/api";
import { WinProbabilityBars, GoalsProbabilityBar, BttsProbabilityBar } from "@/components/PredictionBar";
import MatchAnalysisPanel from "@/components/MatchAnalysis";
import PlayerPropsPanel from "@/components/PlayerPropsPanel";

interface Props {
  params: Promise<{ id: string }>;
}

/** Settlement pill — green ✓ when we caught it, red ✗ when we missed. */
function HitPill({ hit, label }: { hit: boolean | null | undefined; label?: string }) {
  if (hit == null) return null;
  return (
    <span
      className={`badge font-semibold ${
        hit ? "bg-green-500/20 text-green-400" : "bg-rose-500/20 text-rose-400"
      }`}
    >
      {hit ? "✓" : "✗"}
      {label ? ` ${label}` : ""}
    </span>
  );
}

export default async function NationalMatchDetailPage({ params }: Props) {
  const id = Number((await params).id);
  if (isNaN(id)) notFound();

  let prediction;
  try {
    prediction = await getNationalPrediction(id);
  } catch {
    notFound();
  }

  // Player props (best-effort — only present for fixtures we've priced).
  let propTeams: Record<string, PlayerProp[]> = {};
  try {
    propTeams = (await getPlayerProps(id)).teams;
  } catch {
    /* none yet */
  }

  const hasResult =
    prediction.actual_home_goals !== null && prediction.actual_away_goals !== null;
  const isCorrect =
    hasResult && prediction.prediction === prediction.actual_result;
  const hasEnded =
    hasResult || hasMatchEndedUtc(prediction.kickoff_utc);

  // Kick-off time in the user's timezone ("20:00", "04:00 +1"), when known.
  const kickoffTime = formatKickoffUtc(prediction.kickoff_utc, prediction.match_date);

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      {/* Back — returns to wherever the user came from (history), not a fixed route */}
      <BackLink fallback="/" label="← Back" />

      {/* Match header card */}
      <div className="card p-6 space-y-4">
        <div className="flex items-center justify-between text-sm text-gray-500">
          <span>🏆 {prediction.tournament}</span>
          <span className="badge bg-pitch-800 text-gray-400 tabular-nums">
            {formatDate(prediction.match_date)}
            {kickoffTime ? ` · ${kickoffTime}` : ""}
          </span>
        </div>

        <div className="flex items-center gap-4">
          <div className="flex-1 text-center space-y-1">
            <p className="text-xl font-bold text-white leading-tight">
              {prediction.home_team}
            </p>
            <p className="text-xs text-gray-500">{prediction.neutral ? "Neutral" : "Home"}</p>
          </div>

          <div className="text-center shrink-0">
            {hasResult ? (
              <>
                <p className="text-4xl font-black tabular-nums text-white">
                  {prediction.actual_home_goals} – {prediction.actual_away_goals}
                </p>
                <p className={`text-xs font-medium mt-1 ${isCorrect ? "text-green-400" : "text-red-400"}`}>
                  {isCorrect ? "✓ Correct" : "✗ Wrong"} · Pred: {prediction.prediction}
                </p>
              </>
            ) : (
              <p className="text-2xl font-bold text-gray-600">vs</p>
            )}
          </div>

          <div className="flex-1 text-center space-y-1">
            <p className="text-xl font-bold text-white leading-tight">
              {prediction.away_team}
            </p>
            <p className="text-xs text-gray-500">Away</p>
          </div>
        </div>
      </div>

      {/* Confidence */}
      <div className="flex items-center gap-2 px-1 text-sm">
        <span className={`w-2 h-2 rounded-full ${confidenceDot(prediction.confidence)}`} />
        <span className={`font-medium capitalize ${confidenceColor(prediction.confidence)}`}>
          {prediction.confidence.toLowerCase()} confidence
        </span>
      </div>

      {/* Win / Draw / Loss */}
      <div className="card p-5 space-y-3">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
          Win · Draw · Loss
        </h2>
        <WinProbabilityBars
          homeTeam={prediction.home_team}
          awayTeam={prediction.away_team}
          homeWin={prediction.home_win_prob}
          draw={prediction.draw_prob}
          awayWin={prediction.away_win_prob}
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
              prediction.over_2_5_prob > 0.5
                ? "bg-orange-500/20 text-orange-400"
                : "bg-sky-600/20 text-sky-400"
            }`}
          >
            {prediction.over_2_5_prob > 0.5 ? "OVER" : "UNDER"} 2.5
          </span>
        </div>
        <GoalsProbabilityBar overProb={prediction.over_2_5_prob} />
      </div>

      {/* BTTS */}
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

      {/* Elo ratings */}
      {(prediction.h_elo != null || prediction.a_elo != null) && (
        <div className="card p-5 space-y-3">
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
            Elo Ratings
          </h2>
          <div className="flex items-center justify-between text-sm">
            <div className="text-center">
              <p className="text-white font-bold text-lg tabular-nums">
                {prediction.h_elo != null ? Math.round(prediction.h_elo) : "—"}
              </p>
              <p className="text-gray-500 text-xs">{prediction.home_team}</p>
            </div>
            <span className="text-gray-600">vs</span>
            <div className="text-center">
              <p className="text-white font-bold text-lg tabular-nums">
                {prediction.a_elo != null ? Math.round(prediction.a_elo) : "—"}
              </p>
              <p className="text-gray-500 text-xs">{prediction.away_team}</p>
            </div>
          </div>
        </div>
      )}

      {/* Expected cards (yellow+red) per team */}
      {(prediction.exp_home_cards != null || prediction.exp_away_cards != null) && (
        <div className="card p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
              🟨 Expected Cards
            </h2>
            {hasResult && prediction.cards_hit != null && (
              <HitPill hit={prediction.cards_hit} label={prediction.cards_hit ? "πιάσαμε" : "χάσαμε"} />
            )}
          </div>
          <div className="flex items-center justify-between text-sm">
            <div className="text-center">
              <p className="text-white font-bold text-lg tabular-nums">
                {prediction.exp_home_cards != null ? prediction.exp_home_cards.toFixed(1) : "—"}
              </p>
              <p className="text-gray-500 text-xs">{prediction.home_team}</p>
            </div>
            <span className="text-gray-600 text-xs">
              total ≈ {(((prediction.exp_home_cards ?? 0) + (prediction.exp_away_cards ?? 0)) || 0).toFixed(1)}
            </span>
            <div className="text-center">
              <p className="text-white font-bold text-lg tabular-nums">
                {prediction.exp_away_cards != null ? prediction.exp_away_cards.toFixed(1) : "—"}
              </p>
              <p className="text-gray-500 text-xs">{prediction.away_team}</p>
            </div>
          </div>
          {hasResult && (prediction.actual_home_cards != null || prediction.actual_away_cards != null) && (
            <div className="flex items-center justify-between text-xs border-t border-pitch-700 pt-2">
              <span className="tabular-nums text-emerald-400 font-semibold">
                {prediction.actual_home_cards ?? "—"}
              </span>
              <span className="text-gray-500">
                Πραγματικά · σύνολο {((prediction.actual_home_cards ?? 0) + (prediction.actual_away_cards ?? 0)).toFixed(0)}
              </span>
              <span className="tabular-nums text-emerald-400 font-semibold">
                {prediction.actual_away_cards ?? "—"}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Expected corners per team */}
      {(prediction.exp_home_corners != null || prediction.exp_away_corners != null) && (
        <div className="card p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
              🚩 Expected Corners
            </h2>
            {hasResult && prediction.corners_hit != null && (
              <HitPill hit={prediction.corners_hit} label={prediction.corners_hit ? "πιάσαμε" : "χάσαμε"} />
            )}
          </div>
          <div className="flex items-center justify-between text-sm">
            <div className="text-center">
              <p className="text-white font-bold text-lg tabular-nums">
                {prediction.exp_home_corners != null ? prediction.exp_home_corners.toFixed(1) : "—"}
              </p>
              <p className="text-gray-500 text-xs">{prediction.home_team}</p>
            </div>
            <span className="text-gray-600 text-xs">
              total ≈ {(((prediction.exp_home_corners ?? 0) + (prediction.exp_away_corners ?? 0)) || 0).toFixed(1)}
            </span>
            <div className="text-center">
              <p className="text-white font-bold text-lg tabular-nums">
                {prediction.exp_away_corners != null ? prediction.exp_away_corners.toFixed(1) : "—"}
              </p>
              <p className="text-gray-500 text-xs">{prediction.away_team}</p>
            </div>
          </div>
          {prediction.corners_over_9_5_prob != null && (
            <p className="text-center text-gray-500 text-xs">
              Over 9.5 corners: {(prediction.corners_over_9_5_prob * 100).toFixed(0)}%
            </p>
          )}
          {hasResult && (prediction.actual_home_corners != null || prediction.actual_away_corners != null) && (
            <div className="flex items-center justify-between text-xs border-t border-pitch-700 pt-2">
              <span className="tabular-nums text-emerald-400 font-semibold">
                {prediction.actual_home_corners ?? "—"}
              </span>
              <span className="text-gray-500">
                Πραγματικά · σύνολο {(prediction.actual_home_corners ?? 0) + (prediction.actual_away_corners ?? 0)}
              </span>
              <span className="tabular-nums text-emerald-400 font-semibold">
                {prediction.actual_away_corners ?? "—"}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Correct score — most likely scorelines */}
      {prediction.top_scores && prediction.top_scores.length > 0 && (
        <div className="card p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
              🎯 Πιθανά Σκορ
            </h2>
            <div className="flex items-center gap-2">
              {prediction.most_likely_score && (
                <span className="badge bg-pitch-800 text-gray-300 font-semibold tabular-nums">
                  {prediction.most_likely_score}
                </span>
              )}
              {hasResult && (
                <HitPill
                  hit={prediction.score_hit}
                  label={
                    prediction.score_hit ? "πιάσαμε" : prediction.score_in_top ? "top-6" : "χάσαμε"
                  }
                />
              )}
            </div>
          </div>
          {hasResult && (
            <p className="text-xs text-gray-500">
              Πραγματικό σκορ:{" "}
              <span className="tabular-nums text-emerald-400 font-semibold">
                {prediction.actual_home_goals}-{prediction.actual_away_goals}
              </span>
            </p>
          )}
          <div className="space-y-1.5">
            {prediction.top_scores.slice(0, 6).map((s) => {
              const isActual =
                hasResult &&
                s.score === `${prediction.actual_home_goals}-${prediction.actual_away_goals}`;
              return (
                <div key={s.score} className="flex items-center gap-3 text-sm">
                  <span
                    className={`w-10 tabular-nums font-medium ${
                      isActual ? "text-emerald-400" : "text-gray-200"
                    }`}
                  >
                    {s.score}
                    {isActual ? " ✓" : ""}
                  </span>
                  <div className="flex-1 h-2 rounded-full bg-pitch-800 overflow-hidden">
                    <div
                      className={`h-full rounded-full ${isActual ? "bg-emerald-400" : "bg-green-500/60"}`}
                      style={{ width: `${Math.min(100, (s.prob / prediction.top_scores![0].prob) * 100)}%` }}
                    />
                  </div>
                  <span className="w-12 text-right tabular-nums text-gray-400">
                    {Math.round(s.prob * 100)}%
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Player props (scorer / SoT / assist) */}
      <PlayerPropsPanel teams={propTeams} />

      {/* AI Analysis + bookmaker comparison — only for upcoming matches */}
      {!hasEnded && (
        <MatchAnalysisPanel
          matchId={prediction.id}
          homeTeam={prediction.home_team}
          awayTeam={prediction.away_team}
          isNational
        />
      )}

      <p className="text-xs text-gray-600 text-center px-4">
        Predictions are for entertainment only.
      </p>
    </div>
  );
}
