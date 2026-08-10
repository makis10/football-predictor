import Link from "next/link";
import {
  type Match,
  type PredictionEmbed,
  confidenceDot,
  formatDate,
  formatKickoff,
  leagueFlag,
  leagueLabel,
} from "@/lib/api";

interface Props {
  match: Match;
}

/** Derive the actual W/D/L label from the score */
function actualOutcome(match: Match): "H" | "D" | "A" | null {
  if (match.home_goals == null || match.away_goals == null) return null;
  if (match.home_goals > match.away_goals) return "H";
  if (match.home_goals === match.away_goals) return "D";
  return "A";
}

/** What outcome did the model most strongly predict? */
function predictedOutcome(p: PredictionEmbed): "H" | "D" | "A" {
  const { home_win_prob, draw_prob, away_win_prob } = p;
  if (home_win_prob >= draw_prob && home_win_prob >= away_win_prob) return "H";
  if (draw_prob >= home_win_prob && draw_prob >= away_win_prob) return "D";
  return "A";
}

/** Was the goals prediction correct? */
function goalsCorrect(match: Match, p: PredictionEmbed): boolean | null {
  if (match.home_goals == null || match.away_goals == null) return null;
  const total = match.home_goals + match.away_goals;
  const actual = total > 2.5 ? "OVER" : "UNDER";
  return p.goals_prediction === actual;
}

export default function ResultCard({ match }: Props) {
  const p = match.prediction ?? null;
  const actual = actualOutcome(match);
  const predicted = p ? predictedOutcome(p) : null;
  const resultCorrect = actual && predicted ? actual === predicted : null;
  const goalsOk = p ? goalsCorrect(match, p) : null;
  // Cards on the Recent Results page live under a per-day header, so the
  // date is already obvious.  Show the kick-off time here; fall back to the
  // short date when no time is known (legacy fixtures).
  const when =
    formatKickoff(match.match_date, match.kickoff_time) ??
    formatDate(match.match_date);

  return (
    <Link href={`/matches/${match.id}`} className="block group">
      <div className="card p-4 hover:border-line transition-colors h-full flex flex-col gap-3">
        {/* League + kick-off time */}
        <div className="flex items-center justify-between text-xs text-chalk-3">
          <span>
            {leagueFlag(match.league)} {leagueLabel(match.league)}
          </span>
          <span className="tabular-nums">{when}</span>
        </div>

        {/* Teams + score */}
        <div className="flex items-center justify-between gap-2">
          <span className="font-semibold text-sm text-chalk truncate flex-1">
            {match.home_team}
          </span>
          <span className="text-lg font-bold text-chalk shrink-0 tabular-nums">
            {match.home_goals} – {match.away_goals}
          </span>
          <span className="font-semibold text-sm text-chalk truncate flex-1 text-right">
            {match.away_team}
          </span>
        </div>

        {/* Prediction row */}
        {p ? (
          <div className="mt-auto space-y-2">
            {/* Win/Draw/Loss probability bar */}
            <div className="flex gap-1 h-1.5 rounded-full overflow-hidden">
              <div
                className="bg-win rounded-l-full"
                style={{ width: `${Math.round(p.home_win_prob * 100)}%` }}
              />
              <div
                className="bg-chalk-2"
                style={{ width: `${Math.round(p.draw_prob * 100)}%` }}
              />
              <div
                className="bg-chalk-2 rounded-r-full"
                style={{ width: `${Math.round(p.away_win_prob * 100)}%` }}
              />
            </div>

            <div className="flex items-center justify-between text-xs">
              <span className="text-chalk-2 tabular-nums">
                {Math.round(p.home_win_prob * 100)}% ·{" "}
                {Math.round(p.draw_prob * 100)}% ·{" "}
                {Math.round(p.away_win_prob * 100)}%
              </span>

              {/* Goals badge + confidence dot */}
              <div className="flex items-center gap-1.5">
                <span
                  className={`badge ${
                    p.goals_prediction === "OVER"
                      ? "bg-est/20 text-est"
                      : "bg-chalk-2/20 text-chalk-2"
                  }`}
                >
                  {p.goals_prediction} 2.5
                </span>
                <span
                  className={`w-1.5 h-1.5 rounded-full ${confidenceDot(p.confidence)}`}
                  title={`${p.confidence} confidence`}
                />
              </div>
            </div>

            {/* Correctness indicators */}
            <div className="flex items-center justify-between text-xs border-t border-line pt-2">
              <span className="flex items-center gap-1 text-chalk-3">
                Result:{" "}
                {resultCorrect === true && (
                  <span className="text-win font-semibold">✓ correct</span>
                )}
                {resultCorrect === false && (
                  <span className="text-lose font-semibold">✗ wrong</span>
                )}
                {resultCorrect === null && (
                  <span className="text-chalk-3">—</span>
                )}
              </span>
              <span className="flex items-center gap-1 text-chalk-3">
                Goals:{" "}
                {goalsOk === true && (
                  <span className="text-win font-semibold">✓</span>
                )}
                {goalsOk === false && (
                  <span className="text-lose font-semibold">✗</span>
                )}
                {goalsOk === null && (
                  <span className="text-chalk-3">—</span>
                )}
              </span>
            </div>
          </div>
        ) : (
          <div className="mt-auto">
            <span className="text-xs text-chalk-3 italic">No prediction available</span>
          </div>
        )}
      </div>
    </Link>
  );
}
