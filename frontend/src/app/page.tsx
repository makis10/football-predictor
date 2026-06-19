// Always SSR — predictions and kickoff times change throughout the day.
export const dynamic = "force-dynamic";

import { Suspense } from "react";
import {
  getMatches,
  getUpcomingNationalMatches,
  athensDate,
  formatLongDate,
  INTERNATIONAL_LEAGUE,
} from "@/lib/api";
import MatchCard from "@/components/MatchCard";
import LeagueFilter from "@/components/LeagueFilter";
import OddsFilter from "@/components/OddsFilter";
import ConfidenceFilter from "@/components/ConfidenceFilter";
import ExportButton from "@/components/ExportButton";
import TopPicks from "@/components/TopPicks";

interface PageProps {
  searchParams: { league?: string; min_odds?: string; min_confidence?: string };
}

const DAYS_AHEAD = 3; // today + 2 more days

async function UpcomingGrid({
  league,
  minOdds,
  minConfidence,
  showPicks = true,
}: {
  league?: string;
  minOdds?: number;
  minConfidence?: string;
  showPicks?: boolean;
}) {
  const isInternational = league === INTERNATIONAL_LEAGUE;

  let matches = [];
  try {
    if (isInternational) {
      // "International" filter — show upcoming national fixtures only
      matches = await getUpcomingNationalMatches(athensDate(0), athensDate(DAYS_AHEAD - 1));
      const minConf = minConfidence?.toLowerCase();
      const confRank: Record<string, number> = { low: 1, medium: 2, high: 3 };
      if (minConf) {
        matches = matches.filter(
          (m) => (confRank[m.prediction?.confidence ?? "low"] ?? 0) >= (confRank[minConf] ?? 0),
        );
      }
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
  // National fixtures carry no bookmaker odds, so they can't satisfy a min-odds
  // filter — only merge them when no odds threshold is set.
  if (!league && minOdds == null) {
    try {
      const nat = await getUpcomingNationalMatches(athensDate(0), athensDate(DAYS_AHEAD - 1));
      // Honour the same confidence filter the club list uses.
      const minConf = minConfidence?.toLowerCase();
      const confRank: Record<string, number> = { low: 1, medium: 2, high: 3 };
      const filtered = minConf
        ? nat.filter((m) => (confRank[m.prediction?.confidence ?? "low"] ?? 0) >= (confRank[minConf] ?? 0))
        : nat;
      matches = [...matches, ...filtered].sort((a, b) =>
        a.match_date !== b.match_date
          ? a.match_date.localeCompare(b.match_date)
          : (a.kickoff_time ?? "99").localeCompare(b.kickoff_time ?? "99"),
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
            {dayMatches.map((match) => (
              <MatchCard key={`${match.league}-${match.id}`} match={match} />
            ))}
          </div>
        </div>
      ))}
    </>
  );
}

export default function HomePage({ searchParams }: PageProps) {
  const league        = searchParams.league;
  const minOdds       = searchParams.min_odds ? Number(searchParams.min_odds) : undefined;
  const minConfidence = searchParams.min_confidence || undefined;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white">
          Upcoming Fixtures
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          Model predictions for the next {DAYS_AHEAD} days across 13 leagues.
        </p>
      </div>

      <Suspense>
        <LeagueFilter active={league} />
      </Suspense>

      <div className="flex flex-wrap gap-x-6 gap-y-2">
        <Suspense>
          <OddsFilter active={minOdds} />
        </Suspense>
        <Suspense>
          <ConfidenceFilter active={minConfidence} />
        </Suspense>
        <ExportButton
          league={league}
          minOdds={minOdds}
          minConfidence={minConfidence}
          daysAhead={DAYS_AHEAD}
        />
      </div>

      <div className="space-y-8">
        <Suspense
          fallback={
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {Array.from({ length: 8 }).map((_, i) => (
                <div key={i} className="card p-4 h-36 animate-pulse bg-pitch-800" />
              ))}
            </div>
          }
        >
          <UpcomingGrid league={league} minOdds={minOdds} minConfidence={minConfidence} showPicks={!league && !minOdds && !minConfidence} />
        </Suspense>
      </div>
    </div>
  );
}
