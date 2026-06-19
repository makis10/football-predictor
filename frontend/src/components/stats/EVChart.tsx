"use client";

/**
 * Cumulative EV vs P&L Chart — pure SVG, no external library.
 *
 * Two lines:
 *   - Cumulative Expected Value (dashed purple) — what the model "deserves"
 *   - Cumulative P&L (solid green/red)          — what actually happened
 *
 * If both lines trend upward together → model has real edge.
 * If EV > P&L → model is underperforming expectations (variance).
 * If EV < P&L → getting lucky, not sustainable.
 */
import { EVDataPoint } from "@/lib/api";
import { useState } from "react";

interface Props {
  series: EVDataPoint[];
}

const W = 800;
const H = 280;
const PAD = { top: 20, right: 20, bottom: 40, left: 60 };
const INNER_W = W - PAD.left - PAD.right;
const INNER_H = H - PAD.top  - PAD.bottom;

function buildPath(points: [number, number][]): string {
  if (points.length === 0) return "";
  return points
    .map(([x, y], i) => `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`)
    .join(" ");
}

function niceStep(range: number, ticks = 6): number {
  const rough = range / ticks;
  const magnitude = Math.pow(10, Math.floor(Math.log10(Math.abs(rough) || 1)));
  const candidates = [1, 2, 5, 10, 20, 50, 100, 200, 500].map((c) => c * magnitude);
  return candidates.find((c) => c >= rough) ?? rough;
}

