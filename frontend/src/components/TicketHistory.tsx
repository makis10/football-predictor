"use client";

/**
 * Slips still running — the ones a reader checks daily.
 *
 * This used to list every earlier slip, which does not scale: five a day is
 * ~150 rows a month, and the answer to "how did we do" gets buried under the
 * answer to "what is still live". The full record moved to /tickets/history,
 * paged by week; what stays here is only what has not finished yet.
 *
 * Client component: each row opens the full slip in a modal, which needs state.
 * `t` therefore comes from context, not a prop — a function cannot cross the
 * server/client boundary (React throws at runtime and neither tsc nor the build
 * notices), which `tests/boundary.test.ts` enforces.
 *
 * Compact by design. TicketCard draws one slip in full because it is the offer;
 * here the question is "how did the last two weeks go", so each slip is one row
 * and the legs collapse to a strip of markers. The markers are the same three
 * states TicketCard uses (✓ landed, ✗ missed, • not played yet), so a reader who
 * has looked at today's card already knows how to read this.
 *
 * Open slips are included, not just graded ones. A card is cut with a horizon of
 * up to seven days, so mid-week the settled-only list is empty while several are
 * still live — which reads as "no history" when the truth is "still running".
 */
import {
  Ticket,
  TicketLeg,
  formatDate,
  leagueFlag,
  marketLabel,
} from "@/lib/api";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import TicketCard from "@/components/TicketCard";
import { useT } from "@/components/LanguageProvider";

type TFunc = (k: string, v?: Record<string, string | number>) => string;

/* The same status map TicketCard uses — deliberately duplicated as a constant
   rather than shared, because these are the only two call sites and the pill is
   part of each component's own layout. If a third appears, lift it. */
const STATUS: Record<string, { key: string; cls: string }> = {
  won:  { key: "ticket.status.won",  cls: "bg-win/10 text-win" },
  lost: { key: "ticket.status.lost", cls: "bg-lose/10 text-lose" },
  void: { key: "ticket.status.void", cls: "bg-ink-700 text-chalk-3 line-through" },
};

function statusOf(outcome: Ticket["outcome"]) {
  return (
    STATUS[outcome ?? ""] ?? { key: "ticket.status.open", cls: "bg-ink-700 text-chalk-3" }
  );
}

/** One marker per leg: ✓ landed · ✗ missed · • not played yet. */
function LegMarkers({ legs, t }: { legs: TicketLeg[]; t: TFunc }) {
  return (
    <span className="flex flex-wrap items-center gap-1">
      {legs.map((leg, i) => {
        const settled = leg.won !== null;
        return (
          <span
            key={`${leg.match_id}-${leg.market}-${i}`}
            /* The market and score live in the title so a curious reader can
               check a single leg without us printing forty rows. */
            title={`${leagueFlag(leg.league)} ${leg.home_team} v ${leg.away_team} · ${marketLabel(
              leg.market,
              leg.home_team,
              leg.away_team,
              t,
            )} @ ${leg.odds.toFixed(2)}${
              leg.home_goals !== null && leg.away_goals !== null
                ? ` · ${leg.home_goals}-${leg.away_goals}`
                : ""
            }`}
            className={`font-data text-xs font-bold leading-none ${
              !settled ? "text-chalk-3" : leg.won ? "text-win" : "text-lose"
            }`}
          >
            {!settled ? "•" : leg.won ? "✓" : "✗"}
          </span>
        );
      })}
    </span>
  );
}

function SlipRow({
  ticket,
  t,
  onOpen,
}: {
  ticket: Ticket;
  t: TFunc;
  onOpen: () => void;
}) {
  const status = statusOf(ticket.outcome);
  const landed = ticket.legs.filter((l) => l.won === true).length;
  const pending = ticket.legs.filter((l) => l.won === null).length;

  return (
    <li>
      {/* A real <button>, not a click handler on the <li>: the row is the
          control, so it has to be reachable by keyboard and announced as one.
          The dead-slip note below sits outside it — it is a statement about the
          row, not part of the thing you press. */}
      <button
        type="button"
        onClick={onOpen}
        className="flex w-full flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg px-2 py-2.5
                   text-left transition-colors hover:bg-ink-700/60
                   focus-visible:outline focus-visible:outline-2 focus-visible:outline-chalk-2"
        aria-label={t("tickets.history.open", {
          profile: t(`tickets.profile.${ticket.profile}`),
          date: formatDate(ticket.generated_for),
        })}
      >
      <span className="w-[4.5rem] shrink-0 text-[11px] text-chalk-3">
        {formatDate(ticket.generated_for)}
      </span>

      <span className="w-24 shrink-0 truncate text-sm text-chalk">
        {t(`tickets.profile.${ticket.profile}`)}
      </span>

      <LegMarkers legs={ticket.legs} t={t} />

      <span className="ml-auto flex items-center gap-3">
        <span className="text-[11px] text-chalk-3 tabular-nums">
          {t("tickets.history.progress", {
            landed,
            total: ticket.num_legs,
          })}
        </span>
        <span className="font-data w-14 text-right text-sm font-bold text-chalk">
          {ticket.total_odds.toFixed(2)}
        </span>
        <span
          className={`shrink-0 rounded px-2 py-0.5 text-[10px] font-bold tracking-wider ${status.cls}`}
        >
          {t(status.key)}
        </span>
      </span>

      </button>

      {/* Only for a slip that is still open but already mathematically dead:
          one missed leg kills an accumulator, so saying nothing here would let
          a reader keep hoping for a return that cannot arrive. The backend
          still reports it as open — it grades only when every leg is played —
          so this is worded as a fact about the legs, not a result. */}
      {ticket.outcome === null && pending > 0 &&
        ticket.legs.some((l) => l.won === false) && (
          <p className="w-full pl-[4.5rem] pb-1.5 text-[11px] text-lose/80">
            {t("tickets.history.dead")}
          </p>
        )}
    </li>
  );
}


