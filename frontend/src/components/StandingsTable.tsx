import { type Standings } from "@/lib/api";

// The API names the zones in the language of the competition regulations; the
// UI speaks Greek. Anything unmapped (a new competition) falls through as-is
// rather than rendering blank.
const ZONE_EL: Record<string, string> = {
  "Champions League": "Champions League",
  "Promotion":        "Άνοδος",
  "Europe":           "Ευρώπη",
  "Libertadores":     "Libertadores",
  "Round of 16":      "Απευθείας 16άδα",
  "Play-off":         "Play-off 16άδας",
  "Relegation":       "Υποβιβασμός",
  "Eliminated":       "Αποκλεισμός",
};

const zoneLabel = (s: string) => ZONE_EL[s] ?? s;

/**
 * League table with zone shading. The top zone means different things in
 * different competitions (Champions League vs promotion play-off vs
 * Libertadores), so its label comes from the API rather than being hardcoded.
 */
export default function StandingsTable({ table }: { table: Standings }) {
  if (!table || table.rows.length === 0) return null;

  return (
    <div className="card p-5 space-y-3">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
          📋 Βαθμολογία
        </h2>
        <span className="text-[11px] text-gray-600 tabular-nums">
          {table.season}
          {table.is_final && " · τελική"}
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[10px] uppercase tracking-wide text-gray-500">
              <th className="py-1.5 pr-2 text-left font-medium">#</th>
              <th className="py-1.5 pr-2 text-left font-medium">Ομάδα</th>
              <th className="py-1.5 px-1.5 text-right font-medium">Α</th>
              <th className="py-1.5 px-1.5 text-right font-medium hidden sm:table-cell">Ν</th>
              <th className="py-1.5 px-1.5 text-right font-medium hidden sm:table-cell">Ι</th>
              <th className="py-1.5 px-1.5 text-right font-medium hidden sm:table-cell">Η</th>
              <th className="py-1.5 px-1.5 text-right font-medium">Δ</th>
              <th className="py-1.5 pl-1.5 text-right font-medium">Β</th>
            </tr>
          </thead>
          <tbody>
            {table.rows.map((r) => {
              // Zone is carried per row so a mid-table team is never shaded by
              // an off-by-one in the UI's own position maths.
              const tint =
                r.zone === "top"
                  ? "bg-green-500/10"
                  : r.zone === "playoff"
                    ? "bg-amber-500/10"
                    : r.zone === "bottom"
                      ? "bg-rose-500/10"
                      : "";
              const bar =
                r.zone === "top"
                  ? "border-l-2 border-green-500"
                  : r.zone === "playoff"
                    ? "border-l-2 border-amber-500"
                    : r.zone === "bottom"
                      ? "border-l-2 border-rose-500"
                      : "border-l-2 border-transparent";
              return (
                <tr key={r.team} className={`${tint} border-t border-pitch-800`}>
                  <td className={`py-1.5 pr-2 tabular-nums text-gray-500 ${bar} pl-2`}>
                    {r.position}
                  </td>
                  <td className="py-1.5 pr-2 text-gray-200 truncate max-w-[9rem]">{r.team}</td>
                  <td className="py-1.5 px-1.5 text-right tabular-nums text-gray-500">{r.played}</td>
                  <td className="py-1.5 px-1.5 text-right tabular-nums text-gray-500 hidden sm:table-cell">{r.won}</td>
                  <td className="py-1.5 px-1.5 text-right tabular-nums text-gray-500 hidden sm:table-cell">{r.drawn}</td>
                  <td className="py-1.5 px-1.5 text-right tabular-nums text-gray-500 hidden sm:table-cell">{r.lost}</td>
                  <td className="py-1.5 px-1.5 text-right tabular-nums text-gray-400">
                    {r.goal_diff > 0 ? `+${r.goal_diff}` : r.goal_diff}
                  </td>
                  <td className="py-1.5 pl-1.5 text-right tabular-nums font-semibold text-gray-100">
                    {r.points}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-gray-500 pt-1">
        {table.top_n > 0 && (
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-sm bg-green-500/70" />
            {zoneLabel(table.top_zone)}
          </span>
        )}
        {table.playoff_zone && (
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-sm bg-amber-500/70" />
            {zoneLabel(table.playoff_zone)}
          </span>
        )}
        {(table.bottom_n > 0 || table.playoff_zone) && (
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-sm bg-rose-500/70" />
            {zoneLabel(table.bottom_zone)}
          </span>
        )}
      </div>
    </div>
  );
}
