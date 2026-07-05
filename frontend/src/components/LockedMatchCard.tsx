/**
 * Locked fixture card — freemium teaser for logged-out visitors.
 *
 * Shows only the public bits (competition, teams, kick-off); the prediction is
 * NOT rendered at all (server component → the numbers never reach the HTML, so
 * the gate can't be bypassed with dev-tools). Clicking anywhere goes to
 * /register. The free taste is the Top-3 picks row above the grid.
 */
import Link from "next/link";
import { Match, leagueFlag, leagueLabel, formatKickoff } from "@/lib/api";

export default function LockedMatchCard({ match }: { match: Match }) {
  return (
    <Link
      href="/register"
      className="card p-4 flex flex-col gap-3 relative overflow-hidden group hover:border-green-600/50 transition-colors"
    >
      <div className="flex items-center justify-between text-xs text-gray-500">
        <span>
          {leagueFlag(match.league)} {leagueLabel(match.league)}
        </span>
        <span>{formatKickoff(match.match_date, match.kickoff_time)}</span>
      </div>

      <div className="flex items-center justify-between gap-2 text-sm font-medium text-gray-100">
        <span className="truncate">{match.home_team}</span>
        <span className="text-gray-600 shrink-0">vs</span>
        <span className="truncate text-right">{match.away_team}</span>
      </div>

      {/* Locked prediction area — placeholder bars, no real data behind them */}
      <div className="relative rounded-lg border border-pitch-700 bg-pitch-800/60 px-3 py-3">
        <div className="flex gap-1.5 opacity-30 blur-[2px] select-none" aria-hidden>
          <div className="h-2 rounded-full bg-green-500/60 w-2/5" />
          <div className="h-2 rounded-full bg-gray-500/60 w-1/5" />
          <div className="h-2 rounded-full bg-sky-500/60 w-2/5" />
        </div>
        <div className="mt-2 flex items-center gap-2 text-xs">
          <span className="text-amber-400">🔒</span>
          <span className="text-gray-300">
            Πρόβλεψη μόνο για μέλη —{" "}
            <span className="text-green-400 font-semibold group-hover:underline">
              κάνε δωρεάν εγγραφή
            </span>
          </span>
        </div>
      </div>
    </Link>
  );
}
