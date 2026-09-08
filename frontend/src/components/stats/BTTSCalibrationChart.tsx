/**
 * Server component — the BTTS (GG/NG) reliability diagram, as inline SVG.
 *
 * 2026-09-07. This chart was the only quality evidence the page offered for a
 * market with AUC 0.5143 on 1,908 settled rows, 78.7% of every probability it
 * has ever produced inside [0.50, 0.60), and a Brier skill score of -0.0064
 * against a constant — worse than replacing every number with the base rate.
 *
 * A reliability diagram cannot show that, and this one actively hid it. A
 * perfectly calibrated CONSTANT plots as a perfect diagonal, so "well
 * calibrated" and "useful" render identically. The curve spanned 25%→74% on two
 * endpoints of n=5 and n=7 while the bin holding 1,501 matches drew at the same
 * radius, because the bubble scale saturates at n>=127 — and the legend claimed
 * "bubble size = sample count" underneath. The subtitle credited Poisson λ for
 * values that come from the XGBoost classifier 96.3% of the time.
 *
 * So the chart now carries the number that separates the two claims (AUC), says
 * plainly when a forecast has no discrimination, and its legend describes what
 * the radius actually does.
 */
import { CalibrationBucket } from "@/lib/api";
import type { TFunc } from "@/lib/i18n";

interface Props {
  buckets: CalibrationBucket[];
  /** Discrimination. null when the sample is too small to compute one. */
  /** Passed in because these are server components — see SiteNav for why
   *  a function cannot cross to a client component. Without it the AUC
   *  health warning renders in English on the Greek page, which is what
   *  it did until 2026-09-08. */
  t?: TFunc;
  auc?: number | null;
  /** Share of outcome variance explained. 0 = every match got the same answer. */
  resolution?: number | null;
}

/** Below this a forecast is not telling matches apart, whatever its
 *  calibration looks like. 0.50 is a coin; 0.53 is inside the noise on any
 *  sample this page has. */
const NO_SIGNAL_AUC = 0.53;

const W = 560;
const H = 260;
const PAD = { top: 16, right: 24, bottom: 40, left: 48 };
const PLOT_W = W - PAD.left - PAD.right;
const PLOT_H = H - PAD.top - PAD.bottom;

function scaleX(v: number) {
  return ((v - 0.0) / 1.0) * PLOT_W;
}

function scaleY(v: number) {
  return PLOT_H * (1 - v);
}

