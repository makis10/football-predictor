import { redirect } from "next/navigation";
import Link from "next/link";
import { getCurrentUserId, fetchWithAuth } from "@/lib/auth";
import SettleBetButton from "@/components/SettleBetButton";

interface ROIData {
  total_bets:   number;
  settled_bets: number;
  wins:         number;
  losses:       number;
  total_staked: number;
  total_profit: number;
  roi_pct:      number;
  win_rate:     number;
}

interface BetOut {
  id:        number;
  match_id:  number;
  market:    string;
  odds:      number;
  stake:     number;
  outcome:   string | null;
  profit:    number | null;
  placed_at: string;
}

const marketLabel: Record<string, string> = {
  home_win:  "Home Win",
  draw:      "Draw",
  away_win:  "Away Win",
  over_2_5:  "Over 2.5",
  under_2_5: "Under 2.5",
  btts_yes:  "GG",
  btts_no:   "NG",
};

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-pitch-700 bg-pitch-900 p-4 text-center">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className="text-2xl font-bold text-white">{value}</p>
      {sub && <p className="text-xs text-gray-500 mt-0.5">{sub}</p>}
    </div>
  );
}

export default async function MyROIPage() {
  const userId = await getCurrentUserId();
  if (!userId) redirect("/login");

  const [roiRes, betsRes] = await Promise.all([
    fetchWithAuth("/users/roi"),
    fetchWithAuth("/users/bets"),
  ]);

  const roi: ROIData  = roiRes.ok  ? await roiRes.json()  : null;
  const bets: BetOut[] = betsRes.ok ? await betsRes.json() : [];

  if (!roi) {
    return (
      <div className="max-w-2xl mx-auto">
        <h1 className="text-2xl font-bold mb-4">📊 My ROI</h1>
        <p className="text-gray-500">Failed to load data.</p>
      </div>
    );
  }

  const roiColor = roi.roi_pct >= 0 ? "text-green-400" : "text-red-400";

  return (
    <div className="max-w-2xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold">📊 My ROI</h1>
        <p className="text-sm text-gray-500 mt-1">Track your betting performance based on suggested markets</p>
      </div>

      {roi.total_bets === 0 ? (
        <div className="rounded-xl border border-pitch-700 bg-pitch-900 px-6 py-12 text-center">
          <p className="text-gray-400">No bets recorded yet.</p>
          <p className="text-sm text-gray-600 mt-1">
            Log bets from a match analysis page to track your performance.
          </p>
        </div>
      ) : (
        <>
          {/* Summary stats */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatCard label="Total bets" value={String(roi.total_bets)} />
            <StatCard
              label="ROI"
              value={`${roi.roi_pct >= 0 ? "+" : ""}${roi.roi_pct.toFixed(1)}%`}
              sub={roi.settled_bets > 0 ? `${roi.settled_bets} settled` : ""}
            />
            <StatCard label="Win rate" value={`${roi.win_rate.toFixed(1)}%`} sub={`${roi.wins}W ${roi.losses}L`} />
            <StatCard
              label="P&L"
              value={`${roi.total_profit >= 0 ? "+" : ""}${roi.total_profit.toFixed(2)}u`}
              sub={`${roi.total_staked.toFixed(2)}u staked`}
            />
          </div>

          {/* ROI bar */}
          <div className="rounded-xl border border-pitch-700 bg-pitch-900 p-4">
            <div className="flex justify-between text-xs text-gray-500 mb-2">
              <span>P&L</span>
              <span className={roiColor}>
                {roi.total_profit >= 0 ? "+" : ""}{roi.total_profit.toFixed(2)} units
              </span>
            </div>
            <div className="h-2 rounded-full bg-pitch-700 overflow-hidden">
              <div
                className={`h-full rounded-full ${roi.roi_pct >= 0 ? "bg-green-500" : "bg-red-500"}`}
                style={{ width: `${Math.min(Math.abs(roi.roi_pct), 100)}%` }}
              />
            </div>
          </div>

          {/* Bet history */}
          {bets.length > 0 && (
            <section className="space-y-2">
              <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
                Bet History
              </h2>
              <div className="rounded-xl border border-pitch-700 bg-pitch-900 divide-y divide-pitch-700">
                {bets.map((b) => {
                  const mkt = marketLabel[b.market] ?? b.market;
                  const outcomeColor =
                    b.outcome === "win"  ? "text-green-400" :
                    b.outcome === "loss" ? "text-red-400"   :
                    b.outcome === "void" ? "text-gray-500"  :
                    "text-yellow-500";
                  return (
                    <div key={b.id} className="flex items-center gap-3 px-4 py-3">
                      <div className="flex-1 min-w-0">
                        <Link
                          href={`/matches/${b.match_id}`}
                          className="text-sm text-white font-medium hover:text-green-400 transition-colors"
                        >
                          Match #{b.match_id}
                        </Link>
                        <p className="text-xs text-gray-400">
                          <span className="text-green-400">{mkt}</span>
                          {" · "}@{b.odds.toFixed(2)} · {b.stake.toFixed(2)}u
                          {" · "}{new Date(b.placed_at).toLocaleDateString("el-GR")}
                        </p>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        {b.outcome ? (
                          <div className="text-right">
                            <p className={`text-sm font-semibold ${outcomeColor}`}>
                              {b.outcome.toUpperCase()}
                            </p>
                            {b.profit != null && (
                              <p className={`text-xs ${b.profit >= 0 ? "text-green-400" : "text-red-400"}`}>
                                {b.profit >= 0 ? "+" : ""}{b.profit.toFixed(2)}u
                              </p>
                            )}
                          </div>
                        ) : (
                          <>
                            <span className="text-xs text-yellow-500 font-medium">PENDING</span>
                            <SettleBetButton betId={b.id} />
                          </>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
              <p className="text-xs text-gray-600 px-1">
                W = Win · L = Loss · V = Void. Click to settle pending bets.
              </p>
            </section>
          )}
        </>
      )}
    </div>
  );
}
