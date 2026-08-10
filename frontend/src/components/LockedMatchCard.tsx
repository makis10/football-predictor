/**
 * Locked fixture card — freemium teaser for logged-out visitors.
 *
 * Shows only the public bits (competition, teams, kick-off); the prediction is
 * NOT rendered at all (server component → the numbers never reach the HTML, so
 * the gate can't be bypassed with dev-tools). Clicking anywhere goes to
 * /register. The free taste is the Top-3 picks row above the grid.
 */
import Link from "next/link";
import { Match, leagueFlag, leagueLabel, formatKickoff, formatKickoffUtc, formatDate } from "@/lib/api";
import type { TFunc } from "@/lib/i18n";

export default function LockedMatchCard({ match, t }: { match: Match; t: TFunc }) {
  // kickoff_utc takes precedence: covers kick-offs whose UTC date crosses
  // midnight ("04:00 +1"), where kickoff_time is deliberately null.
  const when =
    formatKickoffUtc(match.kickoff_utc ?? null, match.match_date) ??
    formatKickoff(match.match_date, match.kickoff_time) ??
    formatDate(match.match_date);

  return (
    <Link
      href="/register"
      className="card p-4 flex flex-col gap-3 relative overflow-hidden group hover:border-win/50 transition-colors"
    >
      <div className="flex items-center justify-between text-xs text-chalk-3">
        <span>
          {leagueFlag(match.league)} {leagueLabel(match.league)}
        </span>
        <span>{when}</span>
      </div>

      <div className="flex items-center justify-between gap-2 text-sm font-medium text-chalk">
        <span className="truncate">{match.home_team}</span>
        <span className="text-chalk-3 shrink-0">vs</span>
        <span className="truncate text-right">{match.away_team}</span>
      </div>

      {/* Locked prediction area — placeholder bars, no real data behind them */}
      <div className="relative rounded-lg border border-line bg-ink-700/60 px-3 py-3">
        <div className="flex gap-1.5 opacity-30 blur-[2px] select-none" aria-hidden>
          <div className="h-2 rounded-full bg-win/60 w-2/5" />
          <div className="h-2 rounded-full bg-chalk-2/60 w-1/5" />
          <div className="h-2 rounded-full bg-chalk-2/60 w-2/5" />
        </div>
        <div className="mt-2 flex items-center gap-2 text-xs">
          <span className="text-est">🔒</span>
          <span className="text-chalk-2">
            {t("locked.membersOnly")}{" "}
            <span className="text-win font-semibold group-hover:underline">
              {t("locked.signupFree")}
            </span>
          </span>
        </div>
      </div>
    </Link>
  );
}
