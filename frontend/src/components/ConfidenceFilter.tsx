"use client";

import { useRouter, useSearchParams } from "next/navigation";

const OPTIONS = [
  { label: "Any confidence", value: null },
  { label: "High only", value: "high" },
  { label: "Medium+", value: "medium" },
];

export default function ConfidenceFilter({
  active,
  basePath = "/",
}: {
  active?: string;
  basePath?: string;
}) {
  const router = useRouter();
  const params = useSearchParams();

  function select(value: string | null) {
    const next = new URLSearchParams(params.toString());
    next.delete("page");
    if (value != null) {
      next.set("min_confidence", value);
    } else {
      next.delete("min_confidence");
    }
    router.push(`${basePath}?${next}`);
  }

  const base = "px-3 py-1.5 rounded-lg text-sm font-medium transition-colors whitespace-nowrap";
  const activeClass = "bg-violet-500 text-white";
  const inactiveClass = "bg-pitch-800 text-gray-400 hover:text-gray-200 hover:bg-pitch-700";

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="text-xs text-gray-500 mr-1">Confidence:</span>
      {OPTIONS.map((opt) => (
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
