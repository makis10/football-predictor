/**
 * Public taste of the long-term projections.
 *
 * /projections went members-only on 2026-08-19, and it was the site's biggest
 * indexable surface — 26 competitions of unique, regularly-changing text. A
 * lock with nothing behind it costs that entirely, so this leaves the same free
 * taste the home page gives with its Top-3 picks: the title race, three teams
 * deep, per competition.
 *
 * What is withheld is the part worth an account: every other team, the
 * Europe-qualification and relegation probabilities, expected points, the
 * history chart, and the tables. Server component — the withheld numbers are
 * never rendered, so this is a gate and not a CSS trick.
 */
import {
  isEuropeanProjection,
  leagueFlag,
  leagueLabel,
  type SeasonProjection,
} from "@/lib/api";
import type { TFunc } from "@/lib/i18n";

/** How many teams the free taste shows. Same number as the home page's picks. */
const TEASER_ROWS = 3;

type Row = { team: string; p: number };

function topThree(projection: SeasonProjection): Row[] {
  const rows: Row[] = isEuropeanProjection(projection)
    ? projection.teams.map((t) => ({ team: t.team, p: t.p_champion }))
    : projection.teams.map((t) => ({ team: t.team, p: t.p_title }));
  return rows
    .filter((r) => r.p > 0)
    .sort((a, b) => b.p - a.p)
    .slice(0, TEASER_ROWS);
}

export default function ProjectionsTeaser({
  items,
  t,
}: {
  items: { league: string; projection: SeasonProjection | null }[];
  t: TFunc;
}) {
  const blocks = items
    .map((i) => ({ league: i.league, rows: i.projection ? topThree(i.projection) : [] }))
    .filter((b) => b.rows.length > 0);

  if (blocks.length === 0) return null;

  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-sm font-semibold text-chalk-2 uppercase tracking-wider">
          {t("projTeaser.title")}
        </h2>
        <p className="text-xs text-chalk-3 mt-0.5">{t("projTeaser.body")}</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {blocks.map(({ league, rows }) => (
          <div key={league} className="card p-3 space-y-2">
            <p className="text-xs text-chalk-3">
              {leagueFlag(league)} {leagueLabel(league)}
            </p>
            <ol className="space-y-1">
              {rows.map((r, i) => (
                <li key={r.team} className="flex items-baseline justify-between gap-2 text-sm">
                  <span className="truncate text-chalk">
                    <span className="text-chalk-3 mr-1.5">{i + 1}.</span>
                    {r.team}
                  </span>
                  <span className="tabular-nums text-chalk-2 shrink-0">
                    {(r.p * 100).toFixed(0)}%
                  </span>
                </li>
              ))}
            </ol>
          </div>
        ))}
      </div>
    </section>
  );
}
