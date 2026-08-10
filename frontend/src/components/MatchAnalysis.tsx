"use client";

import { useState, useEffect } from "react";
import { useSession } from "next-auth/react";
import { useT } from "@/components/LanguageProvider";
import Link from "next/link";
import { getAnalysis, getNationalAnalysis, MatchAnalysis, InjuredPlayer, OddsMovement, PoissonStats } from "@/lib/api";

interface Props {
  matchId: number;
  homeTeam: string;
  awayTeam: string;
  /** If true the match already has a result — less useful to show odds */
  isPast?: boolean;
  /** Use national analysis endpoint instead of club */
  isNational?: boolean;
}

// ── Odds movement arrow ───────────────────────────────────────────────────────
// Threshold: ignore sub-3-cent moves (noise from bookmaker rounding).
const MOVEMENT_THRESHOLD = 0.03;

function MovementArrow({ delta }: { delta?: number | null }) {
  if (delta == null || Math.abs(delta) < MOVEMENT_THRESHOLD) return null;
  return delta > 0
    ? <span className="text-win text-[10px] ml-0.5" title={`+${delta.toFixed(2)} (drifted out)`}>↑</span>
    : <span className="text-lose text-[10px] ml-0.5"   title={`${delta.toFixed(2)} (steam move)`}>↓</span>;
}

function ProbBar({
  label,
  model,
  bm,
  color,
  movementDelta,
}: {
  label: string;
  model: number | null;
  bm: number | null | undefined;
  color: string;
  movementDelta?: number | null;
}) {
  const modelPct = model != null ? Math.round(model * 100) : null;
  const bmPct    = bm    != null ? Math.round(bm    * 100) : null;
  const diff     = modelPct != null && bmPct != null ? modelPct - bmPct : null;

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs text-chalk-2">
        <span>{label}</span>
        <div className="flex items-center gap-2">
          {/* Model probability — always white, labelled "ML" when bookmaker is also shown */}
          {modelPct != null && (
            <span className="flex items-center gap-1">
              {bmPct != null && (
                <span className="text-[10px] text-chalk-3 font-medium">ML</span>
              )}
              <span className="font-semibold text-chalk">{modelPct}%</span>
            </span>
          )}
          {/* Bookmaker probability — grey, always labelled "BM" */}
          {bmPct != null && (
            <span className="flex items-center gap-1">
              <span className="text-[10px] text-chalk-3 font-medium">BM</span>
              <span className="text-chalk-2">{bmPct}%</span>
              <MovementArrow delta={movementDelta} />
            </span>
          )}
          {/* Edge indicator */}
          {diff != null && (
            <span
              className={`text-[10px] font-data px-1 rounded ${
                diff > 2
                  ? "bg-win/20 text-win"
                  : diff < -2
                  ? "bg-lose/20 text-lose"
                  : "bg-ink-600 text-chalk-3"
              }`}
            >
              {diff > 0 ? "+" : ""}{diff}pp
            </span>
          )}
        </div>
      </div>
      <div className="relative h-2 rounded-full bg-ink-700 overflow-hidden">
        {/* Model bar */}
        {modelPct != null && (
          <div
            className={`absolute top-0 left-0 h-full rounded-full ${color}`}
            style={{ width: `${modelPct}%`, opacity: 0.85 }}
          />
        )}
        {/* Bookmaker line */}
        {bmPct != null && (
          <div
            /* The market's number as a tick across our bar, so the comparison is
               positional rather than two numbers to subtract in your head. Uses
               the flood token: a hardcoded white tick vanished on the light theme. */
            className="absolute top-0 h-full w-0.5"
            style={{ left: `${bmPct}%`, backgroundColor: "var(--color-flood)" }}
          />
        )}
      </div>
    </div>
  );
}

