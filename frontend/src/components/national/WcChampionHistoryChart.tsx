"use client";

/**
 * WC champion-odds history — pure-SVG multi-line chart, no external library.
 *
 * One line per top contender, plotting the MODEL title probability across the
 * daily snapshots appended by simulate_wc.py. As real group/knockout results
 * land, the lines move — so you can see who's trending up/down toward the cup.
 */
import { useState } from "react";
import type { WcHistorySnapshot } from "@/lib/api";

interface Props {
  snapshots: WcHistorySnapshot[];
  topN?: number;
}

const W = 800;
const H = 300;
const PAD = { top: 20, right: 20, bottom: 40, left: 50 };
const INNER_W = W - PAD.left - PAD.right;
const INNER_H = H - PAD.top - PAD.bottom;

// distinct, legible on the dark pitch background
const COLORS = ["#4ade80", "#60a5fa", "#f472b6", "#fbbf24", "#a78bfa", "#22d3ee"];

function buildPath(points: [number, number][]): string {
  return points
    .map(([x, y], i) => `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`)
    .join(" ");
}

export function WcChampionHistoryChart({ snapshots, topN = 6 }: Props) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  if (snapshots.length < 2) {
    return (
      <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-6 text-center">
        <p className="text-sm text-gray-500">
          📉 Champion-odds history will appear after a few daily simulations.
        </p>
        <p className="text-xs text-gray-600 mt-1">
          One snapshot is stored per day each time{" "}
          <code className="font-mono bg-pitch-700 px-1 rounded">simulate_wc.py --save-json</code> runs.
        </p>
      </div>
    );
  }

  // Pick the teams to plot = top-N by the LATEST snapshot's win_pct.
  const latest = snapshots[snapshots.length - 1];
  const teams = latest.teams.slice(0, topN).map((t) => t.team);

  // For each team, its win_pct per snapshot (null when absent that day).
  const seriesByTeam = teams.map((team) =>
    snapshots.map((s) => s.teams.find((t) => t.team === team)?.win_pct ?? null),
  );

  const maxWin = Math.max(
    0.01,
    ...seriesByTeam.flat().filter((v): v is number => v != null),
  );
  const yHi = Math.ceil((maxWin * 1.1) * 100) / 100; // round up to whole %

  const xScale = (i: number) => PAD.left + (i / (snapshots.length - 1)) * INNER_W;
  const yScale = (v: number) => PAD.top + INNER_H - (v / yHi) * INNER_H;

  // Y ticks every 5%
  const yTicks: number[] = [];
  for (let t = 0; t <= yHi + 1e-9; t += 0.05) yTicks.push(t);

  const xTickInterval = Math.ceil(snapshots.length / 6);
  const xTicks = snapshots
    .map((s, i) => ({ i, date: s.date }))
    .filter((_, i) => i % xTickInterval === 0 || i === snapshots.length - 1);

  const hoverSnap = hoverIdx !== null ? snapshots[hoverIdx] : null;

  return (
    <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-5 space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h3 className="text-sm font-semibold text-gray-300">📉 Champion odds over time</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            Model title probability · {snapshots.length} daily snapshots
          </p>
        </div>
        <div className="flex items-center gap-3 text-xs text-gray-400 flex-wrap">
          {teams.map((team, ti) => (
            <span key={team} className="flex items-center gap-1.5">
              <svg width="20" height="4">
                <line x1="0" y1="2" x2="20" y2="2" stroke={COLORS[ti % COLORS.length]} strokeWidth="2.5" />
              </svg>
              {team}
            </span>
          ))}
        </div>
      </div>

      {hoverSnap && (
        <div className="flex gap-4 text-xs bg-pitch-700 rounded-lg px-3 py-2 flex-wrap">
          <span className="text-gray-400">{hoverSnap.date}</span>
          {teams.map((team, ti) => {
            const v = hoverSnap.teams.find((t) => t.team === team)?.win_pct;
            return (
              <span key={team} style={{ color: COLORS[ti % COLORS.length] }}>
                {team}: {v == null ? "—" : `${(v * 100).toFixed(1)}%`}
              </span>
            );
          })}
        </div>
      )}

      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        style={{ maxHeight: 300 }}
        onMouseLeave={() => setHoverIdx(null)}
      >
        {yTicks.map((t) => {
          const y = yScale(t);
          return (
            <g key={t}>
              <line x1={PAD.left} x2={W - PAD.right} y1={y} y2={y} stroke="#374151" strokeWidth={0.5} />
              <text x={PAD.left - 6} y={y + 4} textAnchor="end" fill="#6b7280" fontSize={11}>
                {Math.round(t * 100)}%
              </text>
            </g>
          );
        })}

        {seriesByTeam.map((vals, ti) => {
          const pts = vals
            .map((v, i) => (v == null ? null : ([xScale(i), yScale(v)] as [number, number])))
            .filter((p): p is [number, number] => p != null);
          return (
            <path key={teams[ti]} d={buildPath(pts)} fill="none"
              stroke={COLORS[ti % COLORS.length]} strokeWidth={2.5} />
          );
        })}

        {xTicks.map(({ i, date }) => (
          <text key={i} x={xScale(i)} y={H - 8} textAnchor="middle" fill="#6b7280" fontSize={10}>
            {date.slice(5)}
          </text>
        ))}

        {snapshots.map((_, i) => {
          const x = xScale(i);
          const w = INNER_W / snapshots.length;
          return (
            <rect key={i} x={x - w / 2} y={PAD.top} width={w} height={INNER_H}
              fill="transparent" onMouseEnter={() => setHoverIdx(i)} />
          );
        })}

        {hoverIdx !== null && (
          <>
            <line x1={xScale(hoverIdx)} x2={xScale(hoverIdx)} y1={PAD.top} y2={H - PAD.bottom}
              stroke="#6b7280" strokeWidth={1} strokeDasharray="3 2" />
            {seriesByTeam.map((vals, ti) => {
              const v = vals[hoverIdx];
              if (v == null) return null;
              return (
                <circle key={teams[ti]} cx={xScale(hoverIdx)} cy={yScale(v)} r={4}
                  fill={COLORS[ti % COLORS.length]} />
              );
            })}
          </>
        )}
      </svg>
    </div>
  );
}
