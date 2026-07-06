/**
 * Top 3 AI Picks of the Day
 *
 * Receives the upcoming matches already fetched by the home page,
 * picks the top 3 by confidence + probability, and renders them
 * in a highlighted row above the fixture grid.
 */
import Link from "next/link";
import { Match, leagueFlag, leagueLabel, formatKickoff, formatKickoffUtc, formatDate, confidenceColor, matchHref } from "@/lib/api";

interface Props {
  matches: Match[];
}

const CONF_RANK: Record<string, number> = { high: 3, medium: 2, low: 1 };

function topPick(m: Match): { label: string; prob: number } | null {
  const p = m.prediction;
  if (!p) return null;
  const candidates = [
    { label: "🏠 Home Win", prob: p.home_win_prob },
    { label: "🤝 Draw",     prob: p.draw_prob },
    { label: "✈️ Away Win", prob: p.away_win_prob },
    { label: "⬆️ Over 2.5", prob: p.over_2_5_prob },
    { label: "⬇️ Under 2.5", prob: 1 - p.over_2_5_prob },
  ];
  return candidates.reduce((best, c) => (c.prob > best.prob ? c : best));
}

export default function TopPicks({ matches }: Props) {
  const withPreds = matches.filter((m) => m.prediction);
  if (withPreds.length === 0) return null;

  const ranked = [...withPreds].sort((a, b) => {
    const confA = CONF_RANK[a.prediction!.confidence] ?? 0;
    const confB = CONF_RANK[b.prediction!.confidence] ?? 0;
    if (confB !== confA) return confB - confA;
    const maxA = Math.max(a.prediction!.home_win_prob, a.prediction!.draw_prob, a.prediction!.away_win_prob);
    const maxB = Math.max(b.prediction!.home_win_prob, b.prediction!.draw_prob, b.prediction!.away_win_prob);
    return maxB - maxA;
  });

  const top3 = ranked.slice(0, 3);
  if (top3.length === 0) return null;

  return (
    <section className="space-y-3">
      <div className="flex items-center gap-2">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
          ⚡ Top AI Picks
        </h2>
        <span className="text-xs text-gray-600">highest-confidence predictions</span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {top3.map((match, idx) => {
          const p = match.prediction!;
          const pick = topPick(match);
          // kickoff_utc takes precedence: covers kick-offs whose UTC date
          // crosses midnight, where kickoff_time is deliberately null.
          const kickoff =
            formatKickoffUtc(match.kickoff_utc ?? null, match.match_date) ??
            formatKickoff(match.match_date, match.kickoff_time) ??
            formatDate(match.match_date);
          const confColor = confidenceColor(p.confidence);

          return (
            <Link
              key={`${match.league}-${match.id}`}
              href={matchHref(match)}
              className="
                group relative rounded-xl border border-green-700/40 bg-green-950/20
                hover:border-green-600/60 hover:bg-green-950/30
                transition-all p-4 space-y-2 overflow-hidden
              "
            >
              {/* Rank badge */}
              <span className="absolute top-3 right-3 text-xs font-bold text-green-600/60">
                #{idx + 1}
              </span>

              {/* League */}
              <p className="text-[11px] text-gray-500 flex items-center gap-1">
                <span>{leagueFlag(match.league)}</span>
                <span>{leagueLabel(match.league)}</span>
                {kickoff && <span className="ml-auto text-gray-600">{kickoff}</span>}
              </p>

              {/* Teams */}
              <div className="space-y-0.5">
                <p className="text-sm font-semibold text-white leading-tight">{match.home_team}</p>
                <p className="text-[10px] text-gray-500">vs</p>
                <p className="text-sm font-semibold text-white leading-tight">{match.away_team}</p>
              </div>

              {/* Top pick */}
              {pick && (
                <div className="flex items-center gap-2">
                  <span className="text-sm font-bold text-green-400">
                    {pick.label}
                  </span>
                  <span className="text-xs text-green-600 font-mono">
                    {Math.round(pick.prob * 100)}%
                  </span>
                </div>
              )}

              {/* Confidence */}
              <p className={`text-[11px] font-medium uppercase tracking-wide ${confColor}`}>
                {p.confidence} confidence
              </p>
            </Link>
          );
        })}
      </div>
    </section>
  );
}
