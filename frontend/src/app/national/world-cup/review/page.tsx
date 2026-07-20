export const dynamic = "force-dynamic";

import type { Metadata } from "next";
import Link from "next/link";
import { getWcReview, type WcReview } from "@/lib/api";
import { getServerT } from "@/lib/i18n-server";
import type { TFunc } from "@/lib/i18n";

export const metadata: Metadata = {
  title: "World Cup 2026 Review",
  description: "How the market-independent model performed across the 2026 World Cup — result accuracy, high-confidence calls and the title favourite.",
};

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${(v * 100).toFixed(0)}%`;
}

export default async function WcReviewPage() {
  const t = await getServerT();
  let review: WcReview = { available: false };
  try {
    review = await getWcReview();
  } catch {
    /* fall through */
  }

  if (!review.available || !review.settled) {
    return (
      <div className="space-y-4">
        <Header t={t} />
        <div className="text-center py-16 text-gray-500">
          <p className="text-4xl mb-3">🏆</p>
          <p className="font-medium">{t("rev.emptyTitle")}</p>
          <p className="text-sm mt-1">{t("rev.emptyBody")}</p>
        </div>
      </div>
    );
  }

  const cards = [
    { label: t("rev.settled"), value: String(review.settled), sub: t("rev.settledSub") },
    { label: t("rev.resultAcc"), value: pct(review.result_accuracy), sub: t("rev.resultAccSub", { c: review.result_correct ?? 0, t: review.settled ?? 0 }), accent: true },
    { label: t("rev.highConf"), value: pct(review.high_conf_accuracy), sub: t("rev.highConfSub", { n: review.high_conf_n ?? 0 }), accent: true },
    { label: t("rev.ou"), value: pct(review.ou_accuracy), sub: t("rev.ouSub", { n: review.ou_total ?? 0 }) },
  ];

  return (
    <div className="space-y-6">
      <Header t={t} />

      {review.champ_favorite && (
        <div className="rounded-xl border border-amber-700/40 bg-amber-950/20 p-4 text-sm text-gray-300">
          {t("rev.champFav")}{" "}
          <span className="font-semibold text-amber-300">{review.champ_favorite.team}</span>
          {review.champ_favorite.win_pct != null && (
            <span className="text-gray-500"> {t("rev.champProb", { pct: pct(review.champ_favorite.win_pct) })}</span>
          )}
        </div>
      )}

      <section className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {cards.map((c) => (
          <div key={c.label} className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-4">
            <p className="text-xs text-gray-500">{c.label}</p>
            <p className={`text-2xl font-bold ${c.accent ? "text-emerald-400" : "text-gray-100"}`}>{c.value}</p>
            <p className="text-[11px] text-gray-500 mt-0.5">{c.sub}</p>
          </div>
        ))}
      </section>

      {review.highlights && review.highlights.length > 0 && (
        <section className="card p-5">
          <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-3">
            {t("rev.sureCalls")}
          </h2>
          <ul className="divide-y divide-pitch-800">
            {review.highlights.map((h, i) => (
              <li key={i} className="flex items-center justify-between gap-2 py-2 text-sm">
                <span className="text-gray-200">
                  {h.home} <span className="text-gray-500">vs</span> {h.away}
                </span>
                <span className="flex items-center gap-3">
                  {h.score && <span className="tabular-nums text-emerald-400 font-semibold">{h.score}</span>}
                  <span className="text-xs text-gray-500">{(["H", "D", "A"].includes(h.pick) ? t(`rev.outcome.${h.pick}`) : h.pick)} · {pct(h.prob)}</span>
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <p className="text-xs text-gray-600">
        {t("rev.footPre")}{" "}
        <Link href="/stats?league=International" className="text-sky-400 hover:underline">{t("rev.detailedAcc")}</Link>.
      </p>
    </div>
  );
}

function Header({ t }: { t: TFunc }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white">{t("rev.title")}</h1>
        <p className="text-sm text-gray-500 mt-1">{t("rev.subtitle")}</p>
      </div>
      {/* The simulation page is retired now the tournament is over (that route
          permanently redirects here), so this points at the national hub. */}
      <Link href="/national" className="text-sm text-gray-400 hover:text-white whitespace-nowrap">
        {t("rev.backNational")}
      </Link>
    </div>
  );
}
