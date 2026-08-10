interface AccuracyBarProps {
  label: string;
  value: number;   // 0–1
  color?: string;  // tailwind bg-* class
  showPct?: boolean;
}

export function AccuracyBar({
  label,
  value,
  color = "bg-win",
  showPct = true,
}: AccuracyBarProps) {
  const pct = Math.round(value * 100);
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-sm">
        <span className="text-chalk-2">{label}</span>
        {showPct && (
          <span className="font-semibold text-chalk">{pct}%</span>
        )}
      </div>
      <div className="h-2 w-full rounded-full bg-ink-600 overflow-hidden">
        <div
          className={`h-full rounded-full ${color} transition-all`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