/** The picked slip, drawn in full by the same component the live card uses. */
function SlipModal({
  ticket,
  t,
  onClose,
}: {
  ticket: Ticket;
  t: TFunc;
  onClose: () => void;
}) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    // Stop the page behind from scrolling under the overlay.
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  if (!mounted) return null;

  return createPortal(
    // Portalled to <body> for the same reason NotificationBell is: the sticky
    // header has backdrop-blur, and a backdrop-filter ancestor becomes the
    // containing block for position:fixed — the overlay would be pinned inside
    // the 56px header instead of the viewport.
    <div
      className="z-[100] flex items-center justify-center p-4"
      style={{ position: "fixed", top: 0, right: 0, bottom: 0, left: 0 }}
      role="dialog"
      aria-modal="true"
    >
      <div className="absolute inset-0 bg-scrim backdrop-blur-sm" onClick={onClose} />
      <div
        className="relative z-10 w-full max-w-lg rounded-2xl border border-line bg-ink-800 shadow-2xl"
        style={{ display: "flex", flexDirection: "column", maxHeight: "85vh" }}
      >
        <div
          className="flex items-start justify-between gap-3 border-b border-line px-5 py-4"
          style={{ flexShrink: 0 }}
        >
          <div>
            <p className="text-base font-semibold text-chalk">
              {t("tickets.history.modalTitle")}
            </p>
            <p className="text-xs text-chalk-3">
              {t("tickets.generatedFor", { date: formatDate(ticket.generated_for) })}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("bell.close")}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-chalk-2
                       transition-colors hover:bg-ink-700 hover:text-chalk"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M18 6 6 18" /><path d="m6 6 12 12" />
            </svg>
          </button>
        </div>
        <div className="p-4" style={{ flex: "1 1 auto", minHeight: 0, overflowY: "auto" }}>
          {/* The live card, unchanged. Reused rather than re-laid-out so the
              receipts can never drift from what was published. */}
          <TicketCard ticket={ticket} />
        </div>
      </div>
    </div>,
    document.body,
  );
}

export default function TicketHistory({ tickets }: { tickets: Ticket[] }) {
  const t = useT();
  const [openId, setOpenId] = useState<number | null>(null);

  // Open only. A finished slip belongs in the record, not in a "still running"
  // list — and void slips are finished too, just unresolvably.
  const live = tickets.filter((x) => x.outcome === null);
  if (live.length === 0) return null;
  const opened = live.find((x) => x.id === openId) ?? null;

  // A slip with a missed leg cannot return any more, even though the backend
  // rightly keeps it open until every leg is played. Worth counting separately:
  // "6 running" reads very differently from "6 running, 2 already dead".
  const dead = live.filter((x) => x.legs.some((l) => l.won === false)).length;

  return (
    /* scroll-mt clears the 56px sticky header when the nav deep-links here. */
    <section id="history" className="card scroll-mt-20 p-5">
      <div className="mb-1 flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-chalk-2">
          {t("tickets.history.title")}
        </h2>
        <span className="text-[11px] text-chalk-3 tabular-nums">
          {t("tickets.history.openCount", { open: live.length, dead })}
        </span>
      </div>
      <p className="mb-3 text-xs text-chalk-3">{t("tickets.history.body")}</p>

      {/* Flat list, newest first — the API already orders it, and every row
          carries its own date, so grouping by day would only add chrome. */}
      <ul className="divide-y divide-line-soft/70">
        {live.map((ticket) => (
          <SlipRow
            key={ticket.id}
            ticket={ticket}
            t={t}
            onOpen={() => setOpenId(ticket.id)}
          />
        ))}
      </ul>

      {opened && (
        <SlipModal ticket={opened} t={t} onClose={() => setOpenId(null)} />
      )}

      <div className="mt-3 flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-[11px] leading-snug text-chalk-3">
          {t("tickets.history.legend")}
        </p>
        <Link
          href="/tickets/history"
          className="text-[11px] text-chalk-2 underline underline-offset-2 transition-colors hover:text-chalk"
        >
          {t("tickets.history.seeAll")} →
        </Link>
      </div>
    </section>
  );
}
