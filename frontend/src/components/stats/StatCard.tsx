interface StatCardProps {
  label: string;
  value: string | number;
  sub?: string;
  accent?: "green" | "blue" | "yellow" | "red" | "gray";
}

const accentClasses = {
  green:  "text-green-400",
  blue:   "text-blue-400",
  yellow: "text-yellow-400",
  red:    "text-red-400",
  gray:   "text-gray-300",
};

export function StatCard({ label, value, sub, accent = "gray" }: StatCardProps) {
  return (
    <div className="rounded-xl border border-pitch-700 bg-pitch-800/60 p-4">
      <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">{label}</p>
      <p className={`text-2xl font-bold ${accentClasses[accent]}`}>{value}</p>
      {sub && <p className="text-xs text-gray-500 mt-0.5">{sub}</p>}
    </div>
  );
}
