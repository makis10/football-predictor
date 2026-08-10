/**
 * /tickets — suggested accumulators, drawn as betting slips.
 *
 * Server component, SSR every request: the slips are frozen in the DB by the
 * daily job, but `outcome` flips as results land, so a cached page would show
 * a finished slip as still open.
 */
import type { Metadata } from "next";
import { formatDate, getTickets } from "@/lib/api";
import TicketCard from "@/components/TicketCard";
import { getServerT } from "@/lib/i18n-server";

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

      {tickets.length === 0 ? (
        <div className="text-center py-16 text-chalk-3">
          <p className="text-4xl mb-4">🎟️</p>
          <p className="text-lg font-medium text-chalk-2">{t("tickets.empty.title")}</p>
          <p className="text-sm mt-1">{t("tickets.empty.body")}</p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 items-start">
            {tickets.map((ticket) => (
              <TicketCard key={ticket.id} ticket={ticket} t={t} />
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
                    <td className="px-3 py-2 text-right font-mono text-chalk-2 tabular-nums">
                      {r.settled}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-chalk-2 tabular-nums">
                      {r.won}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-chalk-2 tabular-nums">
                      {Math.round(r.hit_rate * 100)}%
                    </td>
                    <td
                      className={`px-3 py-2 text-right font-mono tabular-nums ${
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
                    <td className="px-3 py-2 text-right font-mono text-chalk-2 tabular-nums">
                      {overall.settled}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-chalk-2 tabular-nums">
                      {overall.won}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-chalk tabular-nums">
                      {Math.round(overall.hit_rate * 100)}%
                    </td>
                    <td
                      className={`px-3 py-2 text-right font-mono tabular-nums ${
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
    </div>
  );
}
