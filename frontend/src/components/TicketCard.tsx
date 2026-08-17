"use client";

/**
 * One suggested accumulator, drawn as a betting slip.
 *
 * Client component, and `t` comes from context rather than a prop. It has to
 * be: TicketHistory opens a slip in a modal, and a server component cannot be
 * rendered inside a client one. The alternative was a second full-slip layout
 * living in the modal — the "same concept implemented twice with nothing
 * asserting they agree" shape this codebase has been bitten by before.
 *
 * The three footer numbers are deliberately shown together: a payout with no
 * probability beside it is the thing that makes accumulators look better than
 * they are.
 */
import Link from "next/link";
import {
  Ticket,
  TicketLeg,
  formatDate,
  formatKickoff,
  leagueFlag,
  leagueLabel,
  marketLabel,
  matchHref,
} from "@/lib/api";
import { useT } from "@/components/LanguageProvider";

/* Risk rung, 1 (steadiest) to 5 (wildest).
   NOT expressed as a hue. In this system green means "it landed" and amber
   means "our own estimate"; tinting the banker green would state a result that
   has not happened, and tinting the long shot amber would claim its price is
   made up. Risk is its own axis, so it gets its own device — a rung meter —
   which also says more than a colour could: five discrete steps, ordered. */
const PROFILE_RUNG: Record<string, number> = {
  safe: 1,
  treble: 2,
  fourfold: 3,
  fivefold: 4,
  longshot: 5,
};

function RungMeter({ rung }: { rung: number }) {
  return (
    <span className="flex shrink-0 items-center gap-[3px]" aria-hidden>
      {[1, 2, 3, 4, 5].map((i) => (
        <span
          key={i}
          className={`h-1 w-2.5 rounded-[1px] ${
            i <= rung ? "bg-chalk-2" : "bg-ink-600"
          }`}
        />
      ))}
    </span>
  );
}

function LegRow({ leg, t }: { leg: TicketLeg; t: (k: string, v?: Record<string, string | number>) => string }) {
  const kickoff = formatKickoff(leg.match_date, leg.kickoff_time);
  const settled = leg.won !== null;
  const score =
    leg.home_goals !== null && leg.away_goals !== null
      ? `${leg.home_goals}-${leg.away_goals}`
      : null;

  return (
    <li className="flex items-start gap-3 py-2">
      {/* Result marker — only once the match has actually finished */}
      <span
        className={`mt-0.5 w-4 shrink-0 text-center text-xs font-bold ${
          !settled ? "text-chalk-3" : leg.won ? "text-win" : "text-lose"
        }`}
        aria-hidden
      >
        {!settled ? "•" : leg.won ? "✓" : "✗"}
      </span>

      <div className="min-w-0 flex-1">
        <p className="text-[11px] text-chalk-3 flex items-center gap-1.5">
          <span>{leagueFlag(leg.league)}</span>
          <span className="truncate">{leagueLabel(leg.league)}</span>
          <span className="text-chalk-3">·</span>
          <span className="whitespace-nowrap">{formatDate(leg.match_date)}</span>
          {kickoff && <span className="text-chalk-3">{kickoff}</span>}
          {score && <span className="ml-auto font-data text-chalk-2">{score}</span>}
        </p>

        <Link
          /* matchHref, not a hardcoded /matches/ — national fixtures live at
             /national/{id} and this would 404 on them. It reads as safe today
             only because the international calendar is empty; it would have
             broken the moment qualifiers resume. */
          href={matchHref({ id: leg.match_id, league: leg.league } as Parameters<typeof matchHref>[0])}
          className="block text-sm text-chalk hover:text-win transition-colors truncate"
        >
          {leg.home_team} <span className="text-chalk-3">v</span> {leg.away_team}
        </Link>

        <p className="text-[13px] font-medium text-chalk-2">
          {marketLabel(leg.market, leg.home_team, leg.away_team, t)}
          <span className="ml-2 text-[11px] font-normal text-chalk-3">
            {Math.round(leg.prob * 100)}%
          </span>
        </p>
      </div>

      <div className="shrink-0 text-right">
        <p className="font-data text-sm font-bold text-chalk tabular-nums">
          {leg.odds.toFixed(2)}
        </p>
        {leg.estimated && (
          <p className="text-[10px] text-est/80 whitespace-nowrap">
            ≈ {t("tickets.legend.estimated")}
          </p>
        )}
      </div>
    </li>
  );
}

