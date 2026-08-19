// Long-term projections live behind their own route so they're discoverable
// (the home page only shows a table once you filter to a league).
//
// Members-only since 2026-08-19, with a public teaser. A title/relegation
// projection is a forecast we sell, not a public fact — but this route was the
// site's biggest indexable surface, so a bare lock traded away the SEO the
// public showcase exists for. Logged-out visitors get the title race three
// teams deep per competition (the same free taste the home page gives with its
// Top-3 picks); everything else — the rest of the field, Europe and relegation
// probabilities, expected points, history, tables — needs an account.
export const dynamic = "force-dynamic";

import type { Metadata } from "next";
import { getStandings, getLeagueProjection, getProjectionHistory } from "@/lib/api";
import ProjectionsBrowser, {
  type CompetitionProjection,
} from "@/components/ProjectionsBrowser";
import { getServerT } from "@/lib/i18n-server";
import { getSession } from "@/lib/auth";
import LockedDetailPanel from "@/components/LockedDetailPanel";
import ProjectionsTeaser from "@/components/ProjectionsTeaser";

export const metadata: Metadata = {
  title: "Long-term Projections | AI Tipster",
  description:
    "Title, Europe-qualification and relegation probabilities for every league and European competition — Monte Carlo from our model.",
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
  { league: "Belgium",      category: "domestic" },
  { league: "Turkey",       category: "domestic" },
  { league: "Scotland",     category: "domestic" },
  { league: "Denmark",      category: "domestic" },
  { league: "Sweden",       category: "domestic" },
  { league: "Norway",       category: "domestic" },
  { league: "Poland",       category: "domestic" },
  { league: "Austria",      category: "domestic" },
  { league: "Switzerland",  category: "domestic" },
  { league: "Romania",      category: "domestic" },
  { league: "Ireland",      category: "domestic" },
  { league: "Finland",      category: "domestic" },
  { league: "CL",           category: "european" },
  { league: "EL",           category: "european" },
  { league: "ECL",          category: "european" },
];

export default async function ProjectionsPage() {
  const t = await getServerT();

  const session = await getSession();

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
        <h1 className="text-2xl font-bold tracking-tight text-chalk">
          {t("projPage.title")}
        </h1>
        <p className="text-sm text-chalk-3 mt-1">
          {t("projPage.desc")}
        </p>
      </div>

      {/* Logged out: the title race three deep, then the lock. This page was
          the site's biggest indexable surface, and a bare lock would have cost
          all of it — the teaser keeps 26 competitions of unique, changing text
          crawlable while the part worth an account stays behind the gate.
          ProjectionsBrowser is never rendered, so the withheld numbers are not
          in the HTML at all. */}
      {session ? (
        <ProjectionsBrowser items={items} />
      ) : (
        <>
          <ProjectionsTeaser items={items} t={t} />
          <LockedDetailPanel
            t={t}
            title={t("locked.projections.title")}
            body={t("locked.projections.body")}
          />
        </>
      )}
    </div>
  );
}
