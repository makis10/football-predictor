// Always SSR — predictions and kickoff times change throughout the day.
export const dynamic = "force-dynamic";

import { Suspense } from "react";
import Link from "next/link";
import {
  getMatches,
  getLeagueProjection,
  isEuropeanProjection,
  getStandings,
  getUpcomingNationalMatches,
  athensDate,
  canonicalLeagueCode,
  formatLongDate,
  INTERNATIONAL_LEAGUE,
} from "@/lib/api";
import MatchCard from "@/components/MatchCard";
import LockedMatchCard from "@/components/LockedMatchCard";
import StandingsTable from "@/components/StandingsTable";
import LeagueProjectionPanel from "@/components/LeagueProjectionPanel";
import EuropeanProjectionPanel from "@/components/EuropeanProjectionPanel";
import { getSession } from "@/lib/auth";
import FilterBar, { type LeagueCount } from "@/components/FilterBar";
import TopPicks from "@/components/TopPicks";
import { getServerT } from "@/lib/i18n-server";

interface PageProps {
  // Next 15+: searchParams is now a Promise.
  searchParams: Promise<{ league?: string; min_odds?: string; min_confidence?: string }>;
}

const DAYS_AHEAD = 3; // today + 2 more days

const CONF_RANK: Record<string, number> = { low: 1, medium: 2, high: 3 };

function filterByMinConfidence<T extends { prediction?: { confidence?: string } | null }>(
  matches: T[],
  minConfidence?: string,
): T[] {
  const minConf = minConfidence?.toLowerCase();
  if (!minConf) return matches;
  return matches.filter(
    (m) => (CONF_RANK[m.prediction?.confidence ?? "low"] ?? 0) >= (CONF_RANK[minConf] ?? 0),
  );
}

async function UpcomingGrid({
  league,
  minOdds,
  minConfidence,
  showPicks = true,
  locked = false,
}: {
  league?: string;
  minOdds?: number;
  minConfidence?: string;
  showPicks?: boolean;
  /** Freemium: logged-out visitors see the Top-3 picks free; every other
      fixture renders as a LockedMatchCard (no prediction data in the HTML). */
  locked?: boolean;
}) {
  const t = await getServerT();
  // Case-insensitive — hand-typed URLs may use ?league=international.
  const isInternational = league?.toLowerCase() === INTERNATIONAL_LEAGUE.toLowerCase();

  let matches = [];
  try {
    if (isInternational) {
      // "International" filter — show upcoming national fixtures only
      matches = filterByMinConfidence(
        await getUpcomingNationalMatches(athensDate(0), athensDate(DAYS_AHEAD - 1), 200, minOdds),
        minConfidence,
      );
    } else {
      matches = await getMatches(league, 100, 0, "upcoming", true, undefined, undefined, DAYS_AHEAD, minOdds, minConfidence);
    }
  } catch {
    return (
      <div className="col-span-full text-center py-16 text-chalk-3">
        <p className="text-4xl mb-3">⚠️</p>
        <p className="font-medium">Could not reach the API.</p>
        <p className="text-sm mt-1">Make sure the backend is running on port 8000.</p>
      </div>
    );
  }

  // Merge upcoming national-team fixtures into the "All Leagues" view (only
  // when no specific club league is selected). National predictions live in a
  // separate table/endpoint; a failure here must not break the club list.
  // National fixtures DO carry bookmaker odds, so the min-odds filter is applied
  // to them too (inside getUpcomingNationalMatches, same argmax-pick semantics).
  if (!league) {
    try {
      // Honour the same confidence filter the club list uses.
      const filtered = filterByMinConfidence(
        await getUpcomingNationalMatches(athensDate(0), athensDate(DAYS_AHEAD - 1), 200, minOdds),
        minConfidence,
      );
      matches = [...matches, ...filtered].sort((a, b) =>
        a.match_date !== b.match_date
          ? a.match_date.localeCompare(b.match_date)
          // kickoff_utc (full ISO) sorts chronologically; kickoff_time is null
          // for games whose UTC date crosses midnight, so it can't order them.
          : (a.kickoff_utc ?? a.kickoff_time ?? "99").localeCompare(b.kickoff_utc ?? b.kickoff_time ?? "99"),
      );
    } catch {
      // national merge is best-effort — ignore and show club fixtures only
    }
  }

  if (matches.length === 0) {
    return (
      <div className="col-span-full text-center py-16 text-chalk-3">
        <p className="text-4xl mb-3">📅</p>
        <p className="font-medium text-chalk-2">{t("home.empty")}</p>
        <p className="text-sm mt-1 font-mono text-xs">
          docker compose exec backend python scripts/import_fixtures.py
        </p>
      </div>
    );
  }

  // Group by date so we can render date separators
  const byDate = matches.reduce<Record<string, typeof matches>>((acc, m) => {
    const d = m.match_date;
    acc[d] = acc[d] ?? [];
    acc[d].push(m);
    return acc;
  }, {});

  return (
    <>
      {/* Top 3 picks — shown when no league filter is active */}
      {showPicks && <TopPicks matches={matches} t={t} />}

      {Object.entries(byDate).map(([dateStr, dayMatches]) => (
        <div key={dateStr} className="col-span-full space-y-4">
          <h2 className="border-b border-line pb-2 font-display text-sm font-extrabold uppercase tracking-[0.14em] text-chalk-3">
            {formatLongDate(dateStr, "en-GB")}
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {dayMatches.map((match) =>
              locked ? (
                <LockedMatchCard key={`${match.league}-${match.id}`} match={match} t={t} />
              ) : (
                <MatchCard key={`${match.league}-${match.id}`} match={match} t={t} />
              ),
            )}
          </div>
        </div>
      ))}
    </>
  );
}

