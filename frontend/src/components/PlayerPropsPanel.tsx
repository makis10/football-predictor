import { type PlayerProp } from "@/lib/api";

function pct(v: number | null): string {
  return v == null ? "—" : `${Math.round(v * 100)}%`;
}

// Each stat gets its own labelled pill so the meaning is obvious on any screen.
// For FINISHED matches the pill is settled: green ✓ when we caught it (the event
// happened), grey ✗ when it didn't, plus the actual count.
function StatPill({
  label,
  value,
  tone,
  hit,
  actual,
}: {
  label: string;
  value: number | null;
  tone: "score" | "sot" | "assist";
  hit?: boolean | null;
  actual?: number | null;
}) {
  const color =
    tone === "score" ? "text-green-400" : tone === "sot" ? "text-sky-300" : "text-amber-300";
  const settled = hit != null;
  const tint = settled
    ? hit
      ? "ring-1 ring-green-500/40 bg-green-500/10"
      : "ring-1 ring-rose-500/25 bg-rose-500/5"
    : "bg-pitch-900/60";
  return (
    <div className={`flex flex-col items-center rounded-md px-2 py-1 min-w-[3.6rem] ${tint}`}>
      <span className="text-[9px] uppercase tracking-wide text-gray-500 leading-none">{label}</span>
      <span className={`text-sm font-semibold tabular-nums ${color}`}>{pct(value)}</span>
      {settled && (
        <span className={`text-[9px] tabular-nums leading-none mt-0.5 ${hit ? "text-green-400" : "text-gray-500"}`}>
          {hit ? "✓" : "✗"}
          {actual != null ? ` ${actual}` : ""}
        </span>
      )}
    </div>
  );
}

function TeamPropsTable({ team, players }: { team: string; players: PlayerProp[] }) {
  // Finished match? (any player carries settlement). If so, surface the players
  // who actually delivered (scored / shot / assisted), not just our top picks.
  const finished = players.some((p) => p.played != null);
  const ordered = finished
    ? [...players].sort(
        (a, b) =>
          (b.actual_goals ?? 0) - (a.actual_goals ?? 0) ||
          (b.actual_sot ?? 0) - (a.actual_sot ?? 0) ||
          (b.actual_assists ?? 0) - (a.actual_assists ?? 0) ||
          (b.p_score ?? 0) - (a.p_score ?? 0),
      )
    : players;
  const top = ordered.slice(0, 8);
  if (top.length === 0) return null;
  return (
    <div className="space-y-2">
      <h3 className="text-xs font-semibold text-gray-300 uppercase tracking-wide border-b border-pitch-700 pb-1">
        {team}
      </h3>
      {top.map((p) => {
        const dnp = p.played === false;
        return (
          <div
            key={p.player_name}
            className={`flex items-center justify-between gap-2 ${dnp ? "opacity-40" : ""}`}
          >
            <span className="text-sm text-gray-200 truncate flex-1 min-w-0">
              {p.player_name}
              {dnp && <span className="text-[10px] text-gray-500"> · DNP</span>}
            </span>
            <div className="flex gap-1 shrink-0">
              <StatPill label="Σκορ" value={p.p_score} tone="score" hit={dnp ? null : p.score_hit} actual={p.actual_goals} />
              <StatPill label="Σουτ" value={p.p_sot_1} tone="sot" hit={dnp ? null : p.sot_hit} actual={p.actual_sot} />
              <StatPill label="Ασίστ" value={p.p_assist} tone="assist" hit={dnp ? null : p.assist_hit} actual={p.actual_assists} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function PlayerPropsPanel({ teams }: { teams: Record<string, PlayerProp[]> }) {
  const names = Object.keys(teams);
  if (names.length === 0) return null;
  const finished = names.some((t) => teams[t].some((p) => p.played != null));
  return (
    <div className="card p-5 space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
          👤 Στατιστικά Παικτών
        </h2>
        <p className="text-[11px] text-gray-600 mt-1 leading-relaxed">
          Πιθανότητα ανά παίκτη να:{" "}
          <span className="text-green-400">Σκορ</span> = σκοράρει ·{" "}
          <span className="text-sky-300">Σουτ</span> = 1+ σουτ στην εστία ·{" "}
          <span className="text-amber-300">Ασίστ</span> = δώσει ασίστ.{" "}
          {finished
            ? "Κάτω από κάθε πιθανότητα: ✓/✗ τι πιάσαμε + ο πραγματικός αριθμός."
            : "(recency-weighted ρυθμοί × αναμενόμενα γκολ)"}
        </p>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-5">
        {names.map((t) => (
          <TeamPropsTable key={t} team={t} players={teams[t]} />
        ))}
      </div>
    </div>
  );
}
