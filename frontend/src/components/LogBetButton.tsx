"use client";
import { useSession } from "next-auth/react";
import { useState } from "react";
import { CLIENT_API_URL as API } from "@/lib/api";

const MARKETS = [
  { value: "home_win",  label: "Home Win" },
  { value: "draw",      label: "Draw" },
  { value: "away_win",  label: "Away Win" },
  { value: "over_2_5",  label: "Over 2.5" },
  { value: "under_2_5", label: "Under 2.5" },
  { value: "btts_yes",  label: "GG (Both Score)" },
  { value: "btts_no",   label: "NG (Not Both Score)" },
];

interface Props {
  matchId: number;
  suggestedMarket?: string | null;
}

export default function LogBetButton({ matchId, suggestedMarket }: Props) {
  const { data: session, status } = useSession();
  const [open, setOpen]     = useState(false);
  const [market, setMarket] = useState(suggestedMarket ?? "home_win");
  const [odds, setOdds]     = useState("");
  const [stake, setStake]   = useState("1");
  const [loading, setLoading] = useState(false);
  const [result, setResult]   = useState<"ok" | "err" | null>(null);
  const [errMsg, setErrMsg]   = useState("");

  if (status === "loading") return null;
  if (status !== "authenticated") return null;

  const userId = String(session?.user?.id ?? "");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!userId) return;
    setLoading(true);
    setResult(null);
    try {
      const res = await fetch(`${API}/users/bets`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          match_id: matchId,
          market,
          odds: parseFloat(odds),
          stake: parseFloat(stake),
        }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        setErrMsg(d.detail ?? "Failed to log bet");
        setResult("err");
      } else {
        setResult("ok");
        setOpen(false);
      }
    } catch (err) {
      setErrMsg(err instanceof Error ? err.message : "Request failed");
      setResult("err");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="w-full">
      {result === "ok" && (
        <div className="rounded-lg bg-win/10 border border-win/40 px-4 py-2 text-sm text-win mb-3">
          Bet logged. Settle it from My ROI after the match.
        </div>
      )}
      {result === "err" && (
        <div className="rounded-lg bg-lose/10 border border-lose/40 px-4 py-2 text-sm text-lose mb-3">
          {errMsg}
        </div>
      )}

      {!open ? (
        <button
          onClick={() => { setOpen(true); setResult(null); }}
          className="w-full rounded-xl border border-line bg-ink-700 hover:bg-ink-600 px-4 py-2.5 text-sm font-medium text-chalk-2 transition-colors text-left flex items-center gap-2"
        >
          <span>🎯</span> Log a bet on this match
        </button>
      ) : (
        <form onSubmit={handleSubmit} className="rounded-xl border border-line bg-ink-700 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm font-semibold text-chalk">🎯 Log bet</p>
            <button type="button" onClick={() => setOpen(false)} className="text-chalk-3 hover:text-chalk-2 text-xs">
              Cancel
            </button>
          </div>

          <div className="grid grid-cols-1 gap-3">
            <div>
              <label className="block text-xs text-chalk-2 mb-1">Market</label>
              <select
                value={market}
                onChange={(e) => setMarket(e.target.value)}
                className="w-full rounded-lg border border-line bg-ink-800 px-3 py-2 text-sm text-chalk focus:outline-none focus:ring-2 focus:ring-win"
              >
                {MARKETS.map((m) => (
                  <option key={m.value} value={m.value}>{m.label}</option>
                ))}
              </select>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-chalk-2 mb-1">Odds</label>
                <input
                  type="number"
                  step="0.01"
                  min="1"
                  required
                  value={odds}
                  onChange={(e) => setOdds(e.target.value)}
                  placeholder="e.g. 2.10"
                  className="w-full rounded-lg border border-line bg-ink-800 px-3 py-2 text-sm text-chalk placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-win"
                />
              </div>
              <div>
                <label className="block text-xs text-chalk-2 mb-1">Stake (units)</label>
                <input
                  type="number"
                  step="any"
                  min="0.01"
                  required
                  value={stake}
                  onChange={(e) => setStake(e.target.value)}
                  className="w-full rounded-lg border border-line bg-ink-800 px-3 py-2 text-sm text-chalk focus:outline-none focus:ring-2 focus:ring-win"
                />
              </div>
            </div>
          </div>

          <button
            type="submit"
            disabled={loading || !odds}
            className="w-full rounded-xl bg-win hover:bg-win disabled:opacity-50 px-4 py-2 text-sm font-medium text-chalk transition-colors"
          >
            {loading ? "Saving…" : "Log bet"}
          </button>
        </form>
      )}
    </div>
  );
}
