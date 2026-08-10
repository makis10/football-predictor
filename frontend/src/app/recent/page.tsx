// Always SSR — match results are scraped throughout the day.
export const dynamic = "force-dynamic";

import { Suspense } from "react";
import Link from "next/link";
import { getMatches, getPastNationalMatches, formatLongDate, athensDate, canonicalLeagueCode, INTERNATIONAL_LEAGUE, type Match } from "@/lib/api";
import { accuracySummary, gradeMatch, hasResult } from "@/lib/matchGrade";
import FilterBar from "@/components/FilterBar";
import RecentResultCard from "@/components/RecentResultCard";
import { getServerT } from "@/lib/i18n-server";

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

  // Date range for national predictions (same window as club matches).
  // Anchored to Athens time — matches how national match_date is bucketed
  // below — so the UTC 22:00-24:00 window (01:00-03:00 Athens) doesn't
  // shift a match onto the wrong page.
  const toStr   = athensDate(-daysOffset);
  const fromStr = athensDate(-(daysOffset + DAYS_PER_PAGE));

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
      <div className="text-center py-16 text-chalk-3">
        <p className="text-4xl mb-3">⚠️</p>
        <p className="font-medium">Could not reach the API.</p>
      </div>
    );
  }

  if (matches.length === 0) {
    return (
      <div className="text-center py-16 text-chalk-3">
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
        <div className="p-4 rounded-xl bg-ink-700 border border-line space-y-3">
          {/* Top row: overall % + correct/partial/wrong counts */}
          <div className="flex items-center gap-6 flex-wrap">
            <div className="text-center min-w-[56px]">
              <p className="text-3xl font-black text-chalk">{accuracy}%</p>
              <p className="text-xs text-chalk-2 mt-0.5">Both correct</p>
            </div>
            <div className="h-10 w-px bg-ink-600 hidden sm:block" />
            <div className="flex gap-4 text-sm flex-wrap">
              <span className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-win inline-block" />
                <span className="text-win font-bold">{acc.correct}</span>
                <span className="text-chalk-3">correct</span>
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-est inline-block" />
                <span className="text-est font-bold">{acc.partial}</span>
                <span className="text-chalk-3">partial</span>
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-lose inline-block" />
                <span className="text-lose font-bold">{acc.wrong}</span>
                <span className="text-chalk-3">wrong</span>
              </span>
              {noPred > 0 && (
                <span className="text-chalk-3 text-xs self-center">
                  {noPred} without prediction
                </span>
              )}
            </div>
          </div>

          {/* Bottom row: split by prediction type */}
          {(resultAccuracy !== null || goalsAccuracy !== null) && (
            <div className="flex items-center gap-3 pt-1 border-t border-line flex-wrap">
              <span className="text-xs text-chalk-3 mr-1">Breakdown:</span>
              {resultAccuracy !== null && (
                <span className="flex items-center gap-2 bg-ink-600 rounded-lg px-3 py-1.5">
                  <span className="text-xs text-chalk-2">Result (1×2)</span>
                  <span className={`text-sm font-bold ${
                    resultAccuracy >= 50 ? "text-win" :
                    resultAccuracy >= 40 ? "text-est" : "text-lose"
                  }`}>
                    {resultAccuracy}%
                  </span>
                  <span className="text-xs text-chalk-3">
                    {acc.resultCorrect}/{acc.total}
                  </span>
                </span>
              )}
              {goalsAccuracy !== null && (
                <span className="flex items-center gap-2 bg-ink-600 rounded-lg px-3 py-1.5">
                  <span className="text-xs text-chalk-2">Goals (O/U)</span>
                  <span className={`text-sm font-bold ${
                    goalsAccuracy >= 55 ? "text-win" :
                    goalsAccuracy >= 45 ? "text-est" : "text-lose"
                  }`}>
                    {goalsAccuracy}%
                  </span>
                  <span className="text-xs text-chalk-3">
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
            <div className="flex items-center justify-between border-b border-line pb-2">
              <h2 className="text-sm font-semibold text-chalk-2 uppercase tracking-wider">
                {formatLongDate(dateStr)}
              </h2>
              {dayWithPred.length > 0 && (
                <span className="text-xs text-chalk-3">
                  {dayCorrect.length}/{dayWithPred.length} correct
                  {dayPartial.length > 0 && (
                    <span className="text-est ml-1">· {dayPartial.length} partial</span>
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
  const t = await getServerT();
  // Resolve to the canonical code (case-insensitive); a league we don't cover
  // renders an honest "not supported" panel instead of the API's 400 being
  // swallowed and misreported as a connectivity error.
  const league = canonicalLeagueCode(sp.league);
  const unknownLeague = sp.league && !league ? sp.league : undefined;
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
        <h1 className="font-display text-2xl font-extrabold tracking-tight text-chalk">
          {t("recent.title")}
        </h1>
        <p className="mt-1 text-sm text-chalk-2">
          {t("recent.subtitle")}{" "}
          <span className="text-win">{t("recent.legendBoth")}</span>{" "}
          <span className="text-est">{t("recent.legendOne")}</span>{" "}
          <span className="text-lose">{t("recent.legendNone")}</span>
        </p>
      </div>

      <Suspense>
        <FilterBar
            activeLeague={sp.league}
            counts={[]}
            showRefine={false}
            basePath="/recent"
          />
      </Suspense>

      {unknownLeague ? (
        <div className="text-center py-16 text-chalk-3">
          <p className="text-4xl mb-3">🔍</p>
          <p className="font-medium">
            League &ldquo;{unknownLeague}&rdquo; isn&apos;t covered (yet).
          </p>
          <p className="text-sm mt-1">Pick one of the leagues above.</p>
        </div>
      ) : (
        <Suspense
          fallback={
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
              {Array.from({ length: 8 }).map((_, i) => (
                <div key={i} className="rounded-xl h-36 animate-pulse bg-ink-700" />
              ))}
            </div>
          }
        >
          <RecentGrid league={league} page={page} />
        </Suspense>
      )}

      {/* Pagination */}
      <div className="flex items-center justify-center gap-3 pt-4">
        {page > 1 && (
          <Link
            href={buildHref(page - 1)}
            className="px-4 py-2 text-sm rounded-lg bg-ink-700 text-chalk-2 hover:bg-ink-600 transition-colors"
          >
            ← Newer
          </Link>
        )}
        <span className="text-xs text-chalk-3 px-2">{pageLabel(page)}</span>
        <Link
          href={buildHref(page + 1)}
          className="px-4 py-2 text-sm rounded-lg bg-ink-700 text-chalk-2 hover:bg-ink-600 transition-colors"
        >
          Older →
        </Link>
      </div>
    </div>
  );
}