export function BTTSCalibrationChart({ buckets, auc, resolution, t }: Props) {
  if (buckets.length < 2) {
    return (
      <p className="text-sm text-chalk-3 text-center py-6">
        Not enough data for BTTS calibration chart yet.
        Requires predictions with Poisson λ values stored (post-migration 0006).
      </p>
    );
  }

  const diagPts = [`${scaleX(0)},${scaleY(0)}`, `${scaleX(1)},${scaleY(1)}`].join(" ");
  const modelPts = buckets
    .map((b) => `${scaleX(b.predicted_prob)},${scaleY(b.actual_rate)}`)
    .join(" ");

  const yTicks = [0, 0.25, 0.50, 0.75, 1.0];
  const xTicks = [0.10, 0.30, 0.50, 0.70, 0.90];

  return (
    <div className="rounded-xl border border-line bg-ink-700/60 p-4">
      <p className="text-sm font-medium text-chalk-2 mb-1">
        BTTS Calibration — predicted GG probability vs actual GG rate
      </p>
      <p className="text-xs text-chalk-3 mb-1">
        Points near the diagonal mean the numbers are honest — not that they tell
        matches apart. Values come from the BTTS classifier, falling back to the
        stored Poisson λ where none was recorded.
      </p>
      {typeof auc === "number" && (
        <p className={`text-xs mb-3 ${auc < NO_SIGNAL_AUC ? "text-lose" : "text-chalk-3"}`}>
          {t ? t("stats.discrimination", { auc: auc.toFixed(3) })
             : `AUC ${auc.toFixed(3)} · 0.500 is a coin`}
          {typeof resolution === "number" &&
            ` · resolution ${(resolution * 100).toFixed(2)}%`}
          {auc < NO_SIGNAL_AUC && (
            <span className="block">{t ? t("stats.discrimination.short") : "not separating matches"}</span>
          )}
        </p>
      )}

      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full max-w-xl"
        aria-label="BTTS calibration chart"
      >
        <g transform={`translate(${PAD.left},${PAD.top})`}>
          {yTicks.map((t) => (
            <line key={t} x1={0} y1={scaleY(t)} x2={PLOT_W} y2={scaleY(t)}
              stroke="#2d3748" strokeWidth={1} />
          ))}

          <polyline points={diagPts} fill="none" stroke="#4a5568"
            strokeWidth={1.5} strokeDasharray="6 4" />

          <polyline points={modelPts} fill="none" stroke="#63b3ed"
            strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />

          {buckets.map((b, i) => (
            <g key={i}>
              <circle
                cx={scaleX(b.predicted_prob)}
                cy={scaleY(b.actual_rate)}
                r={Math.max(3, Math.min(9, Math.sqrt(b.count) * 0.8))}
                fill="#1a365d"
                stroke="#63b3ed"
                strokeWidth={1.5}
              />
              <title>{t ? t("chart.point", { p: Math.round(b.predicted_prob * 100), a: Math.round(b.actual_rate * 100), n: b.count })
                       : `Predicted: ${Math.round(b.predicted_prob * 100)}% | Actual: ${Math.round(b.actual_rate * 100)}% | n=${b.count}`}</title>
            </g>
          ))}

          {yTicks.map((t) => (
            <text key={t} x={-8} y={scaleY(t) + 4} textAnchor="end" fontSize={11} fill="#718096">
              {Math.round(t * 100)}%
            </text>
          ))}

          {xTicks.map((t) => (
            <text key={t} x={scaleX(t)} y={PLOT_H + 20} textAnchor="middle" fontSize={11} fill="#718096">
              {Math.round(t * 100)}%
            </text>
          ))}

          <line x1={0} y1={0} x2={0} y2={PLOT_H} stroke="#4a5568" strokeWidth={1} />
          <line x1={0} y1={PLOT_H} x2={PLOT_W} y2={PLOT_H} stroke="#4a5568" strokeWidth={1} />

          <text x={PLOT_W / 2} y={PLOT_H + 36} textAnchor="middle" fontSize={11} fill="#718096">
            {t ? t("chart.predictedGG") : "Predicted BTTS (GG) Probability"}
          </text>
          <text x={-PLOT_H / 2} y={-34} textAnchor="middle" fontSize={11} fill="#718096"
            transform="rotate(-90)">
            {t ? t("chart.actualGG") : "Actual GG Rate"}
          </text>
        </g>
      </svg>

      <div className="flex items-center gap-4 mt-2 text-xs text-chalk-3">
        <span className="flex items-center gap-1">
          <svg width="20" height="8">
            <line x1={0} y1={4} x2={20} y2={4} stroke="#4a5568" strokeWidth={1.5} strokeDasharray="4 3" />
          </svg>
          {t ? t("chart.perfectCalibration") : "Perfect calibration"}
        </span>
        <span className="flex items-center gap-1">
          <svg width="20" height="8">
            <line x1={0} y1={4} x2={20} y2={4} stroke="#63b3ed" strokeWidth={2} />
          </svg>
          {t ? t("chart.model") : "Model"}
        </span>
        {/* The radius saturates at n>=127 and floors at n<=14, so it separates
            "a handful" from "a lot" and nothing finer. The old legend read
            "bubble size = sample count", which was false for five of six
            points. Exact counts are in each point's tooltip. */}
        <span className="text-chalk-3">{t ? t("chart.bubble") : "\u00b7 larger bubble = more matches (hover for the count)"}</span>
      </div>
    </div>
  );
}
