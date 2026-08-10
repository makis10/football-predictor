"use client";

import { useState } from "react";
import Link from "next/link";
import {
  type Match,
  type PredictionEmbed,
  leagueFlag,
  leagueLabel,
  matchHref,
  roundLabel,
  INTERNATIONAL_LEAGUE,
  getPostmortem,
} from "@/lib/api";
// Grading uses the shared rule (mirrors backend /stats) so the per-card badge
// can't disagree with the page accuracy or /stats. Display labels stay local.
import { gradeMatch, goalsHit, hasResult } from "@/lib/matchGrade";
import { useT } from "@/components/LanguageProvider";

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
  const t = useT();
  const p = match.prediction ?? null;
  const predicted = p ? predictedOutcome(p) : null;
  const goalsOk = hasResult(match) ? goalsHit(match) : null;
  const state = hasResult(match) ? gradeMatch(match) : null;

  const [postmortem, setPostmortem] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const bg =
    state === "correct"
      ? "bg-win/10 border-win/40 hover:border-win"
      : state === "partial"
      ? "bg-chalk-2/10 border-chalk-2/40 hover:border-chalk-2"
      : state === "wrong"
      ? "bg-lose/10 border-lose/40 hover:border-lose"
      : "bg-ink-800 border-line hover:border-line";

  const badge =
    state === "correct"
      ? "bg-win/20 text-win border border-win/40"
      : state === "partial"
      ? "bg-est/20 text-est border border-est/40"
      : state === "wrong"
      ? "bg-lose/20 text-lose border border-lose/40"
      : "bg-ink-600/30 text-chalk-3";

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
      setPostmortem(t("recent.loadFail"));
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
          <span className="flex items-center gap-1.5 text-xs text-chalk-2">
            {leagueFlag(match.league)} {leagueLabel(match.league)}
            {roundLabel(match.round) && (
              <span className="badge bg-ink-600 text-chalk-2 text-[10px] px-1.5 py-0">
                {roundLabel(match.round)}
              </span>
            )}
          </span>
          {badgeLabel !== null ? (
            <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${badge}`}>
              {badgeLabel}
            </span>
          ) : (
            <span className="text-xs text-chalk-3 italic">No prediction</span>
          )}
        </div>

        {/* Teams + score */}
        <div className="flex items-center gap-3 mt-3">
          <span className="flex-1 font-semibold text-chalk text-sm truncate">
            {match.home_team}
          </span>
          {match.home_goals != null && match.away_goals != null ? (
            <span className="text-2xl font-black tabular-nums text-chalk shrink-0">
              {match.home_goals} – {match.away_goals}
            </span>
          ) : (
            <span className="text-xs font-medium text-est/80 shrink-0 px-2 py-1 rounded-lg bg-est/10 border border-est/20">
              ⏳ Pending
            </span>
          )}
          <span className="flex-1 font-semibold text-chalk text-sm truncate text-right">
            {match.away_team}
          </span>
        </div>

        {/* Prediction detail */}
        {p && (
          <div className="space-y-2 border-t border-line-soft pt-2 mt-3">
            {/* Probability bar */}
            <div className="flex gap-0.5 h-1.5 rounded-full overflow-hidden">
              <div
                className="bg-win"
                style={{ width: `${Math.round(p.home_win_prob * 100)}%` }}
              />
              <div
                className="bg-chalk-2"
                style={{ width: `${Math.round(p.draw_prob * 100)}%` }}
              />
              <div
                className="bg-chalk-2"
                style={{ width: `${Math.round(p.away_win_prob * 100)}%` }}
              />
            </div>

            {/* Predicted vs actual */}
            <div className="flex items-center justify-between text-xs">
              <span className="text-chalk-2">
                Predicted:{" "}
                <span className="text-chalk font-medium">
                  {predicted
                    ? outcomeLabel(predicted, match.home_team, match.away_team)
                    : "—"}
                </span>
                <span className="text-chalk-3 ml-1 tabular-nums">
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
                    ? "text-win"
                    : goalsOk === false
                    ? "text-lose"
                    : "text-chalk-3"
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
            className="w-full py-1.5 text-xs rounded-lg bg-lose/10 text-lose hover:bg-lose/20 transition-colors border border-lose/40 disabled:opacity-50"
          >
            {loading ? t("recent.analyzing") : postmortem ? t("recent.closeAnalysis") : t("recent.whyFail")}
          </button>
          {postmortem && (
            <p className="mt-2 text-xs text-chalk-2 leading-relaxed border-t border-line-soft pt-2">
              {postmortem}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
