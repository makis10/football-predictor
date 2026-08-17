"use client";

/**
 * Route-level error boundary.
 *
 * Without one, any throw in a server component renders Next's unstyled
 * "Application error: a server-side exception has occurred" with a digest and
 * nothing else — no navigation, no retry, and on a public site it looks like
 * the whole thing fell over. Most failures here are one flaky upstream call
 * (the API, the odds feed, Groq), so `reset()` genuinely fixes it.
 *
 * The digest is shown deliberately: it is the only handle that ties what the
 * reader saw to a line in the server log.
 */
import { useEffect } from "react";
import Link from "next/link";
import { useT } from "@/components/LanguageProvider";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const t = useT();

  useEffect(() => {
    // Reaches the browser console and any error tracking that is wired up.
    console.error("route error", error);
  }, [error]);

  return (
    <div className="mx-auto max-w-lg py-20 text-center">
      <p className="text-4xl">⚠️</p>
      <h1 className="mt-4 font-display text-2xl font-extrabold text-chalk">
        {t("error.generic.title")}
      </h1>
      <p className="mt-2 text-sm text-chalk-2">{t("error.generic.body")}</p>
      <div className="mt-6 flex flex-wrap justify-center gap-2">
        <button
          type="button"
          onClick={reset}
          className="rounded-lg bg-chalk px-4 py-2 text-sm font-semibold text-ink-900 transition-opacity hover:opacity-90"
        >
          {t("error.retry")}
        </button>
        <Link
          href="/"
          className="rounded-lg border border-line bg-ink-700 px-4 py-2 text-sm text-chalk-2 transition-colors hover:text-chalk"
        >
          {t("error.toUpcoming")}
        </Link>
      </div>
      {error.digest && (
        <p className="mt-6 font-data text-[11px] text-chalk-3">
          {t("error.reference")}: {error.digest}
        </p>
      )}
    </div>
  );
}
