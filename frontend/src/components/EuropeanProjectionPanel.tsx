import { type EuropeanProjection } from "@/lib/api";
import type { TFunc } from "@/lib/i18n";

function pct(v: number): string {
  if (v <= 0) return "—";
  if (v < 0.005) return "<1%";
  return `${Math.round(v * 100)}%`;
}

function tone(v: number): string {
  if (v < 0.005) return "text-gray-600";
  if (v >= 0.15) return "text-amber-300";
  if (v >= 0.05) return "text-amber-500/80";
  return "text-gray-500";
}

/**
 * Who lifts the trophy: league phase replayed, then the knockout bracket.
 * Only the teams with a real chance are listed — a 36-team wall of "<1%" tells
 * nobody anything.
 */
export default function EuropeanProjectionPanel({ proj, t }: { proj: EuropeanProjection; t: TFunc }) {
  if (!proj || proj.teams.length === 0) return null;

  const contenders = proj.teams.filter((row) => row.p_champion >= 0.005).slice(0, 16);
  const rest = proj.teams.length - contenders.length;

  return (
    <div className="card p-5 space-y-3">
      <div>
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
            {t("proj.eu.title")}
          </h2>
          <span className="text-[11px] text-gray-600 tabular-nums">{proj.season}</span>
        </div>
        <p className="text-[11px] text-gray-600 mt-1 leading-relaxed">
          {t("proj.eu.desc", { sims: proj.sims.toLocaleString(), n: proj.matches_remaining })}
        </p>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[10px] uppercase tracking-wide text-gray-500">
              <th className="py-1.5 pr-2 text-left font-medium">{t("proj.team")}</th>
              <th className="py-1.5 px-2 text-right font-medium">{t("proj.eu.win")}</th>
              <th className="py-1.5 px-2 text-right font-medium">{t("proj.eu.final")}</th>
              <th className="py-1.5 pl-2 text-right font-medium">{t("proj.eu.r16")}</th>
            </tr>
          </thead>
          <tbody>
            {contenders.map((row) => (
              <tr key={row.team} className="border-t border-pitch-800">
                <td className="py-1.5 pr-2 text-gray-200 truncate max-w-[10rem]">{row.team}</td>
                <td className={`py-1.5 px-2 text-right tabular-nums font-semibold ${tone(row.p_champion)}`}>
                  {pct(row.p_champion)}
                </td>
                <td className="py-1.5 px-2 text-right tabular-nums text-gray-400">
                  {pct(row.p_final)}
                </td>
                <td className="py-1.5 pl-2 text-right tabular-nums text-gray-500">
                  {pct(row.p_r16)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {rest > 0 && (
        <p className="text-[11px] text-gray-600">
          {t("proj.eu.more", { n: rest })}
        </p>
      )}
    </div>
  );
}
