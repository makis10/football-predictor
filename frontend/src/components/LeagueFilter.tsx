"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { INTERNATIONAL_LEAGUE, LEAGUES } from "@/lib/api";

export default function LeagueFilter({
  active,
  basePath = "/",
}: {
  active?: string;
  basePath?: string;
}) {
  const router = useRouter();
  const params = useSearchParams();

  function select(code?: string) {
    const next = new URLSearchParams(params.toString());
    next.delete("page"); // reset pagination on filter change
    if (code) {
      next.set("league", code);
    } else {
      next.delete("league");
    }
    router.push(`${basePath}?${next}`);
  }

  const base =
    "px-3 py-1.5 rounded-lg text-sm font-medium transition-colors whitespace-nowrap";
  const activeClass = "bg-green-500 text-black";
  const inactiveClass = "bg-pitch-800 text-gray-400 hover:text-gray-200 hover:bg-pitch-700";

  return (
    <div className="flex flex-wrap gap-2">
      <button
        onClick={() => select(undefined)}
        className={`${base} ${!active ? activeClass : inactiveClass}`}
      >
        All Leagues
      </button>
      {LEAGUES.map((l) => (
        <button
          key={l.code}
          onClick={() => select(l.code)}
          className={`${base} ${active === l.code ? activeClass : inactiveClass}`}
        >
          {l.flag} {l.label}
        </button>
      ))}
      <button
        onClick={() => select(INTERNATIONAL_LEAGUE)}
        className={`${base} ${active === INTERNATIONAL_LEAGUE ? activeClass : inactiveClass}`}
      >
        🌍 International
      </button>
    </div>
  );
}
