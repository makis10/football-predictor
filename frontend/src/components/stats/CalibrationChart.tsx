/**
 * Server component — renders the O/U calibration chart as inline SVG.
 * No client-side JS needed: we compute geometry server-side.
 */
import { CalibrationBucket } from "@/lib/api";
import type { TFunc } from "@/lib/i18n";

interface CalibrationChartProps {
  buckets: CalibrationBucket[];
  /** Discrimination — the thing this chart cannot show. A perfectly calibrated
   *  constant draws a perfect diagonal and carries no information at all. */
  /** Passed in because these are server components — see SiteNav for why
   *  a function cannot cross to a client component. Without it the AUC
   *  health warning renders in English on the Greek page, which is what
   *  it did until 2026-09-08. */
  t?: TFunc;
  auc?: number | null;
  resolution?: number | null;
}

const W = 560;  // viewBox width
const H = 260;  // viewBox height
const PAD = { top: 16, right: 24, bottom: 40, left: 48 };
const PLOT_W = W - PAD.left - PAD.right;
const PLOT_H = H - PAD.top - PAD.bottom;

function scaleX(v: number) {
  // map [0.30, 1.0] → [0, PLOT_W]
  return ((v - 0.30) / 0.70) * PLOT_W;
}

function scaleY(v: number) {
  // map [0, 1] → [PLOT_H, 0]  (SVG y-axis is inverted)
  return PLOT_H * (1 - v);
}

export function CalibrationChart({ buckets, auc, resolution, t }: CalibrationChartProps) {
  if (buckets.length < 2) {
    return (
      <p className="text-sm text-chalk-3 text-center py-6">
        Not enough data for calibration chart yet.
      </p>
    );
  }

  // Perfect calibration diagonal line points
  const diagPts = [
    `${scaleX(0.30)},${scaleY(0.30)}`,
    `${scaleX(1.00)},${scaleY(1.00)}`,
  ].join(" ");

  // Model calibration line
  const modelPts = buckets
    .map((b) => `${scaleX(b.predicted_prob)},${scaleY(b.actual_rate)}`)
    .join(" ");

  // Y-axis tick labels
  const yTicks = [0, 0.25, 0.50, 0.75, 1.0];
  // X-axis tick labels
  const xTicks = [0.30, 0.50, 0.70, 0.90];

  return (
    <div className="rounded-xl border border-line bg-ink-700/60 p-4">
      <p className="text-sm font-medium text-chalk-2 mb-1">
        O/U Calibration — predicted vs actual over-rate
      </p>
      <p className="text-xs text-chalk-3 mb-1">
        Points near the diagonal mean the numbers are honest — not that they tell
        matches apart. Above = over-predicts, below = under-predicts.
      </p>
      {typeof auc === "number" && (
        <p className={`text-xs mb-3 ${auc < 0.53 ? "text-lose" : "text-chalk-3"}`}>
          {t ? t("stats.discrimination", { auc: auc.toFixed(3) })
             : `AUC ${auc.toFixed(3)} · 0.500 is a coin`}
          {typeof resolution === "number" &&
            ` · resolution ${(resolution * 100).toFixed(2)}%`}
          {auc < 0.53 && (
            <span className="block">{t ? t("stats.discrimination.short") : "not separating matches"}</span>
          )}
        </p>
      )}

      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full max-w-xl"
        aria-label="O/U calibration chart"
      >
        <g transform={`translate(${PAD.left},${PAD.top})`}>
          {/* Grid lines */}
          {yTicks.map((t) => (
            <line
              key={t}
              x1={0} y1={scaleY(t)} x2={PLOT_W} y2={scaleY(t)}
              stroke="#2d3748" strokeWidth={1}
            />
          ))}

          {/* Perfect calibration diagonal */}
          <polyline
            points={diagPts}
            fill="none"
            stroke="#4a5568"
            strokeWidth={1.5}
            strokeDasharray="6 4"
          />

          {/* Model calibration line */}
          <polyline
            points={modelPts}
            fill="none"
            stroke="#48bb78"
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
          />

          {/* Data points */}
          {buckets.map((b, i) => (
            <g key={i}>
              <circle
                cx={scaleX(b.predicted_prob)}
                cy={scaleY(b.actual_rate)}
                r={Math.max(3, Math.min(9, Math.sqrt(b.count) * 0.8))}
                fill="#276749"
                stroke="#48bb78"
                strokeWidth={1.5}
              />
              <title>{t ? t("chart.point", { p: Math.round(b.predicted_prob * 100), a: Math.round(b.actual_rate * 100), n: b.count })
                       : `Predicted: ${Math.round(b.predicted_prob * 100)}% | Actual: ${Math.round(b.actual_rate * 100)}% | n=${b.count}`}</title>
            </g>
          ))}

          {/* Y-axis labels */}
          {yTicks.map((t) => (
            <text
              key={t}
              x={-8} y={scaleY(t) + 4}
              textAnchor="end"
              fontSize={11}
              fill="#718096"
            >
              {Math.round(t * 100)}%
            </text>
          ))}

          {/* X-axis labels */}
          {xTicks.map((t) => (
            <text
              key={t}
              x={scaleX(t)} y={PLOT_H + 20}
              textAnchor="middle"
              fontSize={11}
              fill="#718096"
            >
              {Math.round(t * 100)}%
            </text>
          ))}

          {/* Axes */}
          <line x1={0} y1={0} x2={0} y2={PLOT_H} stroke="#4a5568" strokeWidth={1} />
          <line x1={0} y1={PLOT_H} x2={PLOT_W} y2={PLOT_H} stroke="#4a5568" strokeWidth={1} />

          {/* Axis titles */}
          <text
            x={PLOT_W / 2} y={PLOT_H + 36}
            textAnchor="middle"
            fontSize={11}
            fill="#718096"
          >
            {t ? t("chart.predictedOver") : "Predicted Over Probability"}
          </text>
          <text
            x={-PLOT_H / 2} y={-34}
            textAnchor="middle"
            fontSize={11}
            fill="#718096"
            transform="rotate(-90)"
          >
            {t ? t("chart.actualOver") : "Actual Over Rate"}
          </text>
        </g>
      </svg>

      {/* Legend */}
      <div className="flex items-center gap-4 mt-2 text-xs text-chalk-3">
        <span className="flex items-center gap-1">
          <svg width="20" height="8">
            <line x1={0} y1={4} x2={20} y2={4} stroke="#4a5568" strokeWidth={1.5} strokeDasharray="4 3" />
          </svg>
          {t ? t("chart.perfectCalibration") : "Perfect calibration"}
        </span>
        <span className="flex items-center gap-1">
          <svg width="20" height="8">
            <line x1={0} y1={4} x2={20} y2={4} stroke="#48bb78" strokeWidth={2} />
          </svg>
          {t ? t("chart.model") : "Model"}
        </span>
        {/* The radius saturates well before the largest bin, so it separates
            "a handful" from "a lot" and nothing finer. Exact counts are in each
            point's tooltip. */}
        <span className="text-chalk-3">{t ? t("chart.bubble") : "\u00b7 larger bubble = more matches (hover for the count)"}</span>
      </div>
    </div>
  );
}
