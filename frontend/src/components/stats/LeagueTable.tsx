import { LeagueBreakdown } from "@/lib/api";
import type { TFunc } from "@/lib/i18n";
import { leagueFlag, leagueLabel } from "@/lib/api";

interface LeagueTableProps {
  rows: LeagueBreakdown[];
  t: TFunc;
}

function pct(v: number) {
  return `${Math.round(v * 100)}%`;
}

/** Colour by the edge over the row's own no-model floor, as the /stats hero
 *  cards do: 3pp clear is green, above it yellow, at or below it red. A row
 *  without a floor (national tournaments) stays neutral. An absolute 57% painted
 *  Bundesliga O/U 71.6% green against an always-OVER 74.6%, and Ligue 1's
 *  +9.9pp 1x2 edge red. */
function edgeColor(value: number, baseline?: number): string {
  if (!baseline || baseline <= 0 || baseline >= 1) return "text-chalk-2";
  const edge = value - baseline;
  if (edge >= 0.03) return "text-win";
  if (edge > 0) return "text-est";
  return "text-lose";
}

export function LeagueTable({ rows, t }: LeagueTableProps) {
  if (rows.length === 0) {
    return (
      <p className="text-sm text-chalk-3 text-center py-6">{t("stats.table.empty")}</p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-line">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-ink-700 text-chalk-2 text-xs uppercase tracking-wide">
            <th className="px-4 py-3 text-left">{t("stats.league")}</th>
            <th className="px-4 py-3 text-right">{t("stats.games")}</th>
            <th className="px-4 py-3 text-right">{t("stats.resultPct")}</th>
            <th className="px-4 py-3 text-right">{t("stats.ouPct")}</th>
            <th className="px-4 py-3 text-right">{t("stats.bothPct")}</th>
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
              <td className={`px-4 py-3 text-right font-semibold ${edgeColor(r.result_accuracy, r.result_baseline)}`}>
                {pct(r.result_accuracy)}
              </td>
              <td className={`px-4 py-3 text-right font-semibold ${edgeColor(r.goals_accuracy, r.goals_baseline)}`}>
                {pct(r.goals_accuracy)}
              </td>
              <td className={`px-4 py-3 text-right font-semibold text-chalk-2`}>
                {pct(r.both_accuracy)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
