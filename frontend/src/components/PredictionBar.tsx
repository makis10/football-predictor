import type { TFunc } from "@/lib/i18n";

interface BarProps {
  label: string;
  probability: number;   // 0–1
  color: string;         // Tailwind bg-* class
  bold?: boolean;
}

function Bar({ label, probability, color, bold }: BarProps) {
  const pct = Math.round(probability * 100);
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-sm">
        <span className={bold ? "font-semibold text-chalk" : "text-chalk-2"}>
          {label}
        </span>
        <span className={bold ? "font-bold text-chalk" : "font-medium text-chalk-2"}>
          {pct}%
        </span>
      </div>
      <div className="prob-bar-track">
        <div
          className={`h-full rounded-full ${color} transition-all`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

interface WinBarProps {
  homeTeam: string;
  awayTeam: string;
  homeWin: number;
  draw: number;
  awayWin: number;
}

export function WinProbabilityBars({
  homeTeam,
  awayTeam,
  homeWin,
  draw,
  awayWin,
}: WinBarProps) {
  const max = Math.max(homeWin, draw, awayWin);
  return (
    <div className="space-y-3">
      <Bar label={homeTeam}  probability={homeWin} color="bg-win"  bold={homeWin === max} />
      <Bar label="Draw"      probability={draw}    color="bg-chalk-2"   bold={draw === max} />
      <Bar label={awayTeam}  probability={awayWin} color="bg-chalk-2"   bold={awayWin === max} />
    </div>
  );
}

interface GoalsBarProps {
  overProb: number;
}

export function GoalsProbabilityBar({ overProb }: GoalsBarProps) {
  const underProb = 1 - overProb;
  return (
    <div className="space-y-3">
      <Bar label="Over 2.5"  probability={overProb}   color="bg-est" bold={overProb > 0.5} />
      <Bar label="Under 2.5" probability={underProb}  color="bg-chalk-2"    bold={underProb > 0.5} />
    </div>
  );
}

interface BttsBarProps {
  bttsProb: number;
  t: TFunc;
}

export function BttsProbabilityBar({ bttsProb, t }: BttsBarProps) {
  const ngProb = 1 - bttsProb;
  return (
    <div className="space-y-3">
      <Bar label={t("pred.ggLabel")} probability={bttsProb} color="bg-win" bold={bttsProb >= 0.5} />
      <Bar label={t("pred.ngLabel")} probability={ngProb} color="bg-lose" bold={ngProb > 0.5} />
    </div>
  );
}
