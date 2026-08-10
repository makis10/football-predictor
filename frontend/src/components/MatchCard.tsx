import Link from "next/link";
import TrackButton from "@/components/TrackButton";
import { ProbabilityBar } from "@/components/ProbabilityBar";
import {
  type Match,
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

  // The model's pick is the outcome it rates highest — plain argmax.
  // NOT the biggest gap against the bookmaker: that selection was measured at
  // 32% against 53% for argmax over the same 470 settled fixtures, because
  // "where we disagree most with the market" is also "where we are most wrong".
  const pick = p
    ? [
        { label: t("matchCard.pickHome"), prob: p.home_win_prob, tone: "win" as const },
        { label: t("matchCard.pickDraw"), prob: p.draw_prob, tone: "neutral" as const },
        { label: t("matchCard.pickAway"), prob: p.away_win_prob, tone: "lose" as const },
      ].reduce((best, c) => (c.prob > best.prob ? c : best))
    : null;

  return (
    <Link href={matchHref(match)} className="group block">
      <div className="card relative flex h-full flex-col gap-3 p-4 transition-colors hover:border-line">
        {/* National fixtures aren't club matches — no tracking row. */}
        {!isNational && <TrackButton matchId={match.id} />}

        {/* League + kick-off */}
        <div className="flex items-center justify-between gap-2 text-[11px] text-chalk-3">
          <span className="flex min-w-0 items-center gap-1.5">
            <span className="shrink-0">{leagueFlag(match.league)}</span>
            <span className="truncate">{leagueLabel(match.league)}</span>
            {roundLabel(match.round) && (
              <span className="badge shrink-0 bg-ink-700 px-1.5 py-0 text-[10px] text-chalk-3">
                {roundLabel(match.round)}
              </span>
            )}
          </span>
          <span className="shrink-0 font-data tabular-nums text-chalk-2">{when}</span>
        </div>

        {/* Teams + score */}
        <div className="flex items-center justify-between gap-2">
          <span className="flex-1 truncate font-display text-[15px] font-bold text-chalk">
            {match.home_team}
          </span>

          {hasResult ? (
            <span className="shrink-0 font-data text-lg font-bold tabular-nums text-chalk">
              {match.home_goals}–{match.away_goals}
            </span>
          ) : (
            <span className="shrink-0 text-[11px] text-chalk-3">vs</span>
          )}

          <span className="flex-1 truncate text-right font-display text-[15px] font-bold text-chalk">
            {match.away_team}
          </span>
        </div>

        {/* Prediction */}
        {p && p.insufficient_data ? (
          <div className="mt-auto">
            <span className="text-xs italic text-chalk-3">
              {/* Name the side we actually lack. Saying "unknown teams" on a
                  PAOK or Benfica tie reads as a broken site — most of these
                  fixtures pair a club we model with one from a league nobody
                  publishes history for. `knownTeams` is absent on the list
                  payload, so fall back to the generic wording. */}
              {match.unknown_teams?.length
                ? t("matchCard.insufficientNamed", {
                    teams: match.unknown_teams.join(", "),
                  })
                : t("matchCard.insufficient")}
            </span>
          </div>
        ) : p && pick ? (
          <div className="mt-auto space-y-2.5">
            {/* The pick, with its uncertainty band. One bar rather than three:
                in a grid of 20 cards the reader is scanning for "what does the
                model think, and how much does it mean it" — the full H/D/A
                split belongs on the detail page, where there is room to read it. */}
            <ProbabilityBar
              label={pick.label}
              probability={pick.prob}
              confidence={p.confidence}
              tone={pick.tone}
              emphasis
            />

            <div className="flex items-center justify-between gap-2 text-[11px]">
              <span className="font-data tabular-nums text-chalk-3">
                {Math.round(p.home_win_prob * 100)}·{Math.round(p.draw_prob * 100)}·
                {Math.round(p.away_win_prob * 100)}
              </span>
              <span
                className={`badge ${
                  p.goals_prediction === "OVER"
                    ? "bg-est/15 text-est"
                    : "bg-chalk-2/10 text-chalk-2"
                }`}
              >
                {p.goals_prediction} 2.5
              </span>
            </div>
          </div>
        ) : (
          <div className="mt-auto">
            <span className="text-xs italic text-chalk-3">
              {t("matchCard.noPrediction")}
            </span>
          </div>
        )}
      </div>
    </Link>
  );
}
