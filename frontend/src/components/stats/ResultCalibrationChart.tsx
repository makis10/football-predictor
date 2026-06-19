/**
 * 1×2 Result Calibration Chart — pure SVG, server component.
 *
 * Three lines on one chart:
 *   🟢 Home win  (green)
 *   ⚫ Draw      (gray)
 *   🔵 Away win  (blue)
 *
 * X-axis: model's predicted probability for that outcome
 * Y-axis: actual frequency — how often that outcome occurred
 *
 * Points on the diagonal = perfectly calibrated.
 * Above diagonal = model under-estimates that outcome.
 * Below diagonal = model over-estimates that outcome.
 */
import { ResultCalibration } from "@/lib/api";

interface Props {
  data: ResultCalibration | null;
}

const W = 560;
const H = 260;
const PAD = { top: 16, right: 24, bottom: 40, left: 48 };
const PLOT_W = W - PAD.left - PAD.right;
const PLOT_H = H - PAD.top - PAD.bottom;

// X and Y both span [0, 1]
function scaleX(v: number) { return v * PLOT_W; }
function scaleY(v: number) { return PLOT_H * (1 - v); }

const SERIES = [
  { key: "home" as const, label: "🏠 Home win", color: "#48bb78", dash: "" },
  { key: "draw" as const, label: "🤝 Draw",     color: "#a0aec0", dash: "5 3" },
  { key: "away" as const, label: "✈️ Away win", color: "#63b3ed", dash: "" },
] as const;

const Y_TICKS = [0, 0.25, 0.5, 0.75, 1.0];
const X_TICKS = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8];

export function ResultCalibrationChart({ data }: Props) {
  const hasData = data && (
    data.home.length >= 2 || data.draw.length >= 2 || data.away.length >= 2
  );

  if (!hasData) {
    return (
      <p className="text-sm text-gray-500 text-center py-6">
        Not enough data for result calibration yet — needs more completed matches per probability bucket.
      </p>
    );
  }

  // Perfect calibration diagonal
  const diagPts = `${scaleX(0)},${scaleY(0)} ${scaleX(1)},${scaleY(1)}`;

  return (
    <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-4">
      <p className="text-sm font-medium text-gray-300 mb-1">
        1×2 Result Calibration — predicted vs actual frequency
      </p>
      <p className="text-xs text-gray-500 mb-3">
        Points on the diagonal = well calibrated. Above = model under-estimates, below = over-estimates.
        Minimum 3 matches per bucket shown.
      </p>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full max-w-xl"
        aria-label="1×2 result calibration chart"
      >
        <g transform={`translate(${PAD.left},${PAD.top})`}>
          {/* Grid lines */}
          {Y_TICKS.map((t) => (
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

          {/* Series lines + dots */}
          {SERIES.map(({ key, color, dash }) => {
            const buckets = data[key];
            if (buckets.length < 2) return null;
            const pts = buckets
              .map((b) => `${scaleX(b.predicted_prob)},${scaleY(b.actual_rate)}`)
              .join(" ");
            return (
              <g key={key}>
                <polyline
                  points={pts}
                  fill="none"
                  stroke={color}
                  strokeWidth={2}
                  strokeDasharray={dash || undefined}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
                {buckets.map((b, i) => (
                  <g key={i}>
                    <circle
                      cx={scaleX(b.predicted_prob)}
                      cy={scaleY(b.actual_rate)}
                      r={Math.max(3, Math.min(8, Math.sqrt(b.count) * 0.9))}
                      fill={color}
                      fillOpacity={0.4}
                      stroke={color}
                      strokeWidth={1.5}
                    />
                    <title>{`${key === "home" ? "Home" : key === "draw" ? "Draw" : "Away"}: predicted ${Math.round(b.predicted_prob * 100)}% | actual ${Math.round(b.actual_rate * 100)}% | n=${b.count}`}</title>
                  </g>
                ))}
              </g>
            );
          })}

          {/* Y-axis labels */}
          {Y_TICKS.map((t) => (
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
          {X_TICKS.map((t) => (
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
            textAnchor="middle" fontSize={11} fill="#718096"
          >
            Predicted Outcome Probability
          </text>
          <text
            x={-PLOT_H / 2} y={-34}
            textAnchor="middle" fontSize={11} fill="#718096"
            transform="rotate(-90)"
          >
            Actual Frequency
          </text>
        </g>
      </svg>

      {/* Legend */}
      <div className="flex items-center flex-wrap gap-4 mt-2 text-xs text-gray-400">
        <span className="flex items-center gap-1">
          <svg width="20" height="8">
            <line x1={0} y1={4} x2={20} y2={4} stroke="#4a5568" strokeWidth={1.5} strokeDasharray="4 3" />
          </svg>
          Perfect calibration
        </span>
        {SERIES.map(({ key, label, color }) => (
          data[key].length >= 2 && (
            <span key={key} className="flex items-center gap-1">
              <svg width="20" height="8">
                <line x1={0} y1={4} x2={20} y2={4} stroke={color} strokeWidth={2} />
              </svg>
              {label}
            </span>
          )
        ))}
        <span className="text-gray-600">· bubble size = sample count</span>
      </div>
    </div>
  );
}
