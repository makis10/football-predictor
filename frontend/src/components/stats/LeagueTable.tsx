import { LeagueBreakdown } from "@/lib/api";
import { leagueFlag, leagueLabel } from "@/lib/api";

interface LeagueTableProps {
  rows: LeagueBreakdown[];
}

function pct(v: number) {
  return `${Math.round(v * 100)}%`;
}

function colorForAccuracy(v: number): string {
  if (v >= 0.57) return "text-win";
  if (v >= 0.48) return "text-est";
  return "text-lose";
}

export function LeagueTable({ rows }: LeagueTableProps) {
  if (rows.length === 0) {
    return (
      <p className="text-sm text-chalk-3 text-center py-6">No data yet.</p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-line">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-ink-700 text-chalk-2 text-xs uppercase tracking-wide">
            <th className="px-4 py-3 text-left">League</th>
            <th className="px-4 py-3 text-right">Games</th>
            <th className="px-4 py-3 text-right">Result %</th>
            <th className="px-4 py-3 text-right">O/U %</th>
            <th className="px-4 py-3 text-right">Both %</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map((r) => (
            <tr
              key={r.league}
              className="hover:bg-ink-700/50 transition-colors"
            >
              <td className="px-4 py-3 font-medium text-chalk">
                <span className="mr-2">{leagueFlag(r.league)}</span>
                {leagueLabel(r.league)}
              </td>
              <td className="px-4 py-3 text-right text-chalk-2">{r.total}</td>
              <td className={`px-4 py-3 text-right font-semibold ${colorForAccuracy(r.result_accuracy)}`}>
                {pct(r.result_accuracy)}
              </td>
              <td className={`px-4 py-3 text-right font-semibold ${colorForAccuracy(r.goals_accuracy)}`}>
                {pct(r.goals_accuracy)}
              </td>
              <td className={`px-4 py-3 text-right font-semibold ${colorForAccuracy(r.both_accuracy)}`}>
                {pct(r.both_accuracy)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
