export const dynamic = "force-dynamic";

import {
  getNationalPredictions,
  NATIONAL_LIVE_SINCE,
  type NationalPrediction,
} from "@/lib/api";
import NationalMatchCard from "@/components/NationalMatchCard";
import Link from "next/link";

interface PageProps {
  searchParams: {
    tab?: string;
    tournament?: string;
    confidence?: string;
  };
}

// ── helpers ────────────────────────────────────────────────────────────────────

function buildTabUrl(
  tab: string,
  current: { tournament?: string; confidence?: string },
): string {
  const p = new URLSearchParams({ tab });
  if (current.tournament) p.set("tournament", current.tournament);
  if (current.confidence) p.set("confidence", current.confidence);
  return `/national?${p}`;
}

function buildFilterUrl(
  key: "tournament" | "confidence",
  value: string | undefined,
  current: { tab?: string; tournament?: string; confidence?: string },
): string {
  const p = new URLSearchParams();
  if (current.tab) p.set("tab", current.tab);
  if (key === "tournament") {
    if (value) p.set("tournament", value);
    if (current.confidence) p.set("confidence", current.confidence);
  } else {
    if (current.tournament) p.set("tournament", current.tournament);
    if (value) p.set("confidence", value);
  }
  return `/national?${p}`;
}

function groupByTournamentAndDate(
  predictions: NationalPrediction[],
): Map<string, Map<string, NationalPrediction[]>> {
  const byTournament = new Map<string, Map<string, NationalPrediction[]>>();
  for (const p of predictions) {
    if (!byTournament.has(p.tournament)) {
      byTournament.set(p.tournament, new Map());
    }
    const byDate = byTournament.get(p.tournament)!;
    if (!byDate.has(p.match_date)) {
      byDate.set(p.match_date, []);
    }
    byDate.get(p.match_date)!.push(p);
  }
  return byTournament;
}

// ── sub-components ─────────────────────────────────────────────────────────────

function TabBar({
  activeTab,
  searchParams,
}: {
  activeTab: string;
  searchParams: { tournament?: string; confidence?: string };
}) {
  return (
    <div className="flex gap-1 border-b border-pitch-700 pb-0">
      {(["upcoming", "results"] as const).map((tab) => {
        const label = tab === "upcoming" ? "Upcoming" : "Results";
        const isActive = activeTab === tab;
        return (
          <Link
            key={tab}
            href={buildTabUrl(tab, searchParams)}
            className={`px-4 py-2 text-sm font-medium rounded-t-lg border-b-2 transition-colors ${
              isActive
                ? "border-green-400 text-green-400 bg-pitch-800"
                : "border-transparent text-gray-400 hover:text-white hover:bg-pitch-800"
            }`}
          >
            {label}
          </Link>
        );
      })}
    </div>
  );
}

function FilterBar({
  activeTournament,
  activeConfidence,
  tab,
}: {
  activeTournament?: string;
  activeConfidence?: string;
  tab: string;
}) {
  const current = { tab, tournament: activeTournament, confidence: activeConfidence };
  const confidences = ["HIGH", "MEDIUM", "LOW"] as const;

  // Match the outer fixture filters (LeagueFilter / ConfidenceFilter).
  const base = "px-3 py-1.5 rounded-lg text-sm font-medium transition-colors whitespace-nowrap";
  const activeClass = "bg-violet-500 text-white";
  const inactiveClass = "bg-pitch-800 text-gray-400 hover:text-gray-200 hover:bg-pitch-700";

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="text-xs text-gray-500 mr-1">Confidence:</span>
      <Link
        href={buildFilterUrl("confidence", undefined, current)}
        className={`${base} ${!activeConfidence ? activeClass : inactiveClass}`}
      >
        All
      </Link>
      {confidences.map((c) => (
        <Link
          key={c}
          href={buildFilterUrl("confidence", c, current)}
          className={`${base} ${activeConfidence === c ? activeClass : inactiveClass}`}
        >
          {c}
        </Link>
      ))}
    </div>
  );
}

// ── page ───────────────────────────────────────────────────────────────────────

