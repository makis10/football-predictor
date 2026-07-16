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
  getWcReview,
  athensDate,
  canonicalLeagueCode,
  formatLongDate,
  INTERNATIONAL_LEAGUE,
  type WcReview,
} from "@/lib/api";
import MatchCard from "@/components/MatchCard";
import LockedMatchCard from "@/components/LockedMatchCard";
import StandingsTable from "@/components/StandingsTable";
import LeagueProjectionPanel from "@/components/LeagueProjectionPanel";
import EuropeanProjectionPanel from "@/components/EuropeanProjectionPanel";
import { getSession } from "@/lib/auth";
import LeagueFilter from "@/components/LeagueFilter";
import OddsFilter from "@/components/OddsFilter";
import ConfidenceFilter from "@/components/ConfidenceFilter";
import TopPicks from "@/components/TopPicks";

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
      <div className="col-span-full text-center py-16 text-gray-500">
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
      <div className="col-span-full text-center py-16 text-gray-500">
        <p className="text-4xl mb-3">📅</p>
        <p className="font-medium">No upcoming fixtures found.</p>
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
      {showPicks && <TopPicks matches={matches} />}

      {Object.entries(byDate).map(([dateStr, dayMatches]) => (
        <div key={dateStr} className="col-span-full space-y-4">
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider border-b border-pitch-700 pb-2">
            {formatLongDate(dateStr, "en-GB")}
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {dayMatches.map((match) =>
              locked ? (
                <LockedMatchCard key={`${match.league}-${match.id}`} match={match} />
              ) : (
                <MatchCard key={`${match.league}-${match.id}`} match={match} />
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
      {table && <StandingsTable table={table} />}
      {/* A domestic season projects to a table position, a UEFA one to a trophy
          — different questions, so different panels. */}
      {proj &&
        (isEuropeanProjection(proj) ? (
          <EuropeanProjectionPanel proj={proj} />
        ) : (
          <LeagueProjectionPanel proj={proj} />
        ))}
    </div>
  );
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

  // Best-effort WC retrospective hero — keeps the app compelling between the
  // World Cup final and the club season restart, when fixtures are sparse.
  let wcReview: WcReview = { available: false };
  try {
    wcReview = await getWcReview();
  } catch {
    /* non-fatal */
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white">
          Upcoming Fixtures
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          Model predictions for the next {DAYS_AHEAD} days across every major league,
          European cup, friendly &amp; international.
        </p>
      </div>

      {wcReview.available && wcReview.settled ? (
        <Link
          href="/national/world-cup/review"
          className="flex items-center justify-between gap-3 rounded-xl border border-amber-700/40 bg-amber-950/20 px-4 py-3 hover:bg-amber-950/30 transition-colors"
        >
          <span className="text-sm text-gray-300">
            🏆 <span className="font-semibold text-amber-300">World Cup 2026 review</span> — το μοντέλο πέτυχε{" "}
            <span className="font-semibold text-emerald-400">{Math.round((wcReview.result_accuracy ?? 0) * 100)}%</span>{" "}
            των αποτελεσμάτων σε {wcReview.settled} αγώνες
          </span>
          <span className="text-xs text-amber-400 whitespace-nowrap">Δες →</span>
        </Link>
      ) : null}

      <Suspense>
        <LeagueFilter active={sp.league} />
      </Suspense>

      <div className="flex flex-wrap gap-x-6 gap-y-2">
        <Suspense>
          <OddsFilter active={minOdds} />
        </Suspense>
        <Suspense>
          <ConfidenceFilter active={minConfidence} />
        </Suspense>
      </div>

      <div className="space-y-8">
        {unknownLeague ? (
          <div className="col-span-full text-center py-16 text-gray-500">
            <p className="text-4xl mb-3">🔍</p>
            <p className="font-medium">
              League &ldquo;{unknownLeague}&rdquo; isn&apos;t covered (yet).
            </p>
            <p className="text-sm mt-1">Pick one of the leagues above.</p>
          </div>
        ) : (
          <Suspense
            fallback={
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                {Array.from({ length: 8 }).map((_, i) => (
                  <div key={i} className="card p-4 h-36 animate-pulse bg-pitch-800" />
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
        <Suspense fallback={<div className="card p-5 h-64 animate-pulse bg-pitch-800" />}>
          <LeagueStandings league={league} />
        </Suspense>
      )}
    </div>
  );
}
