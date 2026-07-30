import Link from "next/link";
import TrackButton from "@/components/TrackButton";
import {
  type Match,
  confidenceDot,
  formatDate,
  formatKickoff,
  formatKickoffUtc,
  leagueFlag,
  leagueLabel,
  matchHref,
  roundLabel,
  INTERNATIONAL_LEAGUE,
} from "@/lib/api";
import type { TFunc } from "@/lib/i18n";

interface Props {
  match: Match;
  t: TFunc;
}

export default function MatchCard({ match, t }: Props) {
  const p = match.prediction ?? null;
  const hasResult = match.home_goals !== null && match.away_goals !== null;
  const isNational = match.league?.toLowerCase() === INTERNATIONAL_LEAGUE.toLowerCase();
  // Cards live under a per-day header (e.g. "Saturday, 18 April 2026"), so
  // the date is already obvious.  Show the kick-off time here instead; fall
  // back to the short date when no time is known (legacy fixtures).
  // kickoff_utc (full instant) takes precedence: it also covers kick-offs
  // whose UTC date crosses midnight ("04:00 +1"), where kickoff_time is null.
  const when =
    formatKickoffUtc(match.kickoff_utc ?? null, match.match_date) ??
    formatKickoff(match.match_date, match.kickoff_time) ??
    formatDate(match.match_date);

  return (
    <Link href={matchHref(match)} className="block group">
      <div className="card p-4 hover:border-gray-600 transition-colors h-full flex flex-col gap-3 relative">
        {/* National fixtures aren't club matches — no tracking row. */}
        {!isNational && <TrackButton matchId={match.id} />}
        {/* League + kick-off time row */}
        <div className="flex items-center justify-between text-xs text-gray-500">
          <span className="flex items-center gap-1.5">
            {leagueFlag(match.league)} {leagueLabel(match.league)}
            {roundLabel(match.round) && (
              <span className="badge bg-pitch-700 text-gray-400 text-[10px] px-1.5 py-0">
                {roundLabel(match.round)}
              </span>
            )}
          </span>
          <span className="tabular-nums">{when}</span>
        </div>

        {/* Teams + score */}
        <div className="flex items-center justify-between gap-2">
          <span className="font-semibold text-sm text-gray-100 truncate flex-1">
            {match.home_team}
          </span>

          {hasResult ? (
            <span className="text-lg font-bold text-white shrink-0 tabular-nums">
              {match.home_goals} – {match.away_goals}
            </span>
          ) : (
            <span className="text-xs text-gray-600 shrink-0">vs</span>
          )}

          <span className="font-semibold text-sm text-gray-100 truncate flex-1 text-right">
            {match.away_team}
          </span>
        </div>

        {/* Prediction row */}
        {p && p.insufficient_data ? (
          <div className="mt-auto">
            <span className="text-xs text-gray-500 italic">
              {/* Name the side we actually lack. Saying "unknown teams" on a
                  PAOK or Benfica tie reads as a broken site — most of these
                  fixtures pair a club we model with one from a league nobody
                  publishes history for. `knownTeams` is absent on the list
                  payload, so fall back to the generic wording. */}
              {match.unknown_teams?.length
                ? t("matchCard.insufficientNamed",
                    { teams: match.unknown_teams.join(", ") })
                : t("matchCard.insufficient")}
            </span>
          </div>
        ) : p ? (
          <div className="mt-auto space-y-2">
            {/* Win / Draw / Loss mini-bars */}
            <div className="flex gap-1 h-1.5 rounded-full overflow-hidden">
              <div
                className="bg-green-500 rounded-l-full"
                style={{ width: `${Math.round(p.home_win_prob * 100)}%` }}
                title={`Home win ${Math.round(p.home_win_prob * 100)}%`}
              />
              <div
                className="bg-gray-500"
                style={{ width: `${Math.round(p.draw_prob * 100)}%` }}
                title={`Draw ${Math.round(p.draw_prob * 100)}%`}
              />
              <div
                className="bg-blue-500 rounded-r-full"
                style={{ width: `${Math.round(p.away_win_prob * 100)}%` }}
                title={`Away win ${Math.round(p.away_win_prob * 100)}%`}
              />
            </div>

            <div className="flex items-center justify-between text-xs">
              {/* Probabilities */}
              <span className="text-gray-400 tabular-nums">
                {Math.round(p.home_win_prob * 100)}% ·{" "}
                {Math.round(p.draw_prob * 100)}% ·{" "}
                {Math.round(p.away_win_prob * 100)}%
              </span>

              {/* Goals badge + value badge + confidence dot */}
              <div className="flex items-center gap-1.5">
                <span
                  className={`badge ${
                    p.goals_prediction === "OVER"
                      ? "bg-orange-500/20 text-orange-400"
                      : "bg-sky-600/20 text-sky-400"
                  }`}
                >
                  {p.goals_prediction} 2.5
                </span>
                {/* Our pick = the outcome the model rates highest, shown with
                    its probability so the reader can see how confident it
                    actually is. This replaced an "⚡ EV +x%" badge: EV measured
                    the model's disagreement with the bookmaker, which turned out
                    to be anti-predictive (those picks landed 32% of the time vs
                    53% for simply taking the most likely outcome). */}
                {(() => {
                  const pick = Math.max(p.home_win_prob, p.draw_prob, p.away_win_prob);
                  const label =
                    pick === p.home_win_prob ? t("matchCard.pickHome")
                    : pick === p.draw_prob   ? t("matchCard.pickDraw")
                    : t("matchCard.pickAway");
                  return (
                    <span
                      className="badge bg-emerald-500/20 text-emerald-400 font-semibold"
                      title={t("matchCard.pickTitle", { n: "470", hit: "53%" })}
                    >
                      {label} {Math.round(pick * 100)}%
                    </span>
                  );
                })()}
                <span
                  className={`w-1.5 h-1.5 rounded-full ${confidenceDot(p.confidence)}`}
                  title={`${p.confidence} confidence`}
                />
              </div>
            </div>
          </div>
        ) : (
          <div className="mt-auto">
            <span className="text-xs text-gray-600 italic">No prediction available</span>
          </div>
        )}
      </div>
    </Link>
  );
}
