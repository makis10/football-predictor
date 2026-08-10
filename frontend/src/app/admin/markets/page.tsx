import { redirect } from "next/navigation";
import { getSession, fetchWithAuth } from "@/lib/auth";
import { type MarketRecord } from "@/lib/api";
import { getServerT } from "@/lib/i18n-server";

export const dynamic = "force-dynamic";

function fmtRoi(v: number | null): string {
  return v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}

type PageProps = {
  // Next 15+: searchParams is a Promise.
  searchParams: Promise<{ source?: string }>;
};

export default async function MarketRecordPage({ searchParams }: PageProps) {
  const t = await getServerT();
  const session = await getSession();
  if (!(session?.user as any)?.isAdmin) redirect("/");

  const source = (await searchParams).source === "club" ? "club" : "national";
  const res = await fetchWithAuth(`/admin/market-record?source=${source}`);
  const data: MarketRecord | null = res.ok ? await res.json() : null;

  const tabCls = (active: boolean) =>
    `px-3 py-1.5 rounded-lg text-sm font-medium ${
      active ? "bg-ink-600 text-chalk" : "text-chalk-2 hover:text-chalk"
    }`;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Market Record</h1>
        <div className="mt-3 inline-flex gap-1 rounded-xl border border-line bg-ink-800 p-1">
          <a href="/admin/markets?source=national" className={tabCls(source === "national")}>National</a>
          <a href="/admin/markets?source=club" className={tabCls(source === "club")}>Club</a>
        </div>
        <p className="text-sm text-chalk-3 mt-3">
          Shadow-tracked new-model record per market ({source}), over the most-recent{" "}
          {data?.rolling_window ?? 40} settled tickets (rolling window — old results age out,
          so a demoted market can recover on recent form). A market promotes to a headline
          suggestion at ≥{data?.min_samples ?? 30} settled with ROI ≥{" "}
          {data?.roi_floor_pct ?? 0}%. Base markets demote to watch early at ≥
          {data?.demote_min_samples ?? 15} settled with ROI ≤ {data?.demote_roi_ceil_pct ?? -20}%,
          and are held to the same ROI floor at full sample size. Since cutoff {data?.cutoff ?? "—"}.
        </p>
      </div>

      {!data || data.markets.length === 0 ? (
        <div className="rounded-xl border border-line bg-ink-800 p-8 text-center text-chalk-3">
          {t("markets.empty")}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-line">
          <table className="w-full text-sm">
            <thead className="bg-ink-700 text-chalk-2 text-xs uppercase tracking-wide">
              <tr>
                <th className="text-left px-4 py-2">Market</th>
                <th className="text-center px-3 py-2">Status</th>
                <th className="text-right px-3 py-2">Settled</th>
                <th className="text-right px-3 py-2">Win%</th>
                <th className="text-right px-3 py-2">ROI</th>
                <th className="text-right px-4 py-2">To promote</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line-soft">
              {data.markets.map((m) => (
                <tr key={m.market} className="hover:bg-ink-700/40">
                  <td className="px-4 py-2 font-medium text-chalk">{m.market}</td>
                  <td className="px-3 py-2 text-center">
                    {m.demoted ? (
                      <span className="text-[11px] px-2 py-0.5 rounded-full bg-lose/10 text-lose">demoted</span>
                    ) : m.is_base ? (
                      <span className="text-[11px] px-2 py-0.5 rounded-full bg-chalk-2/10 text-chalk-2">base</span>
                    ) : m.proven ? (
                      <span className="text-[11px] px-2 py-0.5 rounded-full bg-win/10 text-win">proven</span>
                    ) : (
                      <span className="text-[11px] px-2 py-0.5 rounded-full bg-est/10 text-est">watch</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-chalk-2">
                    {m.settled}
                    <span className="text-chalk-3 text-xs"> / {m.tracked_total}</span>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-chalk-2">
                    {m.win_pct == null ? "—" : `${Math.round(m.win_pct * 100)}%`}
                  </td>
                  <td className={`px-3 py-2 text-right tabular-nums font-semibold ${
                    m.roi_pct == null ? "text-chalk-3" : m.roi_pct >= 0 ? "text-win" : "text-lose"
                  }`}>
                    {fmtRoi(m.roi_pct)}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums text-chalk-3">
                    {m.is_base || m.proven ? "—" : m.samples_to_promote}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-xs text-chalk-3">
        “watch” markets are shown to users as unproven and recorded here; once the data clears
        the bar they auto-promote to real suggestions. “demoted” base markets are treated as
        watch until their cumulative record recovers. ROI is at the recorded (opening) odds.
      </p>
    </div>
  );
}
