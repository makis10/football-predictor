interface AccuracyBarProps {
  label: string;
  value: number;   // 0–1
  color?: string;  // tailwind bg-* class
  showPct?: boolean;
}

export function AccuracyBar({
  label,
  value,
  color = "bg-green-500",
  showPct = true,
}: AccuracyBarProps) {
  const pct = Math.round(value * 100);
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-sm">
        <span className="text-gray-400">{label}</span>
        {showPct && (
          <span className="font-semibold text-gray-200">{pct}%</span>
        )}
      </div>
      <div className="h-2 w-full rounded-full bg-pitch-700 overflow-hidden">
        <div
          className={`h-full rounded-full ${color} transition-all`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
