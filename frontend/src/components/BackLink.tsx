"use client";
import { useRouter } from "next/navigation";

/**
 * Smart back link — returns to the page the user actually came from
 * (browser history), instead of a hardcoded destination. Falls back to a given
 * route when there's no in-app history (e.g. opened via a direct link).
 */
export default function BackLink({
  fallback = "/",
  label = "← Back",
}: {
  fallback?: string;
  label?: string;
}) {
  const router = useRouter();
  const onClick = () => {
    if (typeof window !== "undefined" && window.history.length > 1) router.back();
    else router.push(fallback);
  };
  return (
    <button
      onClick={onClick}
      className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-300 transition-colors"
    >
      {label}
    </button>
  );
}
