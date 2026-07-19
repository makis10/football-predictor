import { BTTSStats, CLVStats, ROIStats } from "@/lib/api";
import type { TFunc } from "@/lib/i18n";

interface Props {
  roi: ROIStats;
  bttsStats?: BTTSStats | null;
  clv?: CLVStats | null;
  t: TFunc;
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
  t,
  label,
  bets,
  staked,
  pnl,
  roi_pct,
  fairPnl,
  fairRoiPct,
  fairEstimated,
}: {
  t: TFunc;
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
          {t("roi.betsStaked", { bets, staked: fmt(staked) })}
          {vig != null && (
            <span className="text-gray-600"> · {t("roi.vig", { amt: euro(vig) })}</span>
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
              {fairRoiPct >= 0 ? "+" : ""}{fmt(fairRoiPct)}% {t("roi.fairSuffix")}{fairEstimated ? "*" : ""}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

export function ROICard({ roi, bttsStats, clv, t }: Props) {
  const hasStrategy = roi.strategy_bets > 0;

  return (
    <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-5 space-y-4">
      {/* Header — Strategy ROI is the headline number */}
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-sm font-semibold text-gray-300">
            {t("roi.header")}
          </h3>
          <p className="text-xs text-gray-500 mt-0.5">
            {hasStrategy
              ? t("roi.subtitle", { stake: roi.stake_per_bet, n: roi.strategy_bets })
              : t("roi.noStrategy")}
          </p>
        </div>
        {hasStrategy && (
          <div className="text-right">
            <p className={`text-xl font-bold ${pnlColor(roi.strategy_pnl)}`}>
              {roi.strategy_pnl >= 0 ? "+" : ""}€{fmt(roi.strategy_pnl)}
            </p>
            <p className={`text-xs font-semibold ${roiColor(roi.strategy_roi_pct)}`}>
              {t("roi.strategyRoi")} {roi.strategy_roi_pct >= 0 ? "+" : ""}{fmt(roi.strategy_roi_pct)}%
            </p>
          </div>
        )}
      </div>

      {/* CLV — the fastest reliable edge signal */}
      {clv && clv.bets > 0 && (
        <div className="flex items-center justify-between rounded-lg bg-pitch-900/60 px-3 py-2">
          <div>
            <p className="text-xs text-gray-400 font-medium">{t("roi.clvTitle")}</p>
            <p className="text-[10px] text-gray-600">
              {t("roi.clvSub", { n: clv.bets })}
            </p>
          </div>
          <div className="text-right">
            <p className={`text-sm font-bold ${clv.avg_clv_pct > 0 ? "text-green-400" : "text-red-400"}`}>
              {clv.avg_clv_pct >= 0 ? "+" : ""}{fmt(clv.avg_clv_pct)}%
            </p>
            <p className="text-[10px] text-gray-500">
              {t("roi.beatClose", { pct: fmt(clv.beat_close_pct, 0) })}
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
                {t("roi.fairTitle")}
              </p>
              <p className="text-[11px] text-gray-400 mt-0.5">
                {t("roi.fairSub")}
              </p>
            </div>
            <div className="text-right">
              <p className={`text-2xl font-bold ${pnlColor(roi.total_pnl_fair)}`}>
                {roi.total_pnl_fair >= 0 ? "+" : ""}€{fmt(roi.total_pnl_fair)}
              </p>
              <p className={`text-xs font-semibold ${roiColor(roi.total_roi_fair_pct)}`}>
                {roi.total_roi_fair_pct >= 0 ? "+" : ""}{fmt(roi.total_roi_fair_pct)}% {t("roi.fairSuffix")}
              </p>
              <p className="text-[11px] text-gray-500 mt-0.5">
                {t("roi.vsWithVig", { amt: fmt(Math.abs(roi.total_pnl)), pct: fmt(roi.total_roi_pct) })}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Model baseline — bet-everything, expected ≈ −vig */}
      <div className="flex items-baseline justify-between border-t border-pitch-700/50 pt-3">
        <p className="text-xs text-gray-500 font-medium">
          {t("roi.modelBaseline", { n: roi.total_bets })}
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
          <span className="min-w-[72px] text-right">{t("roi.colWithVig")}</span>
          <span className="min-w-[72px] text-right pl-3">{t("roi.colModelFair")}</span>
        </div>
      )}

      {/* Market breakdown */}
      <div className="space-y-0">
        <MarketRow
          t={t}
          label={t("roi.market.result")}
          bets={roi.result_bets}
          staked={roi.result_staked}
          pnl={roi.result_pnl}
          roi_pct={roi.result_roi_pct}
          fairPnl={roi.fair_available ? roi.result_pnl_fair : undefined}
          fairRoiPct={roi.fair_available ? roi.result_roi_fair_pct : undefined}
        />
        <MarketRow
          t={t}
          label={t("roi.market.goals")}
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
              t={t}
              label={t("roi.market.btts")}
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
                <p className="text-sm text-gray-300 font-medium">{t("roi.market.btts")}</p>
                <p className="text-xs text-gray-600">
                  {t("roi.bttsPending")}
                </p>
              </div>
              <p className="text-xs text-gray-600 italic">{t("roi.pending")}</p>
            </div>
          )
        )}
      </div>

      {/* Total decomposition: real loss = model contribution − vig paid */}
      {roi.fair_available && (
        <div className="rounded-lg bg-pitch-900/60 px-4 py-3 space-y-1.5 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-gray-400">{t("roi.decomp.real")}</span>
            <span className={`font-bold ${pnlColor(roi.total_pnl)}`}>{euro(roi.total_pnl)}</span>
          </div>
          <div className="flex items-center justify-between border-t border-pitch-700/50 pt-1.5">
            <span className="text-gray-400">{t("roi.decomp.model")}</span>
            <span className={`font-semibold ${pnlColor(roi.total_pnl_fair)}`}>{euro(roi.total_pnl_fair)}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-gray-400">{t("roi.decomp.vig")}</span>
            <span className="font-semibold text-red-400">{euro(roi.total_pnl - roi.total_pnl_fair)}</span>
          </div>
        </div>
      )}

      {/* Disclaimer */}
      <p className="text-[10px] text-gray-600 leading-relaxed">
        {t("roi.disclaimer")}
      </p>
    </div>
  );
}
