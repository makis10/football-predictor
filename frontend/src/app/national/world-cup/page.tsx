export const dynamic = "force-dynamic";

import Link from "next/link";
import { getWcSimulation, getWcChampionHistory, type WcSimulation, type WcChampionHistory } from "@/lib/api";
import { WcChampionHistoryChart } from "@/components/national/WcChampionHistoryChart";

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${(v * 100).toFixed(1)}%`;
}

function EdgeBadge({ model, market }: { model: number; market: number | null }) {
  if (market == null) return <span className="text-gray-600">—</span>;
  const edge = model - market;
  const cls =
    edge > 0.02 ? "text-amber-400" : edge < -0.02 ? "text-sky-400" : "text-gray-400";
  return (
    <span className={`tabular-nums ${cls}`}>
      {edge >= 0 ? "+" : ""}
      {(edge * 100).toFixed(1)}%
    </span>
  );
}

export default async function WorldCupPage() {
  let sim: WcSimulation = { available: false };
  let history: WcChampionHistory = { available: false, snapshots: [] };
  try {
    [sim, history] = await Promise.all([
      getWcSimulation(),
      getWcChampionHistory().catch(() => ({ available: false, snapshots: [] })),
    ]);
  } catch {
    /* fall through to unavailable state */
  }

  if (!sim.available || !sim.teams?.length) {
    return (
      <div className="space-y-6">
        <Header />
        <div className="text-center py-16 text-gray-500">
          <p className="text-4xl mb-3">🎲</p>
          <p className="font-medium">No simulation available yet.</p>
          <p className="text-sm mt-1 font-mono text-xs">
            docker compose exec backend python scripts/simulate_wc.py --save-json
          </p>
        </div>
      </div>
    );
  }

  const generated = sim.generated_at
    ? new Date(sim.generated_at).toLocaleString("en-GB", {
        timeZone: "Europe/Athens",
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";

  const maxWin = Math.max(...sim.teams.map((t) => t.win_pct));

  return (
    <div className="space-y-6">
      <Header />

      <p className="text-sm text-gray-500">
        {sim.n_sims?.toLocaleString()} Monte Carlo simulations · generated {generated}
        {sim.has_market && " · compared with the bookmaker World Cup Winner market"}
      </p>
      {sim.played_games ? (
        <p className="text-xs text-emerald-400/80">
          ✓ Conditioned on {sim.played_games} real result{sim.played_games === 1 ? "" : "s"} so far
          {sim.remaining_games != null && ` · ${sim.remaining_games} group games remaining`}
        </p>
      ) : null}

      {/* Winner probabilities */}
      <section className="card p-5">
        <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-4">
          🏆 Champion probability
        </h2>
        <div className="space-y-1.5">
          <div className="grid grid-cols-[1.6rem_1fr_4rem_4rem_4rem] gap-2 text-[11px] text-gray-500 uppercase tracking-wide pb-1">
            <span />
            <span>Team</span>
            <span className="text-right">Win</span>
            <span className="text-right">Final</span>
            <span className="text-right">Market</span>
          </div>
          {sim.teams.slice(0, 16).map((t, i) => (
            <div
              key={t.team}
              className="grid grid-cols-[1.6rem_1fr_4rem_4rem_4rem] gap-2 items-center text-sm"
            >
              <span className="text-xs text-gray-600 tabular-nums">{i + 1}</span>
              <div className="relative">
                <div
                  className="absolute inset-y-0 left-0 bg-green-500/10 rounded"
                  style={{ width: `${(t.win_pct / maxWin) * 100}%` }}
                />
                <span className="relative font-medium text-gray-100">{t.team}</span>
              </div>
              <span className="text-right tabular-nums text-green-400 font-semibold">
                {pct(t.win_pct)}
              </span>
              <span className="text-right tabular-nums text-gray-400">{pct(t.final_pct)}</span>
              <span className="text-right tabular-nums text-gray-500">{pct(t.market_pct)}</span>
            </div>
          ))}
        </div>
      </section>

      {/* Champion odds over time */}
      {history.available && history.snapshots.length >= 2 && (
        <section className="card p-5">
          <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-4">
            📉 Champion odds — trend
          </h2>
          <WcChampionHistoryChart snapshots={history.snapshots} />
        </section>
      )}

      {/* Model vs market edge */}
      {sim.has_market && (
        <section className="card p-5">
          <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-1">
            ⚖️ Our model vs sharp market
          </h2>
          <p className="text-xs text-gray-500 mb-4">
            Edge = model − market.{" "}
            <span className="text-amber-400">Amber</span> = we over-rate vs sharps,{" "}
            <span className="text-sky-400">blue</span> = we under-rate. The market is the
            sharper baseline.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-1.5">
            {sim.teams.slice(0, 12).map((t) => (
              <div key={t.team} className="flex items-center justify-between text-sm">
                <span className="text-gray-200">{t.team}</span>
                <span className="flex items-center gap-3 tabular-nums">
                  <span className="text-green-400">{pct(t.win_pct)}</span>
                  <span className="text-gray-500">{pct(t.market_pct)}</span>
                  <EdgeBadge model={t.win_pct} market={t.market_pct} />
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Group standings — qualification probabilities */}
      {sim.group_standings && Object.keys(sim.group_standings).length > 0 && (
        <section className="card p-5">
          <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-1">
            📊 Πρόκριση Ομίλων
          </h2>
          <p className="text-xs text-gray-500 mb-4">
            <span className="text-gray-300">1ος</span> = πρώτη θέση ομίλου ·{" "}
            <span className="text-gray-300">Top-2</span> = απευθείας πρόκριση ·{" "}
            <span className="text-gray-300">Πρόκριση</span> = top-2 ή ένας από τους 8 καλύτερους 3ους.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-5">
            {Object.entries(sim.group_standings).map(([letter, teams]) => (
              <div key={letter} className="space-y-1">
                <div className="grid grid-cols-[1fr_2.4rem_2.4rem_2.6rem] gap-1 text-[10px] text-gray-500 uppercase tracking-wide pb-0.5 border-b border-pitch-700">
                  <span>Group {letter}</span>
                  <span className="text-right">1ος</span>
                  <span className="text-right">Top2</span>
                  <span className="text-right">Πρόκρ</span>
                </div>
                {teams.map((t) => (
                  <div key={t.team} className="grid grid-cols-[1fr_2.4rem_2.4rem_2.6rem] gap-1 items-center text-xs">
                    <span className="text-gray-200 truncate">{t.team}</span>
                    <span className="text-right tabular-nums text-gray-400">{Math.round(t.p_first * 100)}%</span>
                    <span className="text-right tabular-nums text-gray-300">{Math.round(t.p_top2 * 100)}%</span>
                    <span className="text-right tabular-nums text-green-400 font-semibold">{Math.round(t.p_qualify * 100)}%</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Most-likely final pairings */}
      <section className="card p-5">
        <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-1">
          🥇 Most-likely final pairing
        </h2>
        <p className="text-xs text-gray-500 mb-4">
          Even the top pairing is a long shot — the exact two finalists can&apos;t be
          predicted with confidence.
        </p>
        <div className="space-y-1.5">
          {sim.pairings?.slice(0, 8).map((p) => (
            <div
              key={`${p.team_a}-${p.team_b}`}
              className="flex items-center justify-between text-sm"
            >
              <span className="text-gray-200">
                {p.team_a} <span className="text-gray-600">vs</span> {p.team_b}
              </span>
              <span className="tabular-nums text-gray-400">{pct(p.pct)}</span>
            </div>
          ))}
        </div>
      </section>

      {/* Golden Boot — top scorer probabilities */}
      {sim.golden_boot?.players?.length ? (
        <section className="card p-5">
          <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-1">
            👟 Golden Boot — top scorer
          </h2>
          <p className="text-xs text-gray-500 mb-4">
            Each simulated goal is assigned to a player by his recency-weighted share of
            his nation&apos;s goals. Going deep in the bracket matters as much as scoring
            rate — that&apos;s why favourites&apos; strikers dominate.
          </p>
          {(() => {
            const gbHasMarket = !!sim.golden_boot?.has_market;
            const cols = gbHasMarket
              ? "grid-cols-[1.6rem_1fr_4rem_4rem_4rem]"
              : "grid-cols-[1.6rem_1fr_4rem_4rem_4rem]";
            const players = sim.golden_boot!.players.slice(0, 15);
            const maxGb = Math.max(...players.map((p) => p.gb_pct));
            return (
              <div className="space-y-1.5">
                <div className={`grid ${cols} gap-2 text-[11px] text-gray-500 uppercase tracking-wide pb-1`}>
                  <span />
                  <span>Player</span>
                  <span className="text-right">GB</span>
                  {gbHasMarket ? (
                    <>
                      <span className="text-right">Market</span>
                      <span className="text-right">Edge</span>
                    </>
                  ) : (
                    <>
                      <span className="text-right">xGoals</span>
                      <span className="text-right">P(4+)</span>
                    </>
                  )}
                </div>
                {players.map((p, i) => (
                  <div
                    key={`${p.player}-${p.team}`}
                    className={`grid ${cols} gap-2 items-center text-sm`}
                  >
                    <span className="text-xs text-gray-600 tabular-nums">{i + 1}</span>
                    <div className="relative">
                      <div
                        className="absolute inset-y-0 left-0 bg-amber-500/10 rounded"
                        style={{ width: `${maxGb > 0 ? (p.gb_pct / maxGb) * 100 : 0}%` }}
                      />
                      <span className="relative font-medium text-gray-100">
                        {p.player}{" "}
                        <span className="text-xs text-gray-500">({p.team})</span>
                      </span>
                    </div>
                    <span className="text-right tabular-nums text-amber-400 font-semibold">
                      {pct(p.gb_pct)}
                    </span>
                    {gbHasMarket ? (
                      <>
                        <span className="text-right tabular-nums text-gray-500">
                          {pct(p.market_pct ?? null)}
                        </span>
                        <span className="text-right tabular-nums">
                          <EdgeBadge model={p.gb_pct} market={p.market_pct ?? null} />
                        </span>
                      </>
                    ) : (
                      <>
                        <span className="text-right tabular-nums text-gray-400">
                          {p.exp_goals.toFixed(1)}
                        </span>
                        <span className="text-right tabular-nums text-gray-500">{pct(p.p4plus)}</span>
                      </>
                    )}
                  </div>
                ))}
              </div>
            );
          })()}
          {sim.golden_boot.field_pct > 0 && (
            <p className="text-xs text-gray-600 mt-3">
              — field (any unlisted player): {pct(sim.golden_boot.field_pct)}
            </p>
          )}
        </section>
      ) : null}

      {/* Caveats */}
      <section className="text-xs text-gray-600 space-y-1 border-t border-pitch-700 pt-4">
        <p>
          ⚠ Elo-Poisson engine calibrated to our trained result model. Bracket
          group-letter assignment is approximate (fixtures carry no group label), so exact
          knockout paths are indicative. Knockout draws resolved via Elo-weighted penalties.
        </p>
        <p>
          ⚠ Golden Boot shares come from international scoring history (martj42
          goalscorers).{" "}
          {sim.golden_boot?.squad_filtered
            ? "Restricted to officially called-up players (API-Football squads)."
            : "Not filtered by announced squads — an unselected player still carries his historical share."}{" "}
          {sim.golden_boot?.availability_filtered
            ? `Injured/suspended players are excluded (${sim.golden_boot.unavailable_count ?? 0} flagged via API-Football /injuries; refreshed daily).`
            : "Injuries/suspensions not yet applied."}{" "}
          Penalty-takers are implicitly favoured.
        </p>
        <p>Re-run nightly. Winner is a probability distribution, not a single pick.</p>
      </section>
    </div>
  );
}

function Header() {
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white">
          World Cup 2026 — Simulation
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          Monte Carlo tournament projection: champion & finalist probabilities.
        </p>
      </div>
      <div className="shrink-0 flex items-center gap-3 mt-1">
        <Link
          href="/national/world-cup/review"
          className="text-sm text-amber-400 hover:text-amber-300 whitespace-nowrap"
        >
          Review →
        </Link>
        <Link
          href="/"
          className="text-sm text-gray-400 hover:text-white whitespace-nowrap"
        >
          ← Upcoming
        </Link>
      </div>
    </div>
  );
}
