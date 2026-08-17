/**
 * /tickets/history — every slip we have ever published, newest first.
 *
 * Split out from the table on /tickets on purpose. That table started as "all
 * earlier slips" and would have become unreadable within a fortnight: five
 * slips a day is 150 rows a month. It now shows only what is still running,
 * which is the thing a reader checks daily; the full record lives here, paged
 * a week at a time like /recent.
 *
 * Slips are drawn by the same TicketCard the offer uses, so a receipt can never
 * disagree with what was published — the whole point of freezing them.
 */
import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { formatLongDate, getTicketHistory, type Ticket } from "@/lib/api";
import TicketCard from "@/components/TicketCard";
import { getServerT } from "@/lib/i18n-server";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Ticket history — every slip, graded",
  description:
    "Every accumulator we have published, oldest to newest, with what each one " +
    "returned. Slips are stored as they were cut and graded once their matches " +
    "finish — nothing is rewritten afterwards.",
};

const DAYS_PER_PAGE = 7;

interface PageProps {
  searchParams: Promise<{ page?: string }>;
}

/** Outcome → the edge treatment on the card's wrapper.
 *  Hue means the same thing here as everywhere else in the system: green is
 *  "this happened", red is "it did not". An open slip gets no hue at all,
 *  because nothing has happened yet. */
const OUTCOME_EDGE: Record<string, string> = {
  won: "ring-1 ring-win/40",
  lost: "ring-1 ring-lose/40",
  void: "opacity-60",
};

async function HistoryGrid({ page }: { page: number }) {
  const t = await getServerT();
  const offsetDays = (page - 1) * DAYS_PER_PAGE;

  let tickets: Ticket[] = [];
  try {
    tickets = (await getTicketHistory(DAYS_PER_PAGE, offsetDays)).tickets;
  } catch {
    return (
      <p className="py-16 text-center text-sm text-chalk-3">
        {t("tickets.history.unavailable")}
      </p>
    );
  }

  if (tickets.length === 0) {
    return (
      <div className="py-16 text-center text-chalk-3">
        <p className="mb-3 text-4xl">🎟️</p>
        <p className="font-medium text-chalk-2">{t("tickets.history.emptyPage")}</p>
      </div>
    );
  }

  // The API already orders newest-first; grouping preserves that order.
  const byDate = tickets.reduce<Record<string, Ticket[]>>((acc, x) => {
    (acc[x.generated_for] ??= []).push(x);
    return acc;
  }, {});

  return (
    <>
      {Object.entries(byDate).map(([day, slips]) => {
        const won = slips.filter((s) => s.outcome === "won").length;
        const lost = slips.filter((s) => s.outcome === "lost").length;
        const open = slips.filter((s) => s.outcome === null).length;
        return (
          <section key={day} className="space-y-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line pb-2">
              <h2 className="font-display text-sm font-extrabold uppercase tracking-[0.14em] text-chalk-3">
                {formatLongDate(day)}
              </h2>
              <p className="font-data text-[11px] text-chalk-3">
                {won > 0 && <span className="text-win">{won}✓</span>}
                {won > 0 && (lost > 0 || open > 0) && " · "}
                {lost > 0 && <span className="text-lose">{lost}✗</span>}
                {lost > 0 && open > 0 && " · "}
                {open > 0 && <span>{t("tickets.history.stillOpen", { n: open })}</span>}
              </p>
            </div>

            <div className="grid grid-cols-1 items-start gap-4 md:grid-cols-2 xl:grid-cols-3">
              {slips.map((slip) => (
                <div
                  key={slip.id}
                  className={`rounded-xl ${OUTCOME_EDGE[slip.outcome ?? ""] ?? ""}`}
                >
                  <TicketCard ticket={slip} />
                </div>
              ))}
            </div>
          </section>
        );
      })}
    </>
  );
}

export default async function TicketHistoryPage({ searchParams }: PageProps) {
  const t = await getServerT();
  const page = Math.max(1, Number((await searchParams).page ?? "1"));
  const href = (p: number) => (p > 1 ? `/tickets/history?page=${p}` : "/tickets/history");

  const from = (page - 1) * DAYS_PER_PAGE;
  const label =
    from === 0
      ? t("tickets.history.windowRecent", { days: DAYS_PER_PAGE })
      : t("tickets.history.windowOlder", { from: from + DAYS_PER_PAGE, to: from + 1 });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-2xl font-extrabold tracking-tight text-chalk">
          {t("tickets.history.pageTitle")}
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-chalk-2">
          {t("tickets.history.pageSubtitle")}{" "}
          <span className="text-win">{t("tickets.history.legendWon")}</span>{" "}
          <span className="text-lose">{t("tickets.history.legendLost")}</span>
        </p>
        <Link
          href="/tickets"
          className="mt-2 inline-block text-xs text-chalk-3 underline underline-offset-2 transition-colors hover:text-chalk-2"
        >
          ← {t("tickets.history.backToToday")}
        </Link>
      </div>

      <Suspense
        fallback={
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-72 animate-pulse rounded-xl bg-ink-700" />
            ))}
          </div>
        }
      >
        <HistoryGrid page={page} />
      </Suspense>

      <div className="flex items-center justify-center gap-3 pt-4">
        {page > 1 && (
          <Link
            href={href(page - 1)}
            className="rounded-lg bg-ink-700 px-4 py-2 text-sm text-chalk-2 transition-colors hover:bg-ink-600"
          >
            ← {t("tickets.history.newer")}
          </Link>
        )}
        <span className="px-2 text-xs text-chalk-3">{label}</span>
        <Link
          href={href(page + 1)}
          className="rounded-lg bg-ink-700 px-4 py-2 text-sm text-chalk-2 transition-colors hover:bg-ink-600"
        >
          {t("tickets.history.older")} →
        </Link>
      </div>
    </div>
  );
}
