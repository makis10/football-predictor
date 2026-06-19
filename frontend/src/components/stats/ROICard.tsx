import { BTTSStats, CLVStats, ROIStats } from "@/lib/api";

interface Props {
  roi: ROIStats;
  bttsStats?: BTTSStats | null;
  clv?: CLVStats | null;
}

function fmt(n: number, decimals = 2) {
  return n.toFixed(decimals);
}

function roiColor(pct: number) {
  if (pct > 2)  return "text-green-400";
  if (pct > -2) return "text-yellow-400";
  return "text-red-400";
}

function pnlColor(n: number) {
  if (n > 0) return "text-green-400";
  if (n < 0) return "text-red-400";
  return "text-gray-400";
}

function MarketRow({
  label,
  bets,
  staked,
  pnl,
  roi_pct,
}: {
  label: string;
  bets: number;
  staked: number;
  pnl: number;
  roi_pct: number;
}) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-pitch-700/50 last:border-0">
      <div>
        <p className="text-sm text-gray-300 font-medium">{label}</p>
        <p className="text-xs text-gray-500">
          {bets} bets · €{fmt(staked)} staked
        </p>
      </div>
      <div className="text-right">
        <p className={`text-sm font-bold ${pnlColor(pnl)}`}>
          {pnl >= 0 ? "+" : ""}€{fmt(pnl)}
        </p>
        <p className={`text-xs font-semibold ${roiColor(roi_pct)}`}>
          ROI {roi_pct >= 0 ? "+" : ""}{fmt(roi_pct)}%
        </p>
      </div>
    </div>
  );
}

export function ROICard({ roi, bttsStats, clv }: Props) {
  const hasStrategy = roi.strategy_bets > 0;

  return (
    <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-5 space-y-4">
      {/* Header — Strategy ROI is the headline number */}
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-sm font-semibold text-gray-300">
            💰 ROI Tracker — Value Strategy
          </h3>
          <p className="text-xs text-gray-500 mt-0.5">
            {hasStrategy
              ? `Μόνο τα ⚡ suggested bets · €${roi.stake_per_bet} flat · ${roi.strategy_bets} bets`
              : "Δεν υπάρχουν ακόμα διευθετημένα suggested bets"}
          </p>
        </div>
        {hasStrategy && (
          <div className="text-right">
            <p className={`text-xl font-bold ${pnlColor(roi.strategy_pnl)}`}>
              {roi.strategy_pnl >= 0 ? "+" : ""}€{fmt(roi.strategy_pnl)}
            </p>
            <p className={`text-xs font-semibold ${roiColor(roi.strategy_roi_pct)}`}>
              Strategy ROI {roi.strategy_roi_pct >= 0 ? "+" : ""}{fmt(roi.strategy_roi_pct)}%
            </p>
          </div>
        )}
      </div>

      {/* CLV — the fastest reliable edge signal */}
      {clv && clv.bets > 0 && (
        <div className="flex items-center justify-between rounded-lg bg-pitch-900/60 px-3 py-2">
          <div>
            <p className="text-xs text-gray-400 font-medium">📉 Closing Line Value</p>
            <p className="text-[10px] text-gray-600">
              {clv.bets} bets με closing snapshot · θετικό CLV = πραγματικό edge
            </p>
          </div>
          <div className="text-right">
            <p className={`text-sm font-bold ${clv.avg_clv_pct > 0 ? "text-green-400" : "text-red-400"}`}>
              {clv.avg_clv_pct >= 0 ? "+" : ""}{fmt(clv.avg_clv_pct)}%
            </p>
            <p className="text-[10px] text-gray-500">
              beat close {fmt(clv.beat_close_pct, 0)}%
            </p>
          </div>
        </div>
      )}

      {/* Model baseline — bet-everything, expected ≈ −vig */}
      <div className="flex items-baseline justify-between border-t border-pitch-700/50 pt-3">
        <p className="text-xs text-gray-500 font-medium">
          Model baseline (bet σε όλα · {roi.total_bets} bets)
        </p>
        <p className={`text-xs font-semibold ${roiColor(roi.total_roi_pct)}`}>
          {roi.total_pnl >= 0 ? "+" : ""}€{fmt(roi.total_pnl)} · {roi.total_roi_pct >= 0 ? "+" : ""}{fmt(roi.total_roi_pct)}%
        </p>
      </div>

      {/* Market breakdown */}
      <div className="space-y-0">
        <MarketRow
          label="1×2 Result"
          bets={roi.result_bets}
          staked={roi.result_staked}
          pnl={roi.result_pnl}
          roi_pct={roi.result_roi_pct}
        />
        <MarketRow
          label="Over 2.5 Goals"
          bets={roi.goals_bets}
          staked={roi.goals_staked}
          pnl={roi.goals_pnl}
          roi_pct={roi.goals_roi_pct}
        />
        {bttsStats && (
          roi.btts_bets > 0 ? (
            <MarketRow
              label="GG (BTTS)"
              bets={roi.btts_bets}
              staked={roi.btts_staked}
              pnl={roi.btts_pnl}
              roi_pct={roi.btts_roi_pct}
            />
          ) : (
            <div className="flex items-center justify-between py-2 border-b border-pitch-700/50">
              <div>
                <p className="text-sm text-gray-300 font-medium">GG (BTTS)</p>
                <p className="text-xs text-gray-600">
                  Δεν υπάρχουν αποθηκευμένες αποδόσεις BTTS ακόμα
                </p>
              </div>
              <p className="text-xs text-gray-600 italic">pending</p>
            </div>
          )
        )}
      </div>

      {/* Disclaimer */}
      <p className="text-[10px] text-gray-600 leading-relaxed">
        Strategy = flat stake μόνο στα ⚡ suggested value bets (με market-shrunk EV
        gate). Το baseline ποντάρει σε κάθε πρόβλεψη και αναμένεται ≈ −γκανιότα —
        είναι δείκτης υγείας μοντέλου, όχι στρατηγική. Το CLV συγκρίνει τις
        αποδόσεις μας με το κλείσιμο: συστηματικά θετικό CLV είναι η πιο γρήγορη
        αξιόπιστη ένδειξη πραγματικού edge.
      </p>
    </div>
  );
}
