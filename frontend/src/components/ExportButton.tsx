"use client";

import { buildExportUrl } from "@/lib/api";

export default function ExportButton({
  league,
  minOdds,
  minConfidence,
  daysAhead,
}: {
  league?: string;
  minOdds?: number;
  minConfidence?: string;
  daysAhead?: number;
}) {
  function download(format: "csv" | "json") {
    const url = buildExportUrl({ format, league, minOdds, minConfidence, daysAhead, status: "upcoming" });
    window.open(url, "_blank");
  }

  const btn = "px-3 py-1.5 rounded-lg text-sm font-medium transition-colors whitespace-nowrap bg-ink-700 text-chalk-2 hover:text-chalk hover:bg-ink-600";

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-chalk-3 mr-1">Export:</span>
      <button onClick={() => download("csv")} className={btn}>
        ↓ CSV
      </button>
      <button onClick={() => download("json")} className={btn}>
        ↓ JSON
      </button>
    </div>
  );
}
