/**
 * 404.
 *
 * Next ships a bare "This page could not be found" with no styling and no way
 * out. On a public site that reads as broken rather than as a wrong address, so
 * this one keeps the reader oriented and points at the two pages that answer
 * most stray URLs: a fixture that has moved on, or a bookmark to an old match.
 */
import Link from "next/link";
import { getServerT } from "@/lib/i18n-server";

export default async function NotFound() {
  const t = await getServerT();
  return (
    <div className="mx-auto max-w-lg py-20 text-center">
      <p className="font-data text-5xl font-bold text-chalk-3">404</p>
      <h1 className="mt-4 font-display text-2xl font-extrabold text-chalk">
        {t("error.notFound.title")}
      </h1>
      <p className="mt-2 text-sm text-chalk-2">{t("error.notFound.body")}</p>
      <div className="mt-6 flex flex-wrap justify-center gap-2">
        <Link
          href="/"
          className="rounded-lg bg-chalk px-4 py-2 text-sm font-semibold text-ink-900 transition-opacity hover:opacity-90"
        >
          {t("error.toUpcoming")}
        </Link>
        <Link
          href="/recent"
          className="rounded-lg border border-line bg-ink-700 px-4 py-2 text-sm text-chalk-2 transition-colors hover:text-chalk"
        >
          {t("error.toRecent")}
        </Link>
      </div>
    </div>
  );
}
