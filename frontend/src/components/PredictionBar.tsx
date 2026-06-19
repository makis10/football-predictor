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
        <span className={bold ? "font-semibold text-gray-100" : "text-gray-400"}>
          {label}
        </span>
        <span className={bold ? "font-bold text-gray-100" : "font-medium text-gray-300"}>
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
      <Bar label={homeTeam}  probability={homeWin} color="bg-green-500"  bold={homeWin === max} />
      <Bar label="Draw"      probability={draw}    color="bg-gray-500"   bold={draw === max} />
      <Bar label={awayTeam}  probability={awayWin} color="bg-blue-500"   bold={awayWin === max} />
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
      <Bar label="Over 2.5"  probability={overProb}   color="bg-orange-500" bold={overProb > 0.5} />
      <Bar label="Under 2.5" probability={underProb}  color="bg-sky-600"    bold={underProb > 0.5} />
    </div>
  );
}

interface BttsBarProps {
  bttsProb: number;
}

export function BttsProbabilityBar({ bttsProb }: BttsBarProps) {
  const ngProb = 1 - bttsProb;
  return (
    <div className="space-y-3">
      <Bar label="GG (και οι δύο σκοράρουν)" probability={bttsProb} color="bg-emerald-500" bold={bttsProb >= 0.5} />
      <Bar label="NG (τουλάχιστον μία δεν σκοράρει)" probability={ngProb} color="bg-rose-500" bold={ngProb > 0.5} />
    </div>
  );
}
