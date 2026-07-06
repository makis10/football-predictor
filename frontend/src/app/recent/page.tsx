// Always SSR — match results are scraped throughout the day.
export const dynamic = "force-dynamic";

import { Suspense } from "react";
import Link from "next/link";
import { getMatches, getPastNationalMatches, formatLongDate, INTERNATIONAL_LEAGUE, type Match } from "@/lib/api";
import { accuracySummary, gradeMatch, hasResult } from "@/lib/matchGrade";
import LeagueFilter from "@/components/LeagueFilter";
import RecentResultCard from "@/components/RecentResultCard";

const _shiftDays = (iso: string, n: number) =>
  new Date(new Date(`${iso}T00:00:00Z`).getTime() + n * 86_400_000).toISOString().slice(0, 10);

const DAYS_PER_PAGE = 7;

interface PageProps {
  searchParams: Promise<{ league?: string; page?: string }>;
}

function pageLabel(page: number): string {
  const daysOffset = (page - 1) * DAYS_PER_PAGE;
  if (daysOffset === 0) return `last ${DAYS_PER_PAGE} days`;
  const from = daysOffset + DAYS_PER_PAGE;
  const to = daysOffset + 1;
  return `${from}–${to} days ago`;
}

async function RecentGrid({ league, page }: { league?: string; page: number }) {
  const daysOffset = (page - 1) * DAYS_PER_PAGE;

  // Date range for national predictions (same window as club matches)
  const now = new Date();
  const toDate = new Date(now);
  toDate.setDate(now.getDate() - daysOffset);
  const fromDate = new Date(now);
  fromDate.setDate(now.getDate() - (daysOffset + DAYS_PER_PAGE));
  const toStr  = toDate.toISOString().slice(0, 10);
  const fromStr = fromDate.toISOString().slice(0, 10);

  // Case-insensitive — hand-typed URLs may use ?league=international.
  const isInternational = league?.toLowerCase() === INTERNATIONAL_LEAGUE.toLowerCase();

  let matches: Match[] = [];
  try {
    // Club matches — skip when "International" filter active
    if (!isInternational) {
      matches = await getMatches(
        league,
        200,
        0,
        "past",
        true,
        DAYS_PER_PAGE,
        daysOffset,
      );
    }

    // National matches — include when All Leagues or International filter.
    // National match_date is remapped to the ATHENS calendar day in
    // nationalToMatch (a late kickoff lands on the next day locally), while the
    // fetch filters the DB source date. Fetch a ±1-day buffer, then keep only
    // those whose Athens date falls in this page's window — so a boundary match
    // shows on the right page (and isn't dropped/duplicated).
    if (!league || isInternational) {
      const nationals = (
        await getPastNationalMatches(_shiftDays(fromStr, -1), _shiftDays(toStr, 1), 200)
      ).filter((m) => m.match_date >= fromStr && m.match_date <= toStr);
      matches = isInternational
        ? nationals
        : [...matches, ...nationals].sort(
            (a, b) => b.match_date.localeCompare(a.match_date),
          );
    }
  } catch {
    return (
      <div className="text-center py-16 text-gray-500">
        <p className="text-4xl mb-3">⚠️</p>
        <p className="font-medium">Could not reach the API.</p>
      </div>
    );
  }

  if (matches.length === 0) {
    return (
      <div className="text-center py-16 text-gray-500">
        <p className="text-4xl mb-3">📅</p>
        <p className="font-medium">No matches found for this period.</p>
      </div>
    );
  }

  // Group by date (most recent first — already ordered by backend)
  const byDate = matches.reduce<Record<string, Match[]>>((acc, m) => {
    acc[m.match_date] = acc[m.match_date] ?? [];
    acc[m.match_date].push(m);
    return acc;
  }, {});

  // Accuracy for the matches on THIS page — graded by the shared rule that
  // mirrors the backend /stats definition (see lib/matchGrade.ts).
  const acc = accuracySummary(matches);
  const accuracy = acc.bothPct;
  const resultAccuracy = acc.resultPct;
  const goalsAccuracy = acc.goalsPct;
  const noPred = matches.length - acc.total;

  return (
    <div className="space-y-8">
      {/* Accuracy summary */}
      {accuracy !== null && (
        <div className="p-4 rounded-xl bg-pitch-800 border border-pitch-700 space-y-3">
          {/* Top row: overall % + correct/partial/wrong counts */}
          <div className="flex items-center gap-6 flex-wrap">
            <div className="text-center min-w-[56px]">
              <p className="text-3xl font-black text-white">{accuracy}%</p>
              <p className="text-xs text-gray-400 mt-0.5">Both correct</p>
            </div>
            <div className="h-10 w-px bg-pitch-600 hidden sm:block" />
            <div className="flex gap-4 text-sm flex-wrap">
              <span className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-green-500 inline-block" />
                <span className="text-green-400 font-bold">{acc.correct}</span>
                <span className="text-gray-500">correct</span>
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-amber-500 inline-block" />
                <span className="text-amber-400 font-bold">{acc.partial}</span>
                <span className="text-gray-500">partial</span>
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-red-500 inline-block" />
                <span className="text-red-400 font-bold">{acc.wrong}</span>
                <span className="text-gray-500">wrong</span>
              </span>
              {noPred > 0 && (
                <span className="text-gray-600 text-xs self-center">
                  {noPred} without prediction
                </span>
              )}
            </div>
          </div>

          {/* Bottom row: split by prediction type */}
          {(resultAccuracy !== null || goalsAccuracy !== null) && (
            <div className="flex items-center gap-3 pt-1 border-t border-pitch-700 flex-wrap">
              <span className="text-xs text-gray-500 mr-1">Breakdown:</span>
              {resultAccuracy !== null && (
                <span className="flex items-center gap-2 bg-pitch-700 rounded-lg px-3 py-1.5">
                  <span className="text-xs text-gray-400">Result (1×2)</span>
                  <span className={`text-sm font-bold ${
                    resultAccuracy >= 50 ? "text-green-400" :
                    resultAccuracy >= 40 ? "text-amber-400" : "text-red-400"
                  }`}>
                    {resultAccuracy}%
                  </span>
                  <span className="text-xs text-gray-600">
                    {acc.resultCorrect}/{acc.total}
                  </span>
                </span>
              )}
              {goalsAccuracy !== null && (
                <span className="flex items-center gap-2 bg-pitch-700 rounded-lg px-3 py-1.5">
                  <span className="text-xs text-gray-400">Goals (O/U)</span>
                  <span className={`text-sm font-bold ${
                    goalsAccuracy >= 55 ? "text-green-400" :
                    goalsAccuracy >= 45 ? "text-amber-400" : "text-red-400"
                  }`}>
                    {goalsAccuracy}%
                  </span>
                  <span className="text-xs text-gray-600">
                    {acc.goalsCorrect}/{acc.total}
                  </span>
                </span>
              )}
            </div>
          )}
        </div>
      )}

      {/* Matches grouped by day */}
      {Object.entries(byDate).map(([dateStr, dayMatches]) => {
        const dayWithPred = dayMatches.filter(hasResult);
        const dayCorrect  = dayWithPred.filter((m) => gradeMatch(m) === "correct");
        const dayPartial  = dayWithPred.filter((m) => gradeMatch(m) === "partial");

        return (
          <div key={dateStr} className="space-y-3">
            {/* Date header */}
            <div className="flex items-center justify-between border-b border-pitch-700 pb-2">
              <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
                {formatLongDate(dateStr)}
              </h2>
              {dayWithPred.length > 0 && (
                <span className="text-xs text-gray-500">
                  {dayCorrect.length}/{dayWithPred.length} correct
                  {dayPartial.length > 0 && (
                    <span className="text-amber-600 ml-1">· {dayPartial.length} partial</span>
                  )}
                </span>
              )}
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
              {dayMatches.map((match) => (
                <RecentResultCard key={match.id} match={match} />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default async function RecentResultsPage({ searchParams }: PageProps) {
  const sp = await searchParams;
  const league = sp.league;
  const page = Math.max(1, Number(sp.page ?? "1"));

  const buildHref = (p: number) => {
    const params = new URLSearchParams();
    if (league) params.set("league", league);
    if (p > 1) params.set("page", String(p));
    const qs = params.toString();
    return `/recent${qs ? `?${qs}` : ""}`;
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white">
          Recent Results
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          Predictions vs. actual results.{" "}
          <span className="text-green-500">Green</span> = both correct,{" "}
          <span className="text-amber-500">amber</span> = one of two correct,{" "}
          <span className="text-red-500">red</span> = both wrong.
        </p>
      </div>

      <Suspense>
        <LeagueFilter active={league} basePath="/recent" />
      </Suspense>

      <Suspense
        fallback={
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="rounded-xl h-36 animate-pulse bg-pitch-800" />
            ))}
          </div>
        }
      >
        <RecentGrid league={league} page={page} />
      </Suspense>

      {/* Pagination */}
      <div className="flex items-center justify-center gap-3 pt-4">
        {page > 1 && (
          <Link
            href={buildHref(page - 1)}
            className="px-4 py-2 text-sm rounded-lg bg-pitch-800 text-gray-300 hover:bg-pitch-700 transition-colors"
          >
            ← Newer
          </Link>
        )}
        <span className="text-xs text-gray-600 px-2">{pageLabel(page)}</span>
        <Link
          href={buildHref(page + 1)}
          className="px-4 py-2 text-sm rounded-lg bg-pitch-800 text-gray-300 hover:bg-pitch-700 transition-colors"
        >
          Older →
        </Link>
      </div>
    </div>
  );
}
