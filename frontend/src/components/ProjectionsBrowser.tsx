"use client";

import { useMemo, useState } from "react";
import {
  type Standings,
  type SeasonProjection,
  type ProjectionHistorySnapshot,
  isEuropeanProjection,
  leagueFlag,
  leagueLabel,
} from "@/lib/api";
import StandingsTable from "@/components/StandingsTable";
import LeagueProjectionPanel from "@/components/LeagueProjectionPanel";
import EuropeanProjectionPanel from "@/components/EuropeanProjectionPanel";
import ProjectionHistoryChart from "@/components/ProjectionHistoryChart";

export interface CompetitionProjection {
  league: string;
  category: "domestic" | "european";
  table: Standings | null;
  projection: SeasonProjection | null;
  history: ProjectionHistorySnapshot[];
}

type Filter = "all" | "domestic" | "european";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all",      label: "Όλα" },
  { key: "domestic", label: "Πρωταθλήματα" },
  { key: "european", label: "Ευρώπη" },
];

/**
 * Long-term projections browser: a category filter + a competition picker, then
 * the selected competition's table and season/trophy projection. All data is
 * fetched server-side (and cached), so switching competition is instant.
 */
export default function ProjectionsBrowser({ items }: { items: CompetitionProjection[] }) {
  const [filter, setFilter] = useState<Filter>("all");

  const visible = useMemo(
    () => (filter === "all" ? items : items.filter((i) => i.category === filter)),
    [filter, items],
  );

  const [selected, setSelected] = useState<string>(items[0]?.league ?? "");
  // Keep the selection valid when the filter hides the current competition.
  const current =
    visible.find((i) => i.league === selected) ?? visible[0] ?? null;

  if (items.length === 0) {
    return (
      <div className="card p-8 text-center text-gray-500">
        <p className="text-4xl mb-3">🔮</p>
        <p className="font-medium">Δεν υπάρχουν διαθέσιμες προγνώσεις αυτή τη στιγμή.</p>
        <p className="text-sm mt-1">
          Οι μακροχρόνιες προγνώσεις ανάβουν μόλις ξεκινήσει η σεζόν κάθε διοργάνωσης.
        </p>
      </div>
    );
  }

  const counts = {
    all: items.length,
    domestic: items.filter((i) => i.category === "domestic").length,
    european: items.filter((i) => i.category === "european").length,
  };

  return (
    <div className="space-y-5">
      {/* Category filter */}
      <div className="flex flex-wrap gap-2">
        {FILTERS.filter((f) => counts[f.key] > 0).map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`px-3 py-1.5 rounded-full text-sm transition-colors ${
              filter === f.key
                ? "bg-green-600 text-white"
                : "bg-pitch-800 text-gray-400 hover:text-gray-200"
            }`}
          >
            {f.label}
            <span className="ml-1.5 text-xs opacity-70">{counts[f.key]}</span>
          </button>
        ))}
      </div>

      {/* Competition picker */}
      <div className="flex flex-wrap gap-2">
        {visible.map((i) => (
          <button
            key={i.league}
            onClick={() => setSelected(i.league)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors ${
              current?.league === i.league
                ? "bg-pitch-700 text-white ring-1 ring-green-500/40"
                : "bg-pitch-900 text-gray-400 hover:text-gray-200 border border-pitch-700"
            }`}
          >
            <span>{leagueFlag(i.league)}</span>
            {leagueLabel(i.league)}
          </button>
        ))}
      </div>

      {/* Selected competition */}
      {current && (
        <div className="space-y-6">
          {current.projection &&
            (isEuropeanProjection(current.projection) ? (
              <EuropeanProjectionPanel proj={current.projection} />
            ) : (
              <LeagueProjectionPanel proj={current.projection} />
            ))}
          {current.history.length >= 2 && (
            <ProjectionHistoryChart snapshots={current.history} />
          )}
          {current.table && <StandingsTable table={current.table} />}
          {!current.projection && !current.table && current.category === "european" && (
            <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-6 text-center space-y-2">
              <p className="text-2xl">🏆</p>
              <p className="text-sm font-semibold text-gray-200">
                Διαθέσιμο μετά την κλήρωση της league phase
              </p>
              <p className="text-xs text-gray-500 leading-relaxed max-w-md mx-auto">
                Οι 36 συμμετέχοντες της διοργάνωσης κρίνονται στα προκριματικά που
                παίζονται τώρα — μια «πιθανότητα κατάκτησης» πριν οριστικοποιηθεί το
                πεδίο θα ήταν εφεύρεση, όχι εκτίμηση. Η πρόβλεψη ανάβει αυτόματα μόλις
                μπουν οι αγώνες της league phase (τέλη Αυγούστου).
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
