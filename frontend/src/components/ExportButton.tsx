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

  const btn = "px-3 py-1.5 rounded-lg text-sm font-medium transition-colors whitespace-nowrap bg-pitch-800 text-gray-400 hover:text-gray-200 hover:bg-pitch-700";

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-gray-500 mr-1">Export:</span>
      <button onClick={() => download("csv")} className={btn}>
        ↓ CSV
      </button>
      <button onClick={() => download("json")} className={btn}>
        ↓ JSON
      </button>
    </div>
  );
}
