/**
 * /tickets — suggested accumulators, drawn as betting slips.
 *
 * Server component, SSR every request: the slips are frozen in the DB by the
 * daily job, but `outcome` flips as results land, so a cached page would show
 * a finished slip as still open.
 */
import type { Metadata } from "next";
import { formatDate, getTicketHistory, getTickets, type Ticket } from "@/lib/api";
import TicketCard from "@/components/TicketCard";
import TicketHistory from "@/components/TicketHistory";
import { getServerT } from "@/lib/i18n-server";
import { getSession } from "@/lib/auth";
import LockedDetailPanel from "@/components/LockedDetailPanel";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Tickets — ready-made accumulators",
  description:
    "Multi-leg football accumulators built from our model's probabilities: " +
    "1X2, double chance, over/under and BTTS legs, each slip shown with its " +
    "honest chance of landing.",
};

export default async function TicketsPage() {
  const t = await getServerT();
  const session = await getSession();

  let data;
  try {
    data = await getTickets();
  } catch {
    return (
      <div className="text-center py-16 text-chalk-3">
        <p className="text-4xl mb-4">🎟️</p>
        <p className="text-lg font-medium text-chalk-2">{t("tickets.empty.title")}</p>
        <p className="text-sm mt-1">{t("tickets.empty.body")}</p>
      </div>
    );
  }

  const { tickets, record, overall } = data;
  const hasRecord = Boolean(overall && overall.settled > 0);

  // The receipts. Best-effort: a failure here must not take down today's card,
  // which is the reason the page exists.
  let history: Ticket[] = [];
  try {
    history = (await getTicketHistory(30)).tickets;
  } catch {
    /* leave empty — TicketHistory renders nothing */
  }

  return (
    <div className="space-y-8">
      <header className="space-y-1">
        <h1 className="text-2xl font-bold text-chalk">🎟️ {t("tickets.title")}</h1>
        <p className="text-sm text-chalk-2">{t("tickets.subtitle")}</p>
        {data.horizon_days && (
          <p className="text-xs text-chalk-3">
            {t("tickets.window", { days: data.horizon_days })}
            {data.generated_for && (
              <>
                {" · "}
                {t("tickets.generatedFor", {
                  date: formatDate(data.generated_for),
                })}
              </>
            )}
          </p>
        )}
      </header>

      {/* The disclaimer sits ABOVE the slips on purpose. A reader who only sees
          the payouts has been told something untrue by omission. */}
      <section className="rounded-lg border border-est/40 bg-est/10 px-4 py-3">
        <p className="text-xs font-semibold text-est">
          {t("tickets.honesty.title")}
        </p>
        <p className="mt-1 text-xs leading-relaxed text-est/70">
          {t("tickets.honesty.body")}
        </p>
      </section>

      {/* Today's slips are members-only. Rendered server-side, so the legs,
          prices and probabilities never reach the HTML for a logged-out
          visitor. The settled record BELOW stays public on purpose: it is the
          only evidence a stranger has that any of this works, and hiding it
          would leave the gate asking them to take our word for it. */}
      {!session ? (
        <LockedDetailPanel
          t={t}
          title={t("locked.tickets.title")}
          body={t("locked.tickets.body")}
        />
      ) : tickets.length === 0 ? (
        <div className="text-center py-16 text-chalk-3">
          <p className="text-4xl mb-4">🎟️</p>
          <p className="text-lg font-medium text-chalk-2">{t("tickets.empty.title")}</p>
          <p className="text-sm mt-1">{t("tickets.empty.body")}</p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 items-start">
            {tickets.map((ticket) => (
              <TicketCard key={ticket.id} ticket={ticket} />
            ))}
          </div>
          {data.profiles_built < data.profiles_total && (
            <p className="text-xs text-chalk-3">
              {t("tickets.builtCount", {
                built: data.profiles_built,
                total: data.profiles_total,
              })}
            </p>
          )}
        </>
      )}

      {/* Every leg links to a match page, which is gated. Saying so here costs
          one line and stops the reader discovering it by hitting a wall after
          they were interested enough to click. */}

      {/* Track record */}
      <section className="space-y-3">
        <div>
          <h2 className="text-sm font-semibold text-chalk-2 uppercase tracking-wider">
            {t("tickets.record.title")}
          </h2>
          <p className="text-xs text-chalk-3 mt-0.5">{t("tickets.record.body")}</p>
        </div>

        {!hasRecord ? (
          <p className="text-sm text-chalk-3">{t("tickets.record.empty")}</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-line">
            <table className="w-full text-sm">
              <thead className="bg-ink-800/60 text-chalk-3">
                <tr>
                  <th className="text-left font-medium px-3 py-2">
                    {t("tickets.record.profile")}
                  </th>
                  <th className="text-right font-medium px-3 py-2">
                    {t("tickets.record.settled")}
                  </th>
                  <th className="text-right font-medium px-3 py-2">
                    {t("tickets.record.won")}
                  </th>
                  <th className="text-right font-medium px-3 py-2">
                    {t("tickets.record.hitRate")}
                  </th>
                  <th className="text-right font-medium px-3 py-2">
                    {t("tickets.record.roi")}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line-soft">
                {record.map((r) => (
                  <tr key={r.profile}>
                    <td className="px-3 py-2 text-chalk-2">
                      {t(`tickets.profile.${r.profile}`)}
                    </td>
                    <td className="px-3 py-2 text-right font-data text-chalk-2">
                      {r.settled}
                    </td>
                    <td className="px-3 py-2 text-right font-data text-chalk-2">
                      {r.won}
                    </td>
                    <td className="px-3 py-2 text-right font-data text-chalk-2">
                      {Math.round(r.hit_rate * 100)}%
                    </td>
                    <td
                      className={`px-3 py-2 text-right font-data ${
                        r.roi_pct >= 0 ? "text-win" : "text-lose"
                      }`}
                    >
                      {r.roi_pct >= 0 ? "+" : ""}
                      {r.roi_pct.toFixed(1)}%
                    </td>
                  </tr>
                ))}
                {overall && (
                  <tr className="bg-ink-800/40 font-semibold">
                    <td className="px-3 py-2 text-chalk-2">
                      {t("tickets.record.overall")}
                    </td>
                    <td className="px-3 py-2 text-right font-data text-chalk-2">
                      {overall.settled}
                    </td>
                    <td className="px-3 py-2 text-right font-data text-chalk-2">
                      {overall.won}
                    </td>
                    <td className="px-3 py-2 text-right font-data text-chalk">
                      {Math.round(overall.hit_rate * 100)}%
                    </td>
                    <td
                      className={`px-3 py-2 text-right font-data ${
                        overall.roi_pct >= 0 ? "text-win" : "text-lose"
                      }`}
                    >
                      {overall.roi_pct >= 0 ? "+" : ""}
                      {overall.roi_pct.toFixed(1)}%
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* The receipts behind that table — every earlier slip, settled or still
          running. Rendered after the record so the aggregate reads first and
          the individual slips back it up. */}
      {/* Open slips are premium: a slip cut two days ago with a seven-day
          horizon is still bettable, so listing its legs here would hand a
          logged-out visitor exactly what the gate above withholds. Settled
          ones are the record and stay public. */}
      <TicketHistory tickets={session ? history : history.filter((h) => h.outcome)} />
    </div>
  );
}
