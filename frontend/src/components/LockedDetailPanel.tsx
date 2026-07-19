/**
 * Locked match-detail panel — freemium gate for logged-out visitors.
 *
 * Rendered server-side INSTEAD of the prediction/analysis sections for
 * upcoming matches, so none of the premium numbers ever reach the HTML.
 * Finished matches stay public (they're the transparency/accuracy proof).
 */
import Link from "next/link";
import type { TFunc } from "@/lib/i18n";

export default function LockedDetailPanel({
  home,
  away,
  t,
}: {
  home: string;
  away: string;
  t: TFunc;
}) {
  return (
    <div className="card p-8 text-center space-y-4">
      <p className="text-4xl">🔒</p>
      <div>
        <p className="text-lg font-semibold text-gray-100">
          {t("locked.detail.title", { home, away })}
        </p>
        <p className="text-sm text-gray-400 mt-2 max-w-md mx-auto">
          {t("locked.detail.body")}
        </p>
      </div>
      <div className="flex items-center justify-center gap-3">
        <Link
          href="/register"
          className="px-5 py-2.5 rounded-lg bg-green-600 hover:bg-green-500 text-white text-sm font-semibold transition-colors"
        >
          {t("locked.detail.signup")}
        </Link>
        <Link
          href="/login"
          className="px-5 py-2.5 rounded-lg border border-pitch-700 hover:bg-pitch-800 text-gray-300 text-sm font-medium transition-colors"
        >
          {t("locked.detail.login")}
        </Link>
      </div>
      <p className="text-xs text-gray-600">
        {t("locked.detail.seePre")} <Link href="/stats" className="text-sky-400 hover:underline">{t("locked.detail.accuracy")}</Link>{" "}
        {t("locked.detail.seeMid")} <Link href="/recent" className="text-sky-400 hover:underline">{t("locked.detail.recent")}</Link> {t("locked.detail.seeSuf")}
      </p>
    </div>
  );
}
