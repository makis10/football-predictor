import { redirect } from "next/navigation";
import { getSession, fetchWithAuth } from "@/lib/auth";
import { type MarketRecord } from "@/lib/api";

export const dynamic = "force-dynamic";

function fmtRoi(v: number | null): string {
  return v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}

type PageProps = {
  // Next 15+: searchParams is a Promise.
  searchParams: Promise<{ source?: string }>;
};

export default async function MarketRecordPage({ searchParams }: PageProps) {
  const session = await getSession();
  if (!(session?.user as any)?.isAdmin) redirect("/");

  const source = (await searchParams).source === "club" ? "club" : "national";
  const res = await fetchWithAuth(`/admin/market-record?source=${source}`);
  const data: MarketRecord | null = res.ok ? await res.json() : null;

  const tabCls = (active: boolean) =>
    `px-3 py-1.5 rounded-lg text-sm font-medium ${
      active ? "bg-pitch-700 text-gray-100" : "text-gray-400 hover:text-gray-200"
    }`;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Market Record</h1>
        <div className="mt-3 inline-flex gap-1 rounded-xl border border-pitch-700 bg-pitch-900 p-1">
          <a href="/admin/markets?source=national" className={tabCls(source === "national")}>National</a>
          <a href="/admin/markets?source=club" className={tabCls(source === "club")}>Club</a>
        </div>
        <p className="text-sm text-gray-500 mt-3">
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
        <div className="rounded-xl border border-pitch-700 bg-pitch-900 p-8 text-center text-gray-500">
          Δεν υπάρχουν ακόμα καταγεγραμμένα tickets.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-pitch-700">
          <table className="w-full text-sm">
            <thead className="bg-pitch-800 text-gray-400 text-xs uppercase tracking-wide">
              <tr>
                <th className="text-left px-4 py-2">Market</th>
                <th className="text-center px-3 py-2">Status</th>
                <th className="text-right px-3 py-2">Settled</th>
                <th className="text-right px-3 py-2">Win%</th>
                <th className="text-right px-3 py-2">ROI</th>
                <th className="text-right px-4 py-2">To promote</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-pitch-800">
              {data.markets.map((m) => (
                <tr key={m.market} className="hover:bg-pitch-800/40">
                  <td className="px-4 py-2 font-medium text-gray-100">{m.market}</td>
                  <td className="px-3 py-2 text-center">
                    {m.demoted ? (
                      <span className="text-[11px] px-2 py-0.5 rounded-full bg-rose-900/40 text-rose-300">demoted</span>
                    ) : m.is_base ? (
                      <span className="text-[11px] px-2 py-0.5 rounded-full bg-sky-900/40 text-sky-300">base</span>
                    ) : m.proven ? (
                      <span className="text-[11px] px-2 py-0.5 rounded-full bg-green-900/40 text-green-300">proven</span>
                    ) : (
                      <span className="text-[11px] px-2 py-0.5 rounded-full bg-amber-900/40 text-amber-300">watch</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-gray-300">
                    {m.settled}
                    <span className="text-gray-600 text-xs"> / {m.tracked_total}</span>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-gray-400">
                    {m.win_pct == null ? "—" : `${Math.round(m.win_pct * 100)}%`}
                  </td>
                  <td className={`px-3 py-2 text-right tabular-nums font-semibold ${
                    m.roi_pct == null ? "text-gray-500" : m.roi_pct >= 0 ? "text-emerald-400" : "text-rose-400"
                  }`}>
                    {fmtRoi(m.roi_pct)}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums text-gray-500">
                    {m.is_base || m.proven ? "—" : m.samples_to_promote}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-xs text-gray-600">
        “watch” markets are shown to users as unproven and recorded here; once the data clears
        the bar they auto-promote to real suggestions. “demoted” base markets are treated as
        watch until their cumulative record recovers. ROI is at the recorded (opening) odds.
      </p>
    </div>
  );
}