function Skeleton() {
  return (
    <div className="card p-5 space-y-4 animate-pulse">
      <div className="h-4 w-48 bg-ink-600 rounded" />
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="space-y-1">
            <div className="h-3 w-full bg-ink-600 rounded" />
            <div className="h-2 w-full bg-ink-700 rounded" />
          </div>
        ))}
      </div>
      <div className="space-y-2 pt-2">
        <div className="h-3 w-full bg-ink-600 rounded" />
        <div className="h-3 w-3/4 bg-ink-600 rounded" />
      </div>
    </div>
  );
}

export default function MatchAnalysisPanel({ matchId, homeTeam, awayTeam, isPast, isNational }: Props) {
  const t = useT();
  const { status } = useSession();
  const [data, setData]       = useState<MatchAnalysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);
  const [tab, setTab]             = useState<"model" | "bookmakers">("model");

  useEffect(() => {
    // The analysis API requires a session (freemium gate in /api/proxy) —
    // don't even fire the request for logged-out visitors.
    if (status !== "authenticated") return;
    setLoading(true);
    setError(null);
    (isNational ? getNationalAnalysis : getAnalysis)(matchId)
      .then(setData)
      .catch((e) => setError(e.message ?? "Failed to load analysis"))
      .finally(() => setLoading(false));
  }, [matchId, isNational, status]);

  // Logged-out: compact conversion CTA instead of the analysis panel.
  if (status === "unauthenticated") {
    return (
      <div className="card p-5 text-center space-y-2">
        <p className="text-sm text-chalk-2">
          {t("ma.lockedCta")}
        </p>
        <Link
          href="/register"
          className="inline-block px-4 py-2 rounded-lg bg-win hover:bg-win text-chalk text-sm font-semibold transition-colors"
        >
          {t("ma.signup")}
        </Link>
      </div>
    );
  }

  if (status === "loading" || loading) return <Skeleton />;
  if (error)   return null; // silently hide if no prediction yet

  if (!data) return null;

  const m   = data.model;
  const bm  = data.bookmakers?.fair_probs;
  const ro  = data.bookmakers?.raw_odds;
  const mov = data.odds_movement;

  return (
   <div className="space-y-4">
    <div className="card p-5 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="font-display text-sm font-extrabold uppercase tracking-[0.14em] text-chalk-3">
          Bookmaker Comparison
        </h2>
        {data.has_odds_data && data.bookmakers && (
          <span className="text-xs text-chalk-3">
            {data.bookmakers.num_bookmakers} bookmakers ·{" "}
            {data.bookmakers.bookmakers.slice(0, 2).join(", ")}
            {data.bookmakers.bookmakers.length > 2 ? "…" : ""}
          </span>
        )}
      </div>

      {/* Odds movement summary — only when at least one significant shift exists */}
      {mov && [mov.home_delta, mov.draw_delta, mov.away_delta, mov.over_delta].some(
        (d) => d != null && Math.abs(d) >= MOVEMENT_THRESHOLD
      ) && (
        <div className="flex items-center gap-1.5 text-xs text-chalk-3">
          <span>📈 Odds movement</span>
          {mov.snapshot_age_hours != null && (
            <span className="text-chalk-3">(vs {mov.snapshot_age_hours}h ago)</span>
          )}
          <span className="text-chalk-3">·</span>
          <span className="text-[10px] text-chalk-3">↑ drifted out · ↓ steam move</span>
        </div>
      )}

      {/* Tab switcher */}
      <div className="flex gap-1 bg-ink-700 rounded-lg p-1 text-xs">
        {(["model", "bookmakers"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`flex-1 py-1.5 px-2 rounded-md transition-colors capitalize ${
              tab === t
                ? "bg-ink-600 text-chalk font-medium"
                : "text-chalk-3 hover:text-chalk-2"
            }`}
          >
            {t === "model" ? `Our model (XGBoost)` : "Bookmaker consensus"}
          </button>
        ))}
      </div>

      {/* Probability bars — 1×2, Over/Under, GG/NG */}
      <div className="space-y-2">
        {/* Column header — only when both model and bookmaker values are shown */}
        {tab === "model" && data.has_odds_data && (
          <div className="flex justify-end gap-3 text-[10px] text-chalk-3 pb-0.5 border-b border-line/50">
            <span className="font-medium">ML = our model</span>
            <span className="font-medium">BM = bookmakers</span>
            <span>│ bar = ML · line = BM</span>
          </div>
        )}
        <p className="text-xs text-chalk-3 uppercase tracking-wider">
          1×2 Probabilities
        </p>

        {tab === "model" ? (
          <>
            <ProbBar label="Home win" model={m.home_win} bm={bm?.home_win} color="bg-win" movementDelta={mov?.home_delta} />
            <ProbBar label="Draw"     model={m.draw}     bm={bm?.draw}     color="bg-est"  movementDelta={mov?.draw_delta} />
            <ProbBar label="Away win" model={m.away_win} bm={bm?.away_win} color="bg-chalk-2"    movementDelta={mov?.away_delta} />

            {/* Over / Under 2.5 */}
            <p className="text-xs text-chalk-3 uppercase tracking-wider pt-1">
              Over / Under 2.5
            </p>
            <ProbBar
              label={`Over 2.5${ro?.over_2_5 ? ` @ ${ro.over_2_5}` : ""}`}
              model={m.over_2_5}
              bm={bm?.over_2_5}
              color="bg-est"
              movementDelta={mov?.over_delta}
            />
            <ProbBar
              label={`Under 2.5${ro?.under_2_5 ? ` @ ${ro.under_2_5}` : ""}`}
              model={1 - m.over_2_5}
              bm={bm?.under_2_5}
              color="bg-chalk-2"
              movementDelta={mov?.over_delta != null ? -mov.over_delta : null}
            />

            {/* GG / NG */}
            {m.btts != null && (
              <>
                <p className="text-xs text-chalk-3 uppercase tracking-wider pt-1">
                  GG / NG (Both teams to score)
                </p>
                <ProbBar
                  label={`GG${ro?.btts_yes ? ` @ ${ro.btts_yes}` : ""}`}
                  model={m.btts}
                  bm={bm?.btts_yes}
                  color="bg-win"
                />
                <ProbBar
                  label={`NG${ro?.btts_no ? ` @ ${ro.btts_no}` : ""}`}
                  model={1 - m.btts}
                  bm={bm?.btts_no}
                  color="bg-lose"
                />
              </>
            )}
          </>
        ) : (
          <>
            {bm ? (
              <>
                <ProbBar label="Home win" model={bm.home_win} bm={null} color="bg-win" />
                <ProbBar label="Draw"     model={bm.draw}     bm={null} color="bg-est" />
                <ProbBar label="Away win" model={bm.away_win} bm={null} color="bg-chalk-2" />

                {/* Over / Under 2.5 */}
                {(bm.over_2_5 != null || bm.under_2_5 != null) && (
                  <>
                    <p className="text-xs text-chalk-3 uppercase tracking-wider pt-1">
                      Over / Under 2.5
                    </p>
                    {bm.over_2_5 != null && (
                      <ProbBar
                        label={`Over 2.5${ro?.over_2_5 ? ` @ ${ro.over_2_5}` : ""}`}
                        model={bm.over_2_5}
                        bm={null}
                        color="bg-est"
                      />
                    )}
                    {bm.under_2_5 != null && (
                      <ProbBar
                        label={`Under 2.5${ro?.under_2_5 ? ` @ ${ro.under_2_5}` : ""}`}
                        model={bm.under_2_5}
                        bm={null}
                        color="bg-chalk-2"
                      />
                    )}
                  </>
                )}

                {/* GG / NG */}
                {(bm.btts_yes != null || bm.btts_no != null) && (
                  <>
                    <p className="text-xs text-chalk-3 uppercase tracking-wider pt-1">
                      GG / NG (Both teams to score)
                    </p>
                    {bm.btts_yes != null && (
                      <ProbBar
                        label={`GG${ro?.btts_yes ? ` @ ${ro.btts_yes}` : ""}`}
                        model={bm.btts_yes}
                        bm={null}
                        color="bg-win"
                      />
                    )}
                    {bm.btts_no != null && (
                      <ProbBar
                        label={`NG${ro?.btts_no ? ` @ ${ro.btts_no}` : ""}`}
                        model={bm.btts_no}
                        bm={null}
                        color="bg-lose"
                      />
                    )}
                  </>
                )}
              </>
            ) : (
              <p className="text-sm text-chalk-3 py-2">
                No bookmaker odds available for this match.
              </p>
            )}
          </>
        )}
      </div>

      {/* ── Extended Poisson stats ─────────────────────────────────────── */}
      {data.poisson_stats && (() => {
        const ps: PoissonStats = data.poisson_stats!;
        const pct = (v: number) => `${Math.round(v * 100)}%`;

        // Flag large model disagreement: Poisson and XGBoost give very different
        // Over 2.5 probabilities (>20pp gap). When this happens the Poisson
        // lambdas don't reflect recent form/context — combos/scores become
        // unreliable and are hidden to avoid misleading the user.
        const modelGap = Math.abs(ps.over_2_5 - m.over_2_5);
        const modelsDisagree = modelGap > 0.20;

        // mini bar: filled width proportional to probability
        const MiniBar = ({ prob, color }: { prob: number; color: string }) => (
          <div className="flex-1 h-1.5 bg-ink-600 rounded-full overflow-hidden">
            <div className={`h-full ${color} rounded-full`} style={{ width: `${Math.round(prob * 100)}%` }} />
          </div>
        );

        return (
          <>
            {/* Goals Lines — always visible */}
            <div className="border-t border-line pt-3 space-y-2">
              <div className="flex items-center gap-2 flex-wrap">
                <p className="text-xs font-semibold text-chalk-2 uppercase tracking-wider">
                  Goals Lines
                </p>
                <span className="text-[10px] text-chalk-3">(Poisson model)</span>
                {modelsDisagree && (
                  <span className="text-[10px] text-est/80 border border-est/30 rounded px-1.5 py-0.5">
                    {t("ma.poissonGap", { pp: Math.round(modelGap * 100) })}
                  </span>
                )}
              </div>
              <div className="space-y-1.5">
                {[
                  { label: "1.5", under: ps.under_1_5, over: ps.over_1_5 },
                  { label: "2.5", under: ps.under_2_5, over: ps.over_2_5, highlight: true },
                  { label: "3.5", under: ps.under_3_5, over: ps.over_3_5 },
                ].map(({ label, under, over, highlight }) => (
                  <div key={label} className={`flex items-center gap-2 text-xs rounded px-1.5 py-1 ${highlight ? "bg-ink-600/50" : ""}`}>
                    <span className={`w-6 text-right font-data shrink-0 ${highlight ? "text-chalk font-semibold" : "text-chalk-3"}`}>
                      {label}
                    </span>
                    <span className="text-chalk-3 w-12 text-right shrink-0">{pct(under)} U</span>
                    <MiniBar prob={under} color="bg-chalk-2" />
                    <div className="w-px h-3 bg-ink-600 shrink-0" />
                    <MiniBar prob={over}  color="bg-est" />
                    <span className="text-chalk-3 w-12 shrink-0">O {pct(over)}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Team Goals — always visible */}
            <div className="border-t border-line pt-3 space-y-2">
              <p className="text-xs font-semibold text-chalk-2 uppercase tracking-wider">
                Team Goals (scores 2+)
              </p>
              <div className="space-y-1.5">
                {[
                  { team: homeTeam, over: ps.home_over_1_5, under: ps.home_under_1_5 },
                  { team: awayTeam, over: ps.away_over_1_5, under: ps.away_under_1_5 },
                ].map(({ team, over, under }) => (
                  <div key={team} className="flex items-center gap-2 text-xs">
                    <span className="text-chalk-2 w-28 truncate shrink-0">{team}</span>
                    <MiniBar prob={over}  color="bg-chalk-2" />
                    <span className="text-chalk-2 shrink-0">{pct(over)}</span>
                    <span className="text-chalk-3 shrink-0 text-[10px]">/ {pct(under)} no</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Advanced Stats — always expanded, hidden when models disagree */}
            {!modelsDisagree && <div className="border-t border-line pt-3">
              <span className="text-xs font-semibold text-chalk-2 uppercase tracking-wider">
                {t("ma.analyticStats")}
              </span>

              <div className="mt-3 space-y-4">
                  {/* Correct Scores */}
                  {(() => {
                    // Find dominant combo category and the most likely score within it.
                    // This ensures the highlighted score is consistent with the dominant combo.
                    const comboDefs: { label: string; prob: number; check: (h: number, a: number) => boolean }[] = [
                      { label: "GG + Over 2.5",       prob: ps.btts_and_over_2_5,  check: (h, a) => h >= 1 && a >= 1 && h + a >= 3 },
                      { label: "GG + Under 2.5",      prob: ps.btts_and_under_2_5, check: (h, a) => h >= 1 && a >= 1 && h + a <= 2 },
                      { label: `${homeTeam} + GG`,    prob: ps.home_win_and_btts,  check: (h, a) => h > a && a >= 1 },
                      { label: `${awayTeam} + GG`,    prob: ps.away_win_and_btts,  check: (h, a) => a > h && h >= 1 },
                      { label: `${homeTeam} + NG`,    prob: ps.home_win_and_ng,    check: (h, a) => h > a && a === 0 },
                      { label: `${awayTeam} + NG`,    prob: ps.away_win_and_ng,    check: (h, a) => a > h && h === 0 },
                    ];
                    const topCombo = comboDefs.reduce((best, c) => c.prob > best.prob ? c : best);
                    const topComboScore = ps.top_scores.find(({ score }) => {
                      const [h, a] = score.split("-").map(Number);
                      return topCombo.check(h, a);
                    });

                    return (
                      <div className="space-y-2">
                        <div className="flex items-center gap-2 flex-wrap">
                          <p className="text-xs text-chalk-3 uppercase tracking-wider">{t("ma.likelyScores")}</p>
                          {topComboScore && (
                            <span className="text-xs bg-win/15 border border-win/25 text-win rounded px-1.5 py-0.5">
                              ⭐ {topComboScore.score} ({pct(topComboScore.prob)})
                              <span className="text-win ml-1">· {topCombo.label}</span>
                            </span>
                          )}
                        </div>
                        <div className="grid grid-cols-3 gap-1.5">
                          {ps.top_scores.map(({ score, prob }) => {
                            const [h, a] = score.split("-").map(Number);
                            const isTopCombo = topCombo.check(h, a);
                            return (
                              <div
                                key={score}
                                className={`flex flex-col items-center rounded-lg border py-2 px-1 ${
                                  isTopCombo
                                    ? "border-win/40 bg-win/10"
                                    : "border-line"
                                }`}
                                style={!isTopCombo ? { backgroundColor: `color-mix(in srgb, var(--color-est) ${Math.round(Math.min(prob * 2, 0.15) * 100)}%, transparent)` } : {}}
                              >
                                <span className="text-sm font-semibold text-chalk font-data">{score}</span>
                                <span className="text-[11px] text-chalk-2">{pct(prob)}</span>
                              </div>
                            );
                          })}
                        </div>
                        <p className="text-[10px] text-chalk-3">
                          {t("ma.teal")}
                        </p>
                      </div>
                    );
                  })()}

                  {/* Combo Markets — 2 groups side by side */}
                  <div className="space-y-2">
                    <p className="text-xs text-chalk-3 uppercase tracking-wider">{t("ma.comboMarkets")}</p>
                    <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
                      {/* Left col: GG-based combos */}
                      {[
                        { label: "GG + Over 2.5",  prob: ps.btts_and_over_2_5 },
                        { label: "GG + Under 2.5", prob: ps.btts_and_under_2_5 },
                        { label: `${homeTeam} + GG`,  prob: ps.home_win_and_btts },
                        { label: `${awayTeam} + GG`,  prob: ps.away_win_and_btts },
                      ].map(({ label, prob }) => (
                        <div key={label} className="flex items-center gap-1.5 text-xs col-span-1">
                          <span className="text-chalk-2 w-28 truncate shrink-0">{label}</span>
                          <MiniBar prob={prob} color="bg-win" />
                          <span className="text-chalk-2 shrink-0 w-7 text-right">{pct(prob)}</span>
                        </div>
                      ))}
                      {/* Right col: Clean-sheet combos (aligns with 1-0 / 0-1 scenarios) */}
                      {[
                        { label: `${homeTeam} + NG`, prob: ps.home_win_and_ng,  note: `${t("ma.eg")} 1-0, 2-0` },
                        { label: `${awayTeam} + NG`, prob: ps.away_win_and_ng,  note: `${t("ma.eg")} 0-1, 0-2` },
                      ].map(({ label, prob, note }) => (
                        <div key={label} className="flex items-center gap-1.5 text-xs col-span-1">
                          <div className="flex flex-col w-28 shrink-0">
                            <span className="text-chalk-2 truncate">{label}</span>
                            <span className="text-[10px] text-chalk-3">{note}</span>
                          </div>
                          <MiniBar prob={prob} color="bg-chalk-2" />
                          <span className="text-chalk-2 shrink-0 w-7 text-right">{pct(prob)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
            </div>}
          </>
        );
      })()}

      {/* Injuries & suspensions */}
      {data.has_injury_data && data.injuries && (
        <div className="border-t border-line pt-3 space-y-2">
          <p className="text-xs font-semibold text-chalk-2 uppercase tracking-wider">
            Injuries &amp; Suspensions
          </p>
          <div className="grid grid-cols-2 gap-3">
            {([["home", homeTeam], ["away", awayTeam]] as const).map(([side, teamName]) => {
              const players = data.injuries![side];
              return (
                <div key={side} className="space-y-1">
                  <p className="text-xs text-chalk-3 font-medium">{teamName}</p>
                  {players.length === 0 ? (
                    <p className="text-xs text-chalk-3 italic">No issues reported</p>
                  ) : (
                    players.map((p: InjuredPlayer, i: number) => (
                      <div key={i} className="flex items-start gap-1.5">
                        <span className={`mt-0.5 text-xs shrink-0 ${
                          p.type === "Suspended"   ? "text-lose"
                          : p.type === "Questionable" ? "text-est"
                          : "text-est"
                        }`}>
                          {p.type === "Suspended" ? "🟥" : p.type === "Questionable" ? "🟡" : "🚑"}
                        </span>
                        <span className="text-xs text-chalk-2 leading-tight">
                          <span className="font-medium">{p.name}</span>
                          {p.reason && (
                            <span className="text-chalk-3 ml-1">({p.reason})</span>
                          )}
                        </span>
                      </div>
                    ))
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* AI analysis */}
      <div className="border-t border-line pt-3 space-y-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-chalk-2 uppercase tracking-wider">
            {t("ma.aiAnalysis")}
          </span>
          <span className="text-xs text-chalk-3">(gpt-oss-120b · Groq)</span>
        </div>
        <p className="text-sm text-chalk-2 leading-relaxed">{data.analysis}</p>

        {/* Picks row — blue (high probability) + green (value bet) */}
        {(() => {
          // Determine top-probability market from model probs.
          // Include GG/NG when the Poisson BTTS probability is available.
          const picks: { label: string; key: string; prob: number }[] = [
            { label: t("ma.win", { team: homeTeam }), key: "home_win",  prob: m.home_win },
            { label: t("ma.draw"),                    key: "draw",      prob: m.draw },
            { label: t("ma.win", { team: awayTeam }), key: "away_win",  prob: m.away_win },
            { label: "Over 2.5",         key: "over_2_5",  prob: m.over_2_5 },
            { label: "Under 2.5",        key: "under_2_5", prob: 1 - m.over_2_5 },
            ...(m.btts != null
              ? [
                  { label: t("ma.ggFull"), key: "btts_yes", prob: m.btts },
                  { label: "NG",           key: "btts_no",  prob: 1 - m.btts },
                ]
              : []),
          ];

          const topPick = picks.reduce((best, cur) =>
            cur.prob > best.prob ? cur : best
          );
          const topOdds = ro?.[topPick.key as keyof typeof ro];

          return (
            <div className="mt-2 flex flex-wrap gap-2">
              {/* Blue — highest-probability outcome */}
              {topOdds != null && (
                <div className="inline-flex items-center gap-2 bg-chalk-2/10 border border-chalk-2/20 rounded-lg px-3 py-2">
                  <span className="text-chalk-2 text-xs">📊</span>
                  <div className="flex flex-col leading-tight">
                    <span className="text-[10px] text-chalk-2 font-semibold uppercase tracking-wide">
                      {t("ma.mostLikely")}
                    </span>
                    <span className="text-sm text-chalk-2 font-medium">
                      {topPick.label}{" "}
                      <span className="text-chalk-2 text-xs">
                        ({Math.round(topPick.prob * 100)}%)
                      </span>{" "}
                      @ {topOdds}
                    </span>
                  </div>
                </div>
              )}

              {/* Green — value bet suggestions (up to 2) */}
              {(data.suggested_markets?.length > 0 || data.suggested_market) && (() => {
                const markets = data.suggested_markets?.length > 0
                  ? data.suggested_markets
                  : data.suggested_market ? [data.suggested_market] : [];
                return markets.map((market, idx) => (
                  <div key={market} className="inline-flex items-center gap-2 bg-win/10 border border-win/20 rounded-lg px-3 py-2">
                    <span className="text-win text-xs">💡</span>
                    <div className="flex flex-col leading-tight">
                      <span className="text-[10px] text-win font-semibold uppercase tracking-wide">
                        {idx === 0 ? "Value Bet" : "Alt. Value Bet"}
                      </span>
                      <span className="text-sm text-win font-medium">
                        {market}
                      </span>
                    </div>
                  </div>
                ));
              })()}
            </div>
          );
        })()}

        {/* Watch markets — model edge, not yet a proven suggestion (shadow-tracked) */}
        {data.watch_markets && data.watch_markets.length > 0 && (
          <div className="mt-2 rounded-lg border border-est/20 bg-est/5 px-3 py-2">
            <div className="flex items-center gap-1.5 mb-1.5">
              <span className="text-est text-xs">📈</span>
              <span className="text-[10px] text-est font-semibold uppercase tracking-wide">
                {t("ma.watched")}
              </span>
            </div>
            <div className="flex flex-wrap gap-2">
              {data.watch_markets.map((w) => (
                <span key={w.market} className="inline-flex items-center gap-1.5 text-sm text-est/90">
                  <span className="font-medium">{w.market}</span>
                  {/* EV is return-per-stake; model/market are probabilities. Never mix them. */}
                  <span className="text-est text-xs">
                    (EV {w.ev_pct >= 0 ? "+" : ""}{w.ev_pct.toFixed(0)}%
                    {w.model_pct != null && w.market_pct != null
                      ? t("ma.modelVs", { m: Math.round(w.model_pct), k: Math.round(w.market_pct) })
                      : w.market_pct != null
                        ? t("ma.marketOnly", { k: Math.round(w.market_pct) })
                        : ""})
                  </span>
                </span>
              ))}
            </div>
            <p className="text-[11px] text-chalk-3 mt-1.5 leading-snug">
              {t("ma.watchNote")}
            </p>
          </div>
        )}
      </div>

      {/* Disclaimer */}
      {!isPast && (
        <p className="text-xs text-chalk-3 pt-1">
          ⚠ This is not financial advice. Predictions are for entertainment only.
        </p>
      )}
    </div>

    {/* Bookmaker comparison + goal stats lead. Cards, corners and Elo follow as
        supporting context. Same order on the club and national pages. */}

    {/* Expected cards — team props (club + national), same block both pages. */}
    {(data.exp_home_cards != null || data.exp_away_cards != null) && (
      <div className="card p-5">
        <h2 className="mb-3 font-display text-sm font-extrabold uppercase tracking-[0.14em] text-chalk-3">
          🟨 Expected Cards
        </h2>
        <div className="flex items-center justify-between gap-4">
          <div className="text-left">
            <p className="text-2xl font-bold text-chalk tabular-nums">{data.exp_home_cards?.toFixed(1) ?? "—"}</p>
            <p className="text-xs text-chalk-3">{homeTeam}</p>
          </div>
          <span className="text-xs text-chalk-3 tabular-nums">
            total ≈ {((data.exp_home_cards ?? 0) + (data.exp_away_cards ?? 0)).toFixed(1)}
          </span>
          <div className="text-right">
            <p className="text-2xl font-bold text-chalk tabular-nums">{data.exp_away_cards?.toFixed(1) ?? "—"}</p>
            <p className="text-xs text-chalk-3">{awayTeam}</p>
          </div>
        </div>
      </div>
    )}

    {/* Expected corners — team props (club + national). */}
    {(data.exp_home_corners != null || data.exp_away_corners != null) && (
      <div className="card p-5">
        <h2 className="mb-3 font-display text-sm font-extrabold uppercase tracking-[0.14em] text-chalk-3">
          🚩 Expected Corners
        </h2>
        <div className="flex items-center justify-between gap-4">
          <div className="text-left">
            <p className="text-2xl font-bold text-chalk tabular-nums">{data.exp_home_corners?.toFixed(1) ?? "—"}</p>
            <p className="text-xs text-chalk-3">{homeTeam}</p>
          </div>
          <span className="text-xs text-chalk-3 tabular-nums">
            total ≈ {((data.exp_home_corners ?? 0) + (data.exp_away_corners ?? 0)).toFixed(1)}
          </span>
          <div className="text-right">
            <p className="text-2xl font-bold text-chalk tabular-nums">{data.exp_away_corners?.toFixed(1) ?? "—"}</p>
            <p className="text-xs text-chalk-3">{awayTeam}</p>
          </div>
        </div>
        {data.corners_over_9_5_prob != null && (
          <p className="text-center text-xs text-chalk-3 mt-2">
            Over 9.5 corners: {Math.round(data.corners_over_9_5_prob * 100)}%
          </p>
        )}
      </div>
    )}

    {/* Elo ratings — shown for both club & national once the analysis carries
        them, so both detail pages present the same block. */}
    {(data.h_elo != null || data.a_elo != null) && (
      <div className="card p-5">
        <h2 className="mb-3 font-display text-sm font-extrabold uppercase tracking-[0.14em] text-chalk-3">
          Elo Ratings
        </h2>
        <div className="flex items-center justify-between gap-4">
          <div className="text-left">
            <p className="text-2xl font-bold text-chalk tabular-nums">
              {data.h_elo != null ? Math.round(data.h_elo) : "—"}
            </p>
            <p className="text-xs text-chalk-3">{homeTeam}</p>
          </div>
          <span className="text-xs text-chalk-3">vs</span>
          <div className="text-right">
            <p className="text-2xl font-bold text-chalk tabular-nums">
              {data.a_elo != null ? Math.round(data.a_elo) : "—"}
            </p>
            <p className="text-xs text-chalk-3">{awayTeam}</p>
          </div>
        </div>
      </div>
    )}
   </div>
  );
}
