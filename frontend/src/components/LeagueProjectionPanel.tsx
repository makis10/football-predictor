import { type LeagueProjection } from "@/lib/api";

function pct(v: number): string {
  if (v <= 0) return "—";
  if (v < 0.005) return "<1%";
  return `${Math.round(v * 100)}%`;
}

/** Colour a probability by how meaningful it is, so a 1% doesn't shout. */
function tone(v: number, kind: "good" | "bad"): string {
  if (v < 0.005) return "text-gray-600";
  if (v >= 0.4) return kind === "good" ? "text-emerald-400" : "text-rose-400";
  if (v >= 0.1) return kind === "good" ? "text-emerald-500/80" : "text-rose-500/80";
  return "text-gray-500";
}

/**
 * Season-long Monte Carlo: title / top-zone / relegation odds.
 * Ordered by title chance, which is the question people actually ask.
 */
export default function LeagueProjectionPanel({ proj }: { proj: LeagueProjection }) {
  if (!proj || proj.teams.length === 0) return null;

  return (
    <div className="card p-5 space-y-3">
      <div>
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
            🔮 Πρόγνωση Σεζόν
          </h2>
          <span className="text-[11px] text-gray-600 tabular-nums">{proj.season}</span>
        </div>
        <p className="text-[11px] text-gray-600 mt-1 leading-relaxed">
          {proj.sims.toLocaleString("el-GR")} προσομοιώσεις των{" "}
          {proj.matches_remaining} αγώνων που απομένουν, από το τρέχον Elo και τη
          βαθμολογία. Δεν λαμβάνει υπόψη μεταγραφές ή τραυματισμούς.
        </p>
        {proj.note && (
          <p className="text-[11px] text-gray-500 mt-1.5 leading-relaxed">
            ℹ️ {proj.note}
          </p>
        )}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[10px] uppercase tracking-wide text-gray-500">
              <th className="py-1.5 pr-2 text-left font-medium">Ομάδα</th>
              <th className="py-1.5 px-2 text-right font-medium">Τίτλος</th>
              <th className="py-1.5 px-2 text-right font-medium">{proj.top_zone}</th>
              <th className="py-1.5 px-2 text-right font-medium">Υποβ.</th>
              <th className="py-1.5 pl-2 text-right font-medium">xΒαθ.</th>
            </tr>
          </thead>
          <tbody>
            {proj.teams.map((t) => (
              <tr key={t.team} className="border-t border-pitch-800">
                <td className="py-1.5 pr-2 text-gray-200 truncate max-w-[9rem]">{t.team}</td>
                <td className={`py-1.5 px-2 text-right tabular-nums font-semibold ${tone(t.p_title, "good")}`}>
                  {pct(t.p_title)}
                </td>
                <td className={`py-1.5 px-2 text-right tabular-nums ${tone(t.p_top, "good")}`}>
                  {pct(t.p_top)}
                </td>
                <td className={`py-1.5 px-2 text-right tabular-nums ${tone(t.p_relegated, "bad")}`}>
                  {pct(t.p_relegated)}
                </td>
                <td className="py-1.5 pl-2 text-right tabular-nums text-gray-500">
                  {t.exp_points.toFixed(0)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