export default async function NationalPage({ searchParams }: PageProps) {
  const tab        = searchParams.tab === "results" ? "results" : "upcoming";
  const tournament = searchParams.tournament;
  const confidence = searchParams.confidence;

  // ── Upcoming tab ──────────────────────────────────────────────────────────
  if (tab === "upcoming") {
    const today = new Date().toISOString().slice(0, 10);

    let predictions: NationalPrediction[] = [];
    let fetchError = false;
    try {
      const result = await getNationalPredictions({
        from: today,
        tournament,
        confidence,
        limit: 500,
      });
      // Only include rows without actual_result (truly upcoming)
      predictions = result.predictions.filter((p) => p.actual_result === null);
    } catch {
      fetchError = true;
    }

    const grouped = groupByTournamentAndDate(predictions);
    const uniqueTournaments = grouped.size;

    return (
      <div className="space-y-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-white">
              International Predictions
            </h1>
            <p className="text-sm text-gray-500 mt-1">
              National team match predictions powered by the international model.
            </p>
          </div>
          <Link
            href="/national/world-cup"
            className="shrink-0 px-3 py-1.5 rounded-lg text-sm font-medium bg-pitch-800 text-gray-300 hover:text-white hover:bg-pitch-700 whitespace-nowrap mt-1"
          >
            🏆 World Cup Sim
          </Link>
        </div>

        <TabBar activeTab={tab} searchParams={{ tournament, confidence }} />

        <FilterBar
          activeTournament={tournament}
          activeConfidence={confidence}
          tab={tab}
        />

        {fetchError ? (
          <div className="text-center py-16 text-gray-500">
            <p className="text-4xl mb-3">⚠️</p>
            <p className="font-medium">Could not reach the API.</p>
            <p className="text-sm mt-1">Make sure the backend is running on port 8000.</p>
          </div>
        ) : predictions.length === 0 ? (
          <div className="text-center py-16 text-gray-500">
            <p className="text-4xl mb-3">📅</p>
            <p className="font-medium">No upcoming international fixtures found.</p>
          </div>
        ) : (
          <>
            <p className="text-sm text-gray-400">
              {predictions.length} upcoming fixture{predictions.length !== 1 ? "s" : ""} across{" "}
              {uniqueTournaments} tournament{uniqueTournaments !== 1 ? "s" : ""}
            </p>

            <div className="space-y-8">
              {Array.from(grouped.entries()).map(([tournamentName, byDate]) => (
                <div key={tournamentName} className="space-y-4">
                  <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider border-b border-pitch-700 pb-2">
                    🏆 {tournamentName}
                  </h2>
                  {Array.from(byDate.entries()).map(([dateStr, preds]) => (
                    <div key={dateStr} className="space-y-3">
                      <h3 className="text-xs text-gray-500 font-medium pl-1">
                        {new Date(`${dateStr}T12:00:00Z`).toLocaleDateString("en-GB", {
                          weekday: "short",
                          day: "numeric",
                          month: "short",
                          year: "numeric",
                        })}
                      </h3>
                      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                        {preds.map((pred) => (
                          <NationalMatchCard key={pred.id} prediction={pred} />
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    );
  }

  // ── Results tab ───────────────────────────────────────────────────────────
  let predictions: NationalPrediction[] = [];
  let fetchError = false;
  let stats: { total: number; correct: number } = { total: 0, correct: 0 };

  try {
    const result = await getNationalPredictions({
      tournament,
      confidence,
      // Live era only + newest-first, so the cap keeps RECENT results instead
      // of the ~2.4k backfilled 2024 replay rows (which would otherwise fill
      // the limit and show e.g. 2024 Baltic Cup as "our results").
      from: NATIONAL_LIVE_SINCE,
      order: "desc",
      limit: 500,
    });
    // Only rows with actual_result
    predictions = result.predictions.filter((p) => p.actual_result !== null);
    // Sort newest first (kickoff-aware within a day)
    predictions.sort((a, b) =>
      (b.kickoff_utc ?? b.match_date).localeCompare(a.kickoff_utc ?? a.match_date),
    );

    stats.total   = predictions.length;
    stats.correct = predictions.filter((p) => p.prediction === p.actual_result).length;
  } catch {
    fetchError = true;
  }

  const grouped = groupByTournamentAndDate(predictions);
  const accuracyPct =
    stats.total > 0 ? ((stats.correct / stats.total) * 100).toFixed(1) : null;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white">
          International Predictions
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          National team match predictions powered by the international model.
        </p>
      </div>

      <TabBar activeTab={tab} searchParams={{ tournament, confidence }} />

      <FilterBar
        activeTournament={tournament}
        activeConfidence={confidence}
        tab={tab}
      />

      {fetchError ? (
        <div className="text-center py-16 text-gray-500">
          <p className="text-4xl mb-3">⚠️</p>
          <p className="font-medium">Could not reach the API.</p>
        </div>
      ) : predictions.length === 0 ? (
        <div className="text-center py-16 text-gray-500">
          <p className="text-4xl mb-3">📊</p>
          <p className="font-medium">No results with actual outcomes yet.</p>
        </div>
      ) : (
        <>
          {/* Accuracy summary */}
          {accuracyPct && (
            <div className="rounded-xl border border-pitch-700 bg-pitch-900 p-4 inline-flex items-center gap-3">
              <span className="text-2xl font-bold text-white">{accuracyPct}%</span>
              <div className="text-sm text-gray-400">
                <span className="text-white font-medium">{stats.correct}</span>
                <span className="text-gray-500"> / </span>
                <span className="text-white font-medium">{stats.total}</span>
                <span className="ml-1">correct predictions</span>
              </div>
            </div>
          )}

          <div className="space-y-8">
            {Array.from(grouped.entries()).map(([tournamentName, byDate]) => (
              <div key={tournamentName} className="space-y-4">
                <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider border-b border-pitch-700 pb-2">
                  🏆 {tournamentName}
                </h2>
                {Array.from(byDate.entries()).map(([dateStr, preds]) => (
                  <div key={dateStr} className="space-y-3">
                    <h3 className="text-xs text-gray-500 font-medium pl-1">
                      {new Date(`${dateStr}T12:00:00Z`).toLocaleDateString("en-GB", {
                        weekday: "short",
                        day: "numeric",
                        month: "short",
                        year: "numeric",
                      })}
                    </h3>
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                      {preds.map((pred) => (
                        <NationalMatchCard key={pred.id} prediction={pred} />
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
