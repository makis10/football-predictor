/**
 * Locked match-detail panel — freemium gate for logged-out visitors.
 *
 * Rendered server-side INSTEAD of the premium sections, so none of the gated
 * numbers ever reach the HTML — the gate cannot be lifted with dev-tools.
 *
 * Used by three surfaces, all for the same reason: upcoming match detail,
 * /tickets and /projections. What stays public everywhere is the record —
 * finished matches, settled slips, real league tables. That is the accuracy
 * proof, and gating it would hide the only evidence a visitor has that any of
 * this works. Pass `title`/`body` to override the fixture-specific copy.
 */
import Link from "next/link";
import type { TFunc } from "@/lib/i18n";

export default function LockedDetailPanel({
  home,
  away,
  t,
  title,
  body,
}: {
  home?: string;
  away?: string;
  t: TFunc;
  /** Override the match-specific copy. Used by /tickets and /projections,
   *  which are gated for the same reason but are not about one fixture. */
  title?: string;
  body?: string;
}) {
  return (
    <div className="card p-8 text-center space-y-4">
      <p className="text-4xl">🔒</p>
      <div>
        <p className="text-lg font-semibold text-chalk">
          {title ?? t("locked.detail.title", { home: home ?? "", away: away ?? "" })}
        </p>
        <p className="text-sm text-chalk-2 mt-2 max-w-md mx-auto">
          {body ?? t("locked.detail.body")}
        </p>
      </div>
      <div className="flex items-center justify-center gap-3">
        <Link
          href="/register"
          className="px-5 py-2.5 rounded-lg bg-win hover:bg-win text-chalk text-sm font-semibold transition-colors"
        >
          {t("locked.detail.signup")}
        </Link>
        <Link
          href="/login"
          className="px-5 py-2.5 rounded-lg border border-line hover:bg-ink-700 text-chalk-2 text-sm font-medium transition-colors"
        >
          {t("locked.detail.login")}
        </Link>
      </div>
      <p className="text-xs text-chalk-3">
        {t("locked.detail.seePre")} <Link href="/stats" className="text-chalk-2 hover:underline">{t("locked.detail.accuracy")}</Link>{" "}
        {t("locked.detail.seeMid")} <Link href="/recent" className="text-chalk-2 hover:underline">{t("locked.detail.recent")}</Link> {t("locked.detail.seeSuf")}
      </p>
    </div>
  );
}