/**
 * League table for the selected competition. Public: it is a record of results,
 * not a prediction, so it sits outside the freemium gate. Silently renders
 * nothing for competitions with no played matches (a cup, or a season that
 * hasn't kicked off).
 */
async function LeagueStandings({ league }: { league: string }) {
  const t = await getServerT();
  // Table and projection are independent: a finished season has a table but no
  // projection; a season that hasn't kicked off has a projection but no table.
  // Fetch both, render whichever exists.
  const [table, proj] = await Promise.all([
    getStandings(league).catch(() => null),
    getLeagueProjection(league).catch(() => null),
  ]);
  if (!table && !proj) return null;
  return (
    <div className="space-y-6">
      {table && <StandingsTable table={table} t={t} />}
      {/* A domestic season projects to a table position, a UEFA one to a trophy
          — different questions, so different panels. */}
      {proj &&
        (isEuropeanProjection(proj) ? (
          <EuropeanProjectionPanel proj={proj} t={t} />
        ) : (
          <LeagueProjectionPanel proj={proj} t={t} />
        ))}
    </div>
  );
}

/**
 * Fixture counts per league for the filter bar.
 *
 * Deliberately ignores the ACTIVE filters. Counting only what survives the
 * current selection would zero out every other chip the moment one is picked,
 * so the bar would stop answering the question it exists to answer — "is there
 * anything on in the Bundesliga tonight" — precisely when the reader is browsing.
 * Predictions are not requested; only the league field is used.
 */
async function getLeagueCounts(): Promise<LeagueCount[]> {
  try {
    const [club, national] = await Promise.all([
      getMatches(undefined, 200, 0, "upcoming", false, undefined, undefined, DAYS_AHEAD),
      getUpcomingNationalMatches(athensDate(0), athensDate(DAYS_AHEAD - 1), 200).catch(
        () => [] as { league: string }[],
      ),
    ]);
    const tally = new Map<string, number>();
    for (const m of [...club, ...national]) {
      if (!m.league) continue;
      tally.set(m.league, (tally.get(m.league) ?? 0) + 1);
    }
    return [...tally.entries()]
      .map(([code, count]) => ({ code, count }))
      .sort((a, b) => b.count - a.count || a.code.localeCompare(b.code));
  } catch {
    // The bar still renders, just without counts — a filter row is not worth
    // failing the whole page over.
    return [];
  }
}

export default async function HomePage({ searchParams }: PageProps) {
  const sp = await searchParams;
  // Resolve to the canonical code (case-insensitive). A league we don't cover
  // (e.g. ?league=Brasileirao) renders an honest "not supported" panel below
  // instead of a 400 from the API dressed up as a connectivity error.
  const league        = canonicalLeagueCode(sp.league);
  const unknownLeague = sp.league && !league ? sp.league : undefined;
  const minOdds       = sp.min_odds ? Number(sp.min_odds) : undefined;
  const minConfidence = sp.min_confidence || undefined;

  // Freemium: logged-out visitors get the Top-3 picks as a free teaser; the
  // rest of the fixtures render locked with a register CTA.
  const session = await getSession();
  const locked = !session;
  const t = await getServerT();
  const leagueCounts = await getLeagueCounts();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-2xl font-extrabold tracking-tight text-chalk">
          {t("home.title")}
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-chalk-2">
          {t("home.subtitle", { days: DAYS_AHEAD })}
        </p>
      </div>

      <Suspense>
        <FilterBar
          activeLeague={sp.league}
          activeOdds={minOdds}
          activeConfidence={minConfidence}
          counts={leagueCounts}
        />
      </Suspense>

      <div className="space-y-8">
        {unknownLeague ? (
          <div className="col-span-full py-16 text-center text-chalk-3">
            <p className="mb-3 text-4xl">🔍</p>
            <p className="font-medium text-chalk-2">
              {t("home.unknownLeague", { league: unknownLeague })}
            </p>
            <p className="mt-1 text-sm">{t("home.unknownLeagueHint")}</p>
          </div>
        ) : (
          <Suspense
            fallback={
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                {Array.from({ length: 8 }).map((_, i) => (
                  <div key={i} className="card p-4 h-36 animate-pulse bg-ink-700" />
                ))}
              </div>
            }
          >
            <UpcomingGrid league={league} minOdds={minOdds} minConfidence={minConfidence} showPicks={(!league && !minOdds && !minConfidence) || locked} locked={locked} />
          </Suspense>
        )}
      </div>

      {/* League table — only meaningful once a single league is selected, and
          never for the "International" pseudo-league (national teams have no
          table). Streams in separately so it can't delay the fixture grid. */}
      {league && league !== INTERNATIONAL_LEAGUE && (
        <Suspense fallback={<div className="card p-5 h-64 animate-pulse bg-ink-700" />}>
          <LeagueStandings league={league} />
        </Suspense>
      )}
    </div>
  );
}