export default function TicketCard({ ticket }: { ticket: Ticket }) {
  const t = useT();
  const rung = PROFILE_RUNG[ticket.profile] ?? 3;
  const estimated = ticket.legs.filter((l) => l.estimated).length;

  // "void" = a fixture on the slip was deleted after it was cut, so it can
  // never be graded honestly. Shown, not hidden, and kept out of the record.
  const STATUS: Record<string, { key: string; cls: string }> = {
    won:  { key: "ticket.status.won",  cls: "bg-win/10 text-win" },
    lost: { key: "ticket.status.lost", cls: "bg-lose/10 text-lose" },
    void: { key: "ticket.status.void", cls: "bg-ink-700 text-chalk-3 line-through" },
  };
  const status = STATUS[ticket.outcome ?? ""] ?? {
    key: "ticket.status.open",
    cls: "bg-ink-700 text-chalk-3",
  };
  const statusLabel = t(status.key);
  const statusClass = status.cls;

  return (
    <article className="card flex flex-col">
      {/* Slip header */}
      <header className="px-4 pt-4 pb-3">
        <div className="flex items-start gap-2">
          <div className="min-w-0">
            <h3 className="font-display text-base font-extrabold text-chalk">
              {t(`tickets.profile.${ticket.profile}`)}
            </h3>
            <p className="text-[11px] text-chalk-3">
              {t(`tickets.profile.${ticket.profile}.desc`)}
            </p>
          </div>
          <span
            className={`ml-auto shrink-0 rounded px-2 py-0.5 text-[10px] font-bold tracking-wider ${statusClass}`}
          >
            {statusLabel}
          </span>
        </div>
        <div className="mt-1.5 flex items-center gap-2">
          <RungMeter rung={rung} />
          <p className="text-[11px] text-chalk-3">
            {t(ticket.num_legs === 1 ? "ticket.legs.one" : "ticket.legs.many",
               { n: ticket.num_legs })}
          </p>
        </div>
      </header>

      {/* Perforation */}
      <div className="border-t border-dashed border-line" />

      <ul className="px-4 divide-y divide-line-soft/70 flex-1">
        {ticket.legs.map((leg) => (
          <LegRow key={`${ticket.id}-${leg.match_id}-${leg.market}`} leg={leg} t={t} />
        ))}
      </ul>

      <div className="border-t border-dashed border-line" />

      {/* Slip footer — payout NEVER without the probability next to it */}
      <footer className="px-4 py-3 grid grid-cols-3 gap-2 text-center">
        <div>
          <p className="text-[10px] uppercase tracking-wide text-chalk-3">
            {t("ticket.totalOdds")}
          </p>
          <p className="font-data text-lg font-bold text-chalk tabular-nums">
            {ticket.total_odds.toFixed(2)}
          </p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wide text-chalk-3">
            {t("ticket.winProb")}
          </p>
          <p className="font-data text-lg font-bold text-chalk tabular-nums">
            {(ticket.combined_prob * 100).toFixed(1)}%
          </p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wide text-chalk-3">
            {t("ticket.returns")}
          </p>
          <p className="font-data text-lg font-bold text-chalk tabular-nums">
            €{(ticket.total_odds * 10).toFixed(2)}
          </p>
        </div>
      </footer>

      {estimated > 0 && (
        <p className="px-4 pb-3 text-[11px] leading-snug text-est/80">
          {t(estimated === 1
               ? "tickets.estimated.note.one"
               : "tickets.estimated.note.many", { n: estimated })}
        </p>
      )}
    </article>
  );
}
