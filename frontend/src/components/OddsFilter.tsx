"use client";

import { useRouter, useSearchParams } from "next/navigation";

const ODDS_OPTIONS = [
  { label: "Any odds", value: null },
  { label: "1.50+", value: 1.5 },
  { label: "1.70+", value: 1.7 },
  { label: "1.90+", value: 1.9 },
  { label: "2.20+", value: 2.2 },
  { label: "2.50+", value: 2.5 },
];

export default function OddsFilter({
  active,
  basePath = "/",
}: {
  active?: number;
  basePath?: string;
}) {
  const router = useRouter();
  const params = useSearchParams();

  function select(value: number | null) {
    const next = new URLSearchParams(params.toString());
    next.delete("page");
    if (value != null) {
      next.set("min_odds", String(value));
    } else {
      next.delete("min_odds");
    }
    router.push(`${basePath}?${next}`);
  }

  const base =
    "px-3 py-1.5 rounded-lg text-sm font-medium transition-colors whitespace-nowrap";
  const activeClass = "bg-emerald-500 text-black";
  const inactiveClass = "bg-pitch-800 text-gray-400 hover:text-gray-200 hover:bg-pitch-700";

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="text-xs text-gray-500 mr-1">Min odds:</span>
      {ODDS_OPTIONS.map((opt) => (
        <button
          key={opt.value ?? "any"}
          onClick={() => select(opt.value)}
          className={`${base} ${active === opt.value ? activeClass : inactiveClass}`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
