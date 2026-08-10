import { type PlayerProp } from "@/lib/api";
import type { TFunc } from "@/lib/i18n";

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
    tone === "score" ? "text-win" : tone === "sot" ? "text-chalk-2" : "text-est";
  const settled = hit != null;
  const tint = settled
    ? hit
      ? "ring-1 ring-win/40 bg-win/10"
      : "ring-1 ring-lose/25 bg-lose/5"
    : "bg-ink-800/60";
  return (
    <div className={`flex flex-col items-center rounded-md px-2 py-1 min-w-[3.6rem] ${tint}`}>
      <span className="text-[9px] uppercase tracking-wide text-chalk-3 leading-none">{label}</span>
      <span className={`text-sm font-semibold tabular-nums ${color}`}>{pct(value)}</span>
      {settled && (
        <span className={`text-[9px] tabular-nums leading-none mt-0.5 ${hit ? "text-win" : "text-chalk-3"}`}>
          {hit ? "✓" : "✗"}
          {actual != null ? ` ${actual}` : ""}
        </span>
      )}
    </div>
  );
}

function TeamPropsTable({ team, players, t }: { team: string; players: PlayerProp[]; t: TFunc }) {
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
      <h3 className="text-xs font-semibold text-chalk-2 uppercase tracking-wide border-b border-line pb-1">
        {team}
      </h3>
      {top.map((p) => {
        const dnp = p.played === false;
        return (
          <div
            key={p.player_name}
            className={`flex items-center justify-between gap-2 ${dnp ? "opacity-40" : ""}`}
          >
            <span className="text-sm text-chalk truncate flex-1 min-w-0">
              {p.player_name}
              {dnp && <span className="text-[10px] text-chalk-3"> · DNP</span>}
            </span>
            <div className="flex gap-1 shrink-0">
              <StatPill label={t("props.score")} value={p.p_score} tone="score" hit={dnp ? null : p.score_hit} actual={p.actual_goals} />
              <StatPill label={t("props.shots")} value={p.p_sot_1} tone="sot" hit={dnp ? null : p.sot_hit} actual={p.actual_sot} />
              <StatPill label={t("props.assist")} value={p.p_assist} tone="assist" hit={dnp ? null : p.assist_hit} actual={p.actual_assists} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function PlayerPropsPanel({ teams, t }: { teams: Record<string, PlayerProp[]>; t: TFunc }) {
  const names = Object.keys(teams);
  if (names.length === 0) return null;
  const finished = names.some((tm) => teams[tm].some((p) => p.played != null));
  return (
    <div className="card p-5 space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-chalk-2 uppercase tracking-wider">
          {t("props.title")}
        </h2>
        <p className="text-[11px] text-chalk-3 mt-1 leading-relaxed">
          {t("props.descPre")}{" "}
          <span className="text-win">{t("props.score")}</span> {t("props.scoreDef")} ·{" "}
          <span className="text-chalk-2">{t("props.shots")}</span> {t("props.shotsDef")} ·{" "}
          <span className="text-est">{t("props.assist")}</span> {t("props.assistDef")}{" "}
          {finished ? t("props.settledNote") : t("props.methodNote")}
        </p>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-5">
        {names.map((tm) => (
          <TeamPropsTable key={tm} team={tm} players={teams[tm]} t={t} />
        ))}
      </div>
    </div>
  );
}
