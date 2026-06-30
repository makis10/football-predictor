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

function euro(n: number) {
  return `${n >= 0 ? "+" : "−"}€${fmt(Math.abs(n))}`;
}

function MarketRow({
  label,
  bets,
  staked,
  pnl,
  roi_pct,
  fairPnl,
  fairRoiPct,
  fairEstimated,
}: {
  label: string;
  bets: number;
  staked: number;
  pnl: number;
  roi_pct: number;
  fairPnl?: number;
  fairRoiPct?: number;
  fairEstimated?: boolean;
}) {
  // Money lost purely to the bookmaker margin on this market.
  const vig = fairPnl != null ? pnl - fairPnl : null;
  return (
    <div className="flex items-center justify-between py-2 border-b border-pitch-700/50 last:border-0">
      <div>
        <p className="text-sm text-gray-300 font-medium">{label}</p>
        <p className="text-xs text-gray-500">
          {bets} bets · €{fmt(staked)} staked
          {vig != null && (
            <span className="text-gray-600"> · γκανιότα {euro(vig)}</span>
          )}
        </p>
      </div>
      <div className="flex items-center gap-4 text-right">
        <div className="min-w-[72px]">
          <p className={`text-sm font-bold ${pnlColor(pnl)}`}>
            {euro(pnl)}
          </p>
          <p className={`text-xs font-semibold ${roiColor(roi_pct)}`}>
            {roi_pct >= 0 ? "+" : ""}{fmt(roi_pct)}%
          </p>
        </div>
        {fairPnl != null && fairRoiPct != null && (
          <div className="min-w-[72px] border-l border-pitch-700/50 pl-3">
            <p className={`text-sm font-bold ${pnlColor(fairPnl)}`}>
              {euro(fairPnl)}
            </p>
            <p className={`text-xs font-semibold ${roiColor(fairRoiPct)}`}>
              {fairRoiPct >= 0 ? "+" : ""}{fmt(fairRoiPct)}% fair{fairEstimated ? "*" : ""}
            </p>
          </div>
        )}
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

      {/* Fair-value (vig removed) — the honest model-quality headline */}
      {roi.fair_available && (
        <div className="rounded-lg border border-green-700/40 bg-green-950/20 px-4 py-3">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold text-green-300">
                🎯 Fair-value ROI — χωρίς γκανιότα
              </p>
              <p className="text-[11px] text-gray-400 mt-0.5">
                Ίδια στοιχήματα σε δίκαιες (de-vigged) αποδόσεις · ποιότητα μοντέλου vs αγορά
              </p>
            </div>
            <div className="text-right">
              <p className={`text-2xl font-bold ${pnlColor(roi.total_pnl_fair)}`}>
                {roi.total_pnl_fair >= 0 ? "+" : ""}€{fmt(roi.total_pnl_fair)}
              </p>
              <p className={`text-xs font-semibold ${roiColor(roi.total_roi_fair_pct)}`}>
                {roi.total_roi_fair_pct >= 0 ? "+" : ""}{fmt(roi.total_roi_fair_pct)}% fair
              </p>
              <p className="text-[11px] text-gray-500 mt-0.5">
                vs −€{fmt(Math.abs(roi.total_pnl))} ({fmt(roi.total_roi_pct)}%) με γκανιότα
              </p>
            </div>
          </div>
          <p className="text-[10px] text-gray-500 mt-2 leading-relaxed">
            Στις δίκαιες αποδόσεις θα ήμασταν <span className="text-gray-300">≈ στο μηδέν ({roi.total_pnl_fair >= 0 ? "+" : ""}€{fmt(roi.total_pnl_fair)})</span>,
            όχι −€{fmt(Math.abs(roi.total_pnl))}. Όλη η απώλεια των −€{fmt(Math.abs(roi.total_pnl))} είναι
            <span className="text-gray-300"> η προμήθεια του πράκτορα (γκανιότα)</span> — όχι λάθος του μοντέλου.
            Οι προβλέψεις μας είναι τόσο ακριβείς όσο η δίκαιη τιμή της αγοράς.
          </p>
        </div>
      )}

      {/* Model baseline — bet-everything, expected ≈ −vig */}
      <div className="flex items-baseline justify-between border-t border-pitch-700/50 pt-3">
        <p className="text-xs text-gray-500 font-medium">
          Model baseline (bet σε όλα · {roi.total_bets} bets)
        </p>
        <div className="flex items-center gap-4 text-right">
          <p className={`text-xs font-semibold ${roiColor(roi.total_roi_pct)} min-w-[72px]`}>
            {euro(roi.total_pnl)} · {roi.total_roi_pct >= 0 ? "+" : ""}{fmt(roi.total_roi_pct)}%
          </p>
          {roi.fair_available && (
            <p className={`text-xs font-semibold ${roiColor(roi.total_roi_fair_pct)} min-w-[72px] border-l border-pitch-700/50 pl-3`}>
              {euro(roi.total_pnl_fair)} · {roi.total_roi_fair_pct >= 0 ? "+" : ""}{fmt(roi.total_roi_fair_pct)}%
            </p>
          )}
        </div>
      </div>

      {/* Column headers for the per-market breakdown */}
      {roi.fair_available && (
        <div className="flex items-center justify-end gap-4 text-[10px] uppercase tracking-wide text-gray-600 -mb-1">
          <span className="min-w-[72px] text-right">με γκανιότα</span>
          <span className="min-w-[72px] text-right pl-3">μοντέλο (fair)</span>
        </div>
      )}

      {/* Market breakdown */}
      <div className="space-y-0">
        <MarketRow
          label="1×2 Result"
          bets={roi.result_bets}
          staked={roi.result_staked}
          pnl={roi.result_pnl}
          roi_pct={roi.result_roi_pct}
          fairPnl={roi.fair_available ? roi.result_pnl_fair : undefined}
          fairRoiPct={roi.fair_available ? roi.result_roi_fair_pct : undefined}
        />
        <MarketRow
          label="Over 2.5 Goals"
          bets={roi.goals_bets}
          staked={roi.goals_staked}
          pnl={roi.goals_pnl}
          roi_pct={roi.goals_roi_pct}
          fairPnl={roi.fair_available ? roi.goals_pnl_fair : undefined}
          fairRoiPct={roi.fair_available ? roi.goals_roi_fair_pct : undefined}
          fairEstimated={roi.goals_fair_is_estimated}
        />
        {bttsStats && (
          roi.btts_bets > 0 ? (
            <MarketRow
              label="GG (BTTS)"
              bets={roi.btts_bets}
              staked={roi.btts_staked}
              pnl={roi.btts_pnl}
              roi_pct={roi.btts_roi_pct}
              fairPnl={roi.fair_available ? roi.btts_pnl_fair : undefined}
              fairRoiPct={roi.fair_available ? roi.btts_roi_fair_pct : undefined}
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

      {/* Total decomposition: real loss = model contribution − vig paid */}
      {roi.fair_available && (
        <div className="rounded-lg bg-pitch-900/60 px-4 py-3 space-y-1.5 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-gray-400">Πραγματικό αποτέλεσμα (με γκανιότα)</span>
            <span className={`font-bold ${pnlColor(roi.total_pnl)}`}>{euro(roi.total_pnl)}</span>
          </div>
          <div className="flex items-center justify-between border-t border-pitch-700/50 pt-1.5">
            <span className="text-gray-400">↳ από σωστά αποτελέσματα μοντέλου</span>
            <span className={`font-semibold ${pnlColor(roi.total_pnl_fair)}`}>{euro(roi.total_pnl_fair)}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-gray-400">↳ χαμένα σε γκανιότα (προμήθεια πράκτορα)</span>
            <span className="font-semibold text-red-400">{euro(roi.total_pnl - roi.total_pnl_fair)}</span>
          </div>
        </div>
      )}

      {/* Disclaimer */}
      <p className="text-[10px] text-gray-600 leading-relaxed">
        Strategy = flat stake μόνο στα ⚡ suggested value bets (με market-shrunk EV
        gate). Το baseline ποντάρει σε κάθε πρόβλεψη και αναμένεται ≈ −γκανιότα —
        είναι δείκτης υγείας μοντέλου, όχι στρατηγική. Fair-value = ίδια στοιχήματα
        σε de-vigged αποδόσεις (Result &amp; BTTS ακριβώς· *O/U με υποθετικό 4%
        overround αφού δεν αποθηκεύουμε under-2.5 odds). Δεν είναι εφικτή απόδοση —
        πουθενά δεν ποντάρεις σε fair odds — αλλά μετρά καθαρά την ποιότητα του μοντέλου.
      </p>
    </div>
  );
}
