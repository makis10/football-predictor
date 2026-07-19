"use client";

/**
 * Title-odds over time — pure-SVG multi-line chart, no external library.
 *
 * One line per top contender, plotting the MODEL title/champion probability
 * across the daily snapshots written by snapshot_projections.py. As results
 * land, the lines move. A dashed line is drawn for the bookmaker market on any
 * team that has one (usually none off-season).
 */
import { type ProjectionHistorySnapshot } from "@/lib/api";
import { useT } from "@/components/LanguageProvider";

const W = 720;
const H = 260;
const PAD = { top: 16, right: 16, bottom: 34, left: 42 };
const INNER_W = W - PAD.left - PAD.right;
const INNER_H = H - PAD.top - PAD.bottom;
const COLORS = ["#4ade80", "#60a5fa", "#f472b6", "#fbbf24", "#a78bfa", "#22d3ee"];

function path(points: [number, number][]): string {
  return points.map(([x, y], i) => `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
}

export default function ProjectionHistoryChart({
  snapshots,
  topN = 5,
}: {
  snapshots: ProjectionHistorySnapshot[];
  topN?: number;
}) {
  const t = useT();
  if (snapshots.length < 2) {
    return (
      <div className="card p-5">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-2">
          {t("hist.title")}
        </h2>
        <p className="text-[11px] text-gray-600 leading-relaxed">
          {t("hist.empty")}
        </p>
      </div>
    );
  }

  const latest = snapshots[snapshots.length - 1];
  const teams = latest.teams.slice(0, topN).map((t) => t.team);

  const series = teams.map((team) =>
    snapshots.map((s) => s.teams.find((t) => t.team === team)?.prob ?? null),
  );
  const anyMarket = snapshots.some((s) => s.teams.some((t) => t.market_pct != null));

  const maxProb = Math.max(
    0.02,
    ...series.flat().filter((v): v is number => v != null),
    ...(anyMarket
      ? snapshots.flatMap((s) => s.teams.map((t) => t.market_pct ?? 0))
      : [0]),
  );
  const yHi = Math.ceil(maxProb * 1.1 * 20) / 20; // round up to 5%

  const xScale = (i: number) => PAD.left + (i / (snapshots.length - 1)) * INNER_W;
  const yScale = (v: number) => PAD.top + INNER_H - (v / yHi) * INNER_H;

  const yTicks: number[] = [];
  for (let t = 0; t <= yHi + 1e-9; t += 0.05) yTicks.push(t);

  return (
    <div className="card p-5 space-y-3">
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
        {t("hist.title")} {anyMarket && <span className="text-[11px] text-gray-600 normal-case">{t("hist.legend")}</span>}
      </h2>
      <div className="overflow-x-auto">
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ minWidth: 420 }}>
          {yTicks.map((t) => (
            <g key={t}>
              <line x1={PAD.left} y1={yScale(t)} x2={W - PAD.right} y2={yScale(t)} stroke="#1f2937" strokeWidth={1} />
              <text x={PAD.left - 6} y={yScale(t) + 3} textAnchor="end" fontSize={9} fill="#6b7280">
                {Math.round(t * 100)}%
              </text>
            </g>
          ))}
          {snapshots.map((s, i) =>
            i % Math.ceil(snapshots.length / 6) === 0 ? (
              <text key={s.date} x={xScale(i)} y={H - PAD.bottom + 14} textAnchor="middle" fontSize={9} fill="#6b7280">
                {s.date.slice(5)}
              </text>
            ) : null,
          )}
          {series.map((vals, ti) => {
            const pts = vals
              .map((v, i): [number, number] | null => (v == null ? null : [xScale(i), yScale(v)]))
              .filter((p): p is [number, number] => p != null);
            return <path key={ti} d={path(pts)} fill="none" stroke={COLORS[ti % COLORS.length]} strokeWidth={2} />;
          })}
          {anyMarket &&
            teams.map((team, ti) => {
              const pts = snapshots
                .map((s, i): [number, number] | null => {
                  const m = s.teams.find((t) => t.team === team)?.market_pct;
                  return m == null ? null : [xScale(i), yScale(m)];
                })
                .filter((p): p is [number, number] => p != null);
              return pts.length > 1 ? (
                <path key={`m${ti}`} d={path(pts)} fill="none" stroke={COLORS[ti % COLORS.length]} strokeWidth={1.5} strokeDasharray="4 3" opacity={0.7} />
              ) : null;
            })}
        </svg>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {teams.map((team, ti) => (
          <span key={team} className="flex items-center gap-1.5 text-[11px] text-gray-400">
            <span className="w-2.5 h-2.5 rounded-sm" style={{ background: COLORS[ti % COLORS.length] }} />
            {team}
          </span>
        ))}
      </div>
    </div>
  );
}
