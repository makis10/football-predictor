interface StatCardProps {
  label: string;
  value: string | number;
  sub?: string;
  accent?: "green" | "blue" | "yellow" | "red" | "gray";
}

const accentClasses = {
  green:  "text-win",
  blue:   "text-chalk-2",
  yellow: "text-est",
  red:    "text-lose",
  gray:   "text-chalk-2",
};

export function StatCard({ label, value, sub, accent = "gray" }: StatCardProps) {
  return (
    <div className="rounded-xl border border-line bg-ink-700/60 p-4">
      <p className="text-xs text-chalk-3 uppercase tracking-wide mb-1">{label}</p>
      <p className={`text-2xl font-bold ${accentClasses[accent]}`}>{value}</p>
      {sub && <p className="text-xs text-chalk-3 mt-0.5">{sub}</p>}
    </div>
  );
}
