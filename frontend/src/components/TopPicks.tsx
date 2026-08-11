/**
 * Top 3 AI Picks of the Day
 *
 * Receives the upcoming matches already fetched by the home page,
 * picks the top 3 by confidence + probability, and renders them
 * in a highlighted row above the fixture grid.
 */
import Link from "next/link";
import { ConfidenceLegend, ProbabilityBar } from "@/components/ProbabilityBar";
import {
  Match,
  leagueFlag,
  leagueLabel,
  formatKickoff,
  formatKickoffUtc,
  formatDate,
  matchHref,
} from "@/lib/api";
import type { TFunc } from "@/lib/i18n";

interface Props {
  matches: Match[];
  t: TFunc;
}

type Pick = { label: string; prob: number; tone: "win" | "neutral" | "lose" };

function topPick(m: Match, t: TFunc): Pick | null {
  const p = m.prediction;
  if (!p) return null;
  const candidates: Pick[] = [
    { label: t("matchCard.pickHome"), prob: p.home_win_prob, tone: "win" },
    { label: t("matchCard.pickDraw"), prob: p.draw_prob, tone: "neutral" },
    { label: t("matchCard.pickAway"), prob: p.away_win_prob, tone: "lose" },
    { label: t("topPicks.over"), prob: p.over_2_5_prob, tone: "win" },
    { label: t("topPicks.under"), prob: 1 - p.over_2_5_prob, tone: "neutral" },
  ];
  return candidates.reduce((best, c) => (c.prob > best.prob ? c : best));
}

export default function TopPicks({ matches, t }: Props) {
  // Exclude no-history fixtures: their default-derived probs are identical and
  // meaningless, so they must never surface as a "top pick".
  const withPreds = matches.filter((m) => m.prediction && !m.prediction.insufficient_data);
  if (withPreds.length === 0) return null;

  // Rank by max result-probability, NOT by confidence tier: club and national
  // define the confidence label with different formulas/thresholds (national
  // "HIGH" needs p_max ≥ 0.65 vs club composite at 0.55), so tier-first sorting
  // over the mixed list systematically inverts the true certainty order.
  const ranked = [...withPreds].sort((a, b) => {
    const maxA = Math.max(a.prediction!.home_win_prob, a.prediction!.draw_prob, a.prediction!.away_win_prob);
    const maxB = Math.max(b.prediction!.home_win_prob, b.prediction!.draw_prob, b.prediction!.away_win_prob);
    return maxB - maxA;
  });

  const top3 = ranked.slice(0, 3);
  if (top3.length === 0) return null;

  return (
    <section className="space-y-3">
      <div className="space-y-1.5">
        <div className="flex flex-wrap items-baseline gap-2">
          <h2 className="font-display text-sm font-extrabold uppercase tracking-[0.14em] text-chalk-3">
            {t("topPicks.heading")}
          </h2>
          <span className="text-xs text-chalk-3">{t("topPicks.subtitle")}</span>
        </div>
        <ConfidenceLegend t={t} />
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {top3.map((match, idx) => {
          const p = match.prediction!;
          const pick = topPick(match, t);
          // kickoff_utc takes precedence: covers kick-offs whose UTC date
          // crosses midnight, where kickoff_time is deliberately null.
          const kickoff =
            formatKickoffUtc(match.kickoff_utc ?? null, match.match_date) ??
            formatKickoff(match.match_date, match.kickoff_time) ??
            formatDate(match.match_date);

          return (
            <Link
              key={`${match.league}-${match.id}`}
              href={matchHref(match)}
              className="card card-pick group space-y-2.5 p-4 transition-colors"
            >
              {/* Rank sits IN the flow. As an absolutely-positioned badge it
                  landed on top of the kick-off time — a 10–12px overlap that
                  rendered as "13:0#1" on every card in the row. */}
              <div className="flex items-center gap-2 text-[11px] text-chalk-3">
                <span className="font-data font-bold text-chalk-2">#{idx + 1}</span>
                <span>{leagueFlag(match.league)}</span>
                <span className="truncate">{leagueLabel(match.league)}</span>
                {kickoff && (
                  <span className="ml-auto shrink-0 font-data tabular-nums text-chalk-2">
                    {kickoff}
                  </span>
                )}
              </div>

              <div>
                <p className="truncate font-display text-[15px] font-bold leading-tight text-chalk">
                  {match.home_team}
                </p>
                <p className="text-[10px] text-chalk-3">vs</p>
                <p className="truncate font-display text-[15px] font-bold leading-tight text-chalk">
                  {match.away_team}
                </p>
              </div>

              {pick && (
                <ProbabilityBar
                  label={pick.label}
                  probability={pick.prob}
                  confidence={p.confidence}
                  tone={pick.tone}
                  emphasis
                  showRange
                  t={t}
                />
              )}
            </Link>
          );
        })}
      </div>
    </section>
  );
}