export function EVChart({ series }: Props) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  if (series.length < 2) {
    return (
      <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-6 text-center">
        <p className="text-sm text-gray-500">
          📈 Cumulative EV chart will appear once bookmaker odds are stored for completed matches.
        </p>
        <p className="text-xs text-gray-600 mt-1">
          Run <code className="font-mono bg-pitch-700 px-1 rounded">compute_predictions.py</code> to populate odds going forward.
        </p>
      </div>
    );
  }

  // Y domain — include 0 and both series extremes
  const allY = series.flatMap((p) => [p.cumulative_ev, p.cumulative_pnl, 0]);
  const yMin = Math.min(...allY);
  const yMax = Math.max(...allY);
  const yRange = yMax - yMin || 1;
  const step = niceStep(yRange);
  const yLo = Math.floor(yMin / step) * step;
  const yHi = Math.ceil(yMax  / step) * step;
  const ySpan = yHi - yLo || 1;

  const xScale = (i: number) => PAD.left + (i / (series.length - 1)) * INNER_W;
  const yScale = (v: number) => PAD.top + INNER_H - ((v - yLo) / ySpan) * INNER_H;

  const evPoints:  [number, number][] = series.map((p, i) => [xScale(i), yScale(p.cumulative_ev)]);
  const pnlPoints: [number, number][] = series.map((p, i) => [xScale(i), yScale(p.cumulative_pnl)]);
  const zeroY = yScale(0);

  // Y-axis ticks
  const yTicks: number[] = [];
  for (let t = yLo; t <= yHi + 0.001; t += step) yTicks.push(t);

  // X-axis: show every Nth label to avoid crowding
  const xTickInterval = Math.ceil(series.length / 6);
  const xTicks = series
    .map((p, i) => ({ i, date: p.date }))
    .filter((_, i) => i % xTickInterval === 0 || i === series.length - 1);

  // Hover data
  const hoverPoint = hoverIdx !== null ? series[hoverIdx] : null;

  return (
    <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-5 space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h3 className="text-sm font-semibold text-gray-300">📈 Cumulative EV vs P&L</h3>
          <p className="text-xs text-gray-500 mt-0.5">€10 flat stake · {series.length} days tracked</p>
        </div>
        {/* Legend — P&L colour matches the line (green=profit, red=loss) */}
        {(() => {
          const lastPnl = series[series.length - 1]?.cumulative_pnl ?? 0;
          const pnlColor = lastPnl >= 0 ? "#4ade80" : "#f87171";
          return (
            <div className="flex items-center gap-4 text-xs text-gray-400">
              <span className="flex items-center gap-1.5">
                <svg width="20" height="4"><line x1="0" y1="2" x2="20" y2="2" stroke="#a78bfa" strokeWidth="2" strokeDasharray="4 2"/></svg>
                Expected Value
              </span>
              <span className="flex items-center gap-1.5">
                <svg width="20" height="4"><line x1="0" y1="2" x2="20" y2="2" stroke={pnlColor} strokeWidth="2"/></svg>
                Actual P&L
              </span>
            </div>
          );
        })()}
      </div>

      {/* Hover tooltip */}
      {hoverPoint && (
        <div className="flex gap-6 text-xs bg-pitch-700 rounded-lg px-3 py-2">
          <span className="text-gray-400">{hoverPoint.date}</span>
          <span className="text-purple-400">
            EV: {hoverPoint.cumulative_ev >= 0 ? "+" : ""}€{hoverPoint.cumulative_ev.toFixed(2)}
          </span>
          <span className={hoverPoint.cumulative_pnl >= 0 ? "text-green-400" : "text-red-400"}>
            P&L: {hoverPoint.cumulative_pnl >= 0 ? "+" : ""}€{hoverPoint.cumulative_pnl.toFixed(2)}
          </span>
        </div>
      )}

      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        style={{ maxHeight: 280 }}
        onMouseLeave={() => setHoverIdx(null)}
      >
        {/* Y grid lines + labels */}
        {yTicks.map((t) => {
          const y = yScale(t);
          return (
            <g key={t}>
              <line x1={PAD.left} x2={W - PAD.right} y1={y} y2={y}
                stroke="#374151" strokeWidth={t === 0 ? 1.5 : 0.5} />
              <text x={PAD.left - 6} y={y + 4} textAnchor="end"
                fill="#6b7280" fontSize={11}>
                {t >= 0 ? `+€${t}` : `-€${Math.abs(t)}`}
              </text>
            </g>
          );
        })}

        {/* Zero line highlight */}
        {zeroY >= PAD.top && zeroY <= H - PAD.bottom && (
          <line x1={PAD.left} x2={W - PAD.right} y1={zeroY} y2={zeroY}
            stroke="#4b5563" strokeWidth={1.5} />
        )}

        {/* EV line (dashed purple) */}
        <path d={buildPath(evPoints)} fill="none" stroke="#a78bfa"
          strokeWidth={2} strokeDasharray="6 3" />

        {/* P&L line (solid, colour by last value) */}
        <path d={buildPath(pnlPoints)} fill="none"
          stroke={series[series.length - 1]?.cumulative_pnl >= 0 ? "#4ade80" : "#f87171"}
          strokeWidth={2.5} />

        {/* X-axis labels */}
        {xTicks.map(({ i, date }) => (
          <text key={i} x={xScale(i)} y={H - 8} textAnchor="middle"
            fill="#6b7280" fontSize={10}>
            {date.slice(5)}  {/* MM-DD */}
          </text>
        ))}

        {/* Hover overlay — invisible rects for hit detection */}
        {series.map((_, i) => {
          const x = xScale(i);
          const w = INNER_W / series.length;
          return (
            <rect
              key={i}
              x={x - w / 2}
              y={PAD.top}
              width={w}
              height={INNER_H}
              fill="transparent"
              onMouseEnter={() => setHoverIdx(i)}
            />
          );
        })}

        {/* Hover dot */}
        {hoverIdx !== null && (
          <>
            <line x1={xScale(hoverIdx)} x2={xScale(hoverIdx)}
              y1={PAD.top} y2={H - PAD.bottom}
              stroke="#6b7280" strokeWidth={1} strokeDasharray="3 2" />
            <circle cx={xScale(hoverIdx)} cy={yScale(series[hoverIdx].cumulative_ev)}
              r={4} fill="#a78bfa" />
            <circle cx={xScale(hoverIdx)} cy={yScale(series[hoverIdx].cumulative_pnl)}
              r={4} fill={series[hoverIdx].cumulative_pnl >= 0 ? "#4ade80" : "#f87171"} />
          </>
        )}
      </svg>
    </div>
  );
}
