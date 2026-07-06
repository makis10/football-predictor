"use client";

import { useState } from "react";
import Link from "next/link";
import {
  type Match,
  type PredictionEmbed,
  leagueFlag,
  leagueLabel,
  matchHref,
  INTERNATIONAL_LEAGUE,
  getPostmortem,
} from "@/lib/api";
// Grading uses the shared rule (mirrors backend /stats) so the per-card badge
// can't disagree with the page accuracy or /stats. Display labels stay local.
import { gradeMatch, goalsHit, hasResult } from "@/lib/matchGrade";

interface Props {
  match: Match;
}

function predictedOutcome(p: PredictionEmbed): "H" | "D" | "A" {
  const { home_win_prob, draw_prob, away_win_prob } = p;
  if (home_win_prob >= draw_prob && home_win_prob >= away_win_prob) return "H";
  if (draw_prob >= home_win_prob && draw_prob >= away_win_prob) return "D";
  return "A";
}

function outcomeLabel(o: "H" | "D" | "A", home: string, away: string) {
  if (o === "H") return `${home} win`;
  if (o === "D") return "Draw";
  return `${away} win`;
}

export default function RecentResultCard({ match }: Props) {
  const p = match.prediction ?? null;
  const predicted = p ? predictedOutcome(p) : null;
  const goalsOk = hasResult(match) ? goalsHit(match) : null;
  const state = hasResult(match) ? gradeMatch(match) : null;

  const [postmortem, setPostmortem] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const bg =
    state === "correct"
      ? "bg-green-950/60 border-green-700/50 hover:border-green-600"
      : state === "partial"
      ? "bg-blue-950/60 border-blue-700/50 hover:border-blue-600"
      : state === "wrong"
      ? "bg-red-950/60 border-red-700/50 hover:border-red-600"
      : "bg-pitch-900 border-pitch-700 hover:border-gray-600";

  const badge =
    state === "correct"
      ? "bg-green-500/20 text-green-400 border border-green-600/40"
      : state === "partial"
      ? "bg-amber-500/20 text-amber-400 border border-amber-600/40"
      : state === "wrong"
      ? "bg-red-500/20 text-red-400 border border-red-600/40"
      : "bg-gray-700/30 text-gray-500";

  const badgeLabel =
    state === "correct" ? "✓ Correct"
    : state === "partial" ? "◑ Partial"
    : state === "wrong"  ? "✗ Wrong"
    : null;

  async function handlePostmortem(e: React.MouseEvent) {
    e.preventDefault();
    if (postmortem) {
      setPostmortem(null);
      return;
    }
    setLoading(true);
    try {
      const res = await getPostmortem(match.id);
      setPostmortem(res.analysis);
    } catch {
      setPostmortem("Αποτυχία φόρτωσης ανάλυσης.");
    } finally {
      setLoading(false);
    }
  }

  const isInternational = match.league?.toLowerCase() === INTERNATIONAL_LEAGUE.toLowerCase();
  const showPostmortem = (state === "wrong" || state === "partial") && p && !isInternational;

  return (
    <div className={`rounded-xl border transition-colors ${bg} flex flex-col gap-3`}>
      <Link href={matchHref(match)} className="block p-4 pb-0">
        {/* League + correctness badge */}
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-400">
            {leagueFlag(match.league)} {leagueLabel(match.league)}
          </span>
          {badgeLabel !== null ? (
            <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${badge}`}>
              {badgeLabel}
            </span>
          ) : (
            <span className="text-xs text-gray-600 italic">No prediction</span>
          )}
        </div>

        {/* Teams + score */}
        <div className="flex items-center gap-3 mt-3">
          <span className="flex-1 font-semibold text-white text-sm truncate">
            {match.home_team}
          </span>
          {match.home_goals != null && match.away_goals != null ? (
            <span className="text-2xl font-black tabular-nums text-white shrink-0">
              {match.home_goals} – {match.away_goals}
            </span>
          ) : (
            <span className="text-xs font-medium text-amber-500/80 shrink-0 px-2 py-1 rounded-lg bg-amber-500/10 border border-amber-600/20">
              ⏳ Pending
            </span>
          )}
          <span className="flex-1 font-semibold text-white text-sm truncate text-right">
            {match.away_team}
          </span>
        </div>

        {/* Prediction detail */}
        {p && (
          <div className="space-y-2 border-t border-white/5 pt-2 mt-3">
            {/* Probability bar */}
            <div className="flex gap-0.5 h-1.5 rounded-full overflow-hidden">
              <div
                className="bg-green-500"
                style={{ width: `${Math.round(p.home_win_prob * 100)}%` }}
              />
              <div
                className="bg-gray-500"
                style={{ width: `${Math.round(p.draw_prob * 100)}%` }}
              />
              <div
                className="bg-blue-500"
                style={{ width: `${Math.round(p.away_win_prob * 100)}%` }}
              />
            </div>

            {/* Predicted vs actual */}
            <div className="flex items-center justify-between text-xs">
              <span className="text-gray-400">
                Predicted:{" "}
                <span className="text-gray-200 font-medium">
                  {predicted
                    ? outcomeLabel(predicted, match.home_team, match.away_team)
                    : "—"}
                </span>
                <span className="text-gray-600 ml-1 tabular-nums">
                  ({predicted === "H"
                    ? Math.round(p.home_win_prob * 100)
                    : predicted === "D"
                    ? Math.round(p.draw_prob * 100)
                    : Math.round(p.away_win_prob * 100)}%)
                </span>
              </span>

              {/* Goals correctness */}
              <span
                className={`text-xs px-1.5 py-0.5 rounded ${
                  goalsOk === true
                    ? "text-green-400"
                    : goalsOk === false
                    ? "text-red-400"
                    : "text-gray-600"
                }`}
              >
                {p.goals_prediction} 2.5{" "}
                {goalsOk === true ? "✓" : goalsOk === false ? "✗" : ""}
              </span>
            </div>
          </div>
        )}
      </Link>

      {/* Post-mortem section */}
      {showPostmortem && (
        <div className="px-4 pb-4">
          <button
            onClick={handlePostmortem}
            disabled={loading}
            className="w-full py-1.5 text-xs rounded-lg bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors border border-red-700/30 disabled:opacity-50"
          >
            {loading ? "Αναλύω…" : postmortem ? "▲ Κλείσιμο ανάλυσης" : "🔍 Γιατί απέτυχε;"}
          </button>
          {postmortem && (
            <p className="mt-2 text-xs text-gray-400 leading-relaxed border-t border-white/5 pt-2">
              {postmortem}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
