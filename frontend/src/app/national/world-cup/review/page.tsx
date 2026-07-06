export const dynamic = "force-dynamic";

import type { Metadata } from "next";
import Link from "next/link";
import { getWcReview, type WcReview } from "@/lib/api";

export const metadata: Metadata = {
  title: "World Cup 2026 Review",
  description: "How the market-independent model performed across the 2026 World Cup — result accuracy, high-confidence calls and the title favourite.",
};

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${(v * 100).toFixed(0)}%`;
}

const OUTCOME_LABEL: Record<string, string> = { H: "νίκη γηπεδούχου", D: "ισοπαλία", A: "νίκη φιλοξ." };

export default async function WcReviewPage() {
  let review: WcReview = { available: false };
  try {
    review = await getWcReview();
  } catch {
    /* fall through */
  }

  if (!review.available || !review.settled) {
    return (
      <div className="space-y-4">
        <Header />
        <div className="text-center py-16 text-gray-500">
          <p className="text-4xl mb-3">🏆</p>
          <p className="font-medium">Review not available yet.</p>
          <p className="text-sm mt-1">Θα γεμίσει καθώς ολοκληρώνονται αγώνες του Παγκοσμίου.</p>
        </div>
      </div>
    );
  }

  const cards = [
    { label: "Settled matches", value: String(review.settled), sub: "με πρόβλεψη + αποτέλεσμα" },
    { label: "Result accuracy", value: pct(review.result_accuracy), sub: `${review.result_correct}/${review.settled} σωστά (1×2)`, accent: true },
    { label: "High-confidence", value: pct(review.high_conf_accuracy), sub: `${review.high_conf_n} σίγουρες κλήσεις (≥55%)`, accent: true },
    { label: "Over/Under 2.5", value: pct(review.ou_accuracy), sub: `${review.ou_total} αγώνες` },
  ];

  return (
    <div className="space-y-6">
      <Header />

      {review.champ_favorite && (
        <div className="rounded-xl border border-amber-700/40 bg-amber-950/20 p-4 text-sm text-gray-300">
          🏆 Το φαβορί του μοντέλου για τον τίτλο (πριν τους νοκ-άουτ):{" "}
          <span className="font-semibold text-amber-300">{review.champ_favorite.team}</span>
          {review.champ_favorite.win_pct != null && (
            <span className="text-gray-500"> ({pct(review.champ_favorite.win_pct)} πιθανότητα)</span>
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
            ✅ Σίγουρες κλήσεις που βγήκαν
          </h2>
          <ul className="divide-y divide-pitch-800">
            {review.highlights.map((h, i) => (
              <li key={i} className="flex items-center justify-between gap-2 py-2 text-sm">
                <span className="text-gray-200">
                  {h.home} <span className="text-gray-500">vs</span> {h.away}
                </span>
                <span className="flex items-center gap-3">
                  {h.score && <span className="tabular-nums text-emerald-400 font-semibold">{h.score}</span>}
                  <span className="text-xs text-gray-500">{OUTCOME_LABEL[h.pick] ?? h.pick} · {pct(h.prob)}</span>
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <p className="text-xs text-gray-600">
        Οι προβλέψεις έγιναν πριν από κάθε αγώνα από το market-independent μοντέλο (talent-adjusted Elo).
        Δες επίσης τη{" "}
        <Link href="/stats?league=International" className="text-sky-400 hover:underline">αναλυτική ακρίβεια</Link>.
      </p>
    </div>
  );
}

function Header() {
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white">World Cup 2026 — Review</h1>
        <p className="text-sm text-gray-500 mt-1">Πώς τα πήγε το μοντέλο στο τουρνουά.</p>
      </div>
      <Link href="/national/world-cup" className="text-sm text-gray-400 hover:text-white whitespace-nowrap">
        ← Simulation
      </Link>
    </div>
  );
}
