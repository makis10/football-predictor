import Link from "next/link";
import { type NationalPrediction, formatDate, formatKickoffUtc } from "@/lib/api";

interface Props {
  prediction: NationalPrediction;
}

function confidenceBadgeClass(confidence: string): string {
  const c = confidence.toUpperCase();
  if (c === "HIGH")   return "bg-green-500/20 text-green-400";
  if (c === "MEDIUM") return "bg-yellow-500/20 text-yellow-400";
  return "bg-gray-500/20 text-gray-400";
}

function overBadgeClass(prob: number): string {
  return prob > 0.5
    ? "bg-orange-500/20 text-orange-400"
    : "bg-sky-600/20 text-sky-400";
}

export default function NationalMatchCard({ prediction: p }: Props) {
  const hasResult = p.actual_result !== null;
  const isCorrect = hasResult && p.prediction === p.actual_result;
  const hasScore  = p.actual_home_goals !== null && p.actual_away_goals !== null;

  // Cards sit under a per-day header, so the date is already obvious — show
  // the kick-off time (Greek wall clock) and fall back to the short date only
  // when no kickoff instant is known yet (e.g. friendlies without odds events).
  const dateLabel = formatKickoffUtc(p.kickoff_utc, p.match_date) ?? formatDate(p.match_date);

  return (
    <Link href={`/national/${p.id}`} className="block group">
    <div className="card p-4 flex flex-col gap-3 h-full hover:border-gray-600 transition-colors">
      {/* Tournament + date row */}
      <div className="flex items-center justify-between text-xs text-gray-500">
        <span className="truncate mr-2">🏆 {p.tournament}</span>
        <span className="shrink-0 tabular-nums">{dateLabel}</span>
      </div>

      {/* Teams + score */}
      <div className="flex items-center justify-between gap-2">
        <span className="font-semibold text-sm text-gray-100 truncate flex-1">
          {p.home_team}
        </span>

        {hasScore ? (
          <span className="text-lg font-bold text-white shrink-0 tabular-nums">
            {p.actual_home_goals} – {p.actual_away_goals}
          </span>
        ) : (
          <span className="text-xs text-gray-600 shrink-0">vs</span>
        )}

        <span className="font-semibold text-sm text-gray-100 truncate flex-1 text-right">
          {p.away_team}
        </span>
      </div>

      {/* Probability bar */}
      <div className="flex gap-1 h-1.5 rounded-full overflow-hidden">
        <div
          className="bg-green-500 rounded-l-full"
          style={{ width: `${Math.round(p.home_win_prob * 100)}%` }}
          title={`Home win ${Math.round(p.home_win_prob * 100)}%`}
        />
        <div
          className="bg-gray-500"
          style={{ width: `${Math.round(p.draw_prob * 100)}%` }}
          title={`Draw ${Math.round(p.draw_prob * 100)}%`}
        />
        <div
          className="bg-blue-500 rounded-r-full"
          style={{ width: `${Math.round(p.away_win_prob * 100)}%` }}
          title={`Away win ${Math.round(p.away_win_prob * 100)}%`}
        />
      </div>

      {/* Probabilities + badges row */}
      <div className="flex items-center justify-between text-xs">
        <span className="text-gray-400 tabular-nums">
          {Math.round(p.home_win_prob * 100)}% ·{" "}
          {Math.round(p.draw_prob * 100)}% ·{" "}
          {Math.round(p.away_win_prob * 100)}%
        </span>
        <div className="flex items-center gap-1.5">
          {p.ev_score != null && p.ev_score > 0 && p.suggested_market && (
            <span
              className="badge bg-emerald-500/20 text-emerald-400 font-semibold"
              title={`${p.suggested_market} — expected value per unit staked (not a probability)`}
            >
              ⚡ EV +{Math.round(p.ev_score * 100)}%
            </span>
          )}
          <span className={`badge ${confidenceBadgeClass(p.confidence)}`}>
            {p.confidence.toUpperCase()}
          </span>
          <span className={`badge ${overBadgeClass(p.over_2_5_prob)}`}>
            O2.5 {Math.round(p.over_2_5_prob * 100)}%
          </span>
        </div>
      </div>

      {/* Bookmaker odds row (1X2) — only when available */}
      {p.bm_home_odds != null && (
        <div className="flex items-center justify-between text-xs text-gray-500">
          <span className="text-gray-600">Odds 1X2</span>
          <span className="tabular-nums text-gray-400">
            {p.bm_home_odds?.toFixed(2) ?? "—"} ·{" "}
            {p.bm_draw_odds?.toFixed(2) ?? "—"} ·{" "}
            {p.bm_away_odds?.toFixed(2) ?? "—"}
            {p.num_bookmakers != null && (
              <span className="text-gray-600"> ({p.num_bookmakers})</span>
            )}
          </span>
        </div>
      )}

      {/* Result row (only when played) */}
      {hasResult && (
        <div className="flex items-center justify-between text-xs mt-auto pt-1 border-t border-pitch-700">
          <span className={isCorrect ? "text-green-400 font-medium" : "text-red-400 font-medium"}>
            {isCorrect ? "✓ Correct" : "✗ Wrong"}
          </span>
          {(p.h_elo != null || p.a_elo != null) && (
            <span className="text-gray-600 tabular-nums">
              Elo: {p.h_elo != null ? Math.round(p.h_elo) : "—"} vs{" "}
              {p.a_elo != null ? Math.round(p.a_elo) : "—"}
            </span>
          )}
        </div>
      )}

      {/* Elo row for upcoming matches (when no result yet) */}
      {!hasResult && (p.h_elo != null || p.a_elo != null) && (
        <div className="flex justify-end text-xs text-gray-600 tabular-nums mt-auto pt-1 border-t border-pitch-700">
          Elo: {p.h_elo != null ? Math.round(p.h_elo) : "—"} vs{" "}
          {p.a_elo != null ? Math.round(p.a_elo) : "—"}
        </div>
      )}
    </div>
    </Link>
  );
}
