// Long-term projections live behind their own route so they're discoverable
// (the home page only shows a table once you filter to a league). Public data —
// results and model projections, no premium picks — so no freemium gate.
export const dynamic = "force-dynamic";

import type { Metadata } from "next";
import { getStandings, getLeagueProjection, getProjectionHistory } from "@/lib/api";
import ProjectionsBrowser, {
  type CompetitionProjection,
} from "@/components/ProjectionsBrowser";

export const metadata: Metadata = {
  title: "Μακροχρόνιες Προγνώσεις | AI Tipster",
  description:
    "Πιθανότητες κατάκτησης, εισόδου στην Ευρώπη και υποβιβασμού για κάθε πρωτάθλημα και ευρωπαϊκή διοργάνωση — Monte Carlo από το μοντέλο μας.",
};

// Competitions that can carry a long-term projection, with their category. The
// friendlies and the "International" pseudo-league have no table, so they're out.
const COMPETITIONS: { league: string; category: "domestic" | "european" }[] = [
  { league: "EPL",          category: "domestic" },
  { league: "LaLiga",       category: "domestic" },
  { league: "SerieA",       category: "domestic" },
  { league: "Bundesliga",   category: "domestic" },
  { league: "Ligue1",       category: "domestic" },
  { league: "Championship",  category: "domestic" },
  { league: "LeagueOne",    category: "domestic" },
  { league: "Eredivisie",   category: "domestic" },
  { league: "PrimeiraLiga", category: "domestic" },
  { league: "GreekSL",      category: "domestic" },
  { league: "BrazilSerieA", category: "domestic" },
  { league: "CL",           category: "european" },
  { league: "EL",           category: "european" },
  { league: "ECL",          category: "european" },
];

export default async function ProjectionsPage() {
  // Fetch every competition's table + projection in parallel. They're all
  // cached (re-primed by the daily warm-up), so this is cheap; a competition
  // that's out of season simply 404s and drops out below.
  const results = await Promise.all(
    COMPETITIONS.map(async ({ league, category }): Promise<CompetitionProjection> => {
      const [table, projection, hist] = await Promise.all([
        getStandings(league).catch(() => null),
        getLeagueProjection(league).catch(() => null),
        getProjectionHistory(league).catch(() => ({ available: false, snapshots: [] })),
      ]);
      return { league, category, table, projection, history: hist.snapshots };
    }),
  );

  // Only show a competition that has SOMETHING (a table or a projection).
  // Exception: UEFA competitions stay visible during the summer qualifying
  // window — the browser renders a "available after the league-phase draw"
  // placeholder instead of silently hiding the tab (users kept asking where
  // the European projections went).
  const items = results.filter((r) => r.table || r.projection || r.category === "european");

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white">
          🔮 Μακροχρόνιες Προγνώσεις
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          Πιθανότητες κατάκτησης, Ευρώπης και υποβιβασμού ανά διοργάνωση —
          Monte Carlo από το τρέχον Elo και τη βαθμολογία.
        </p>
      </div>

      <ProjectionsBrowser items={items} />
    </div>
  );
}
