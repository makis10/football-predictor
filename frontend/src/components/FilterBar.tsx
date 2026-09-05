"use client";

/**
 * One filter control, replacing three stacked rows of buttons.
 *
 * The measurement that forced this: the old bar rendered 42 buttons — 27 league
 * chips, 6 odds chips, 3 confidence chips — before a single fixture. On desktop
 * the first match started at 87% of the viewport height; on a phone it started
 * 1524px down, so the reader scrolled almost a full screen of controls to reach
 * the content they came for. Filters should cost a tap, not a screen.
 *
 * Two changes do the work:
 *   1. Only leagues that ACTUALLY have fixtures in the current window get a
 *      chip, ordered by how many, with the count shown. On a normal midweek
 *      that is 6–8 chips instead of 27, and the counts answer "is there
 *      anything on tonight" without opening anything.
 *   2. Odds and confidence move into a popover. They are refinements — a reader
 *      reaches for them after seeing the card, not before.
 *
 * The full league list stays reachable behind "+N", so nothing is hidden, only
 * deferred. A league with no fixtures still appears there and simply returns an
 * empty day, which is the honest answer.
 *
 * 2026-09-05: "+N" used to sit at the END of the chip strip — inside the
 * `overflow-x-auto` element. Eight chips already overflow a desktop viewport, so
 * the one control that reveals the other twenty-one leagues was itself scrolled
 * off the right edge and never rendered visibly. The list was not deferred, it
 * was unreachable: a reader looking for the Greek league (8 fixtures that day,
 * ranked 9th, one place past the cut) had no way to learn the drawer existed.
 * It is now pinned outside the strip next to Filters, where it cannot scroll
 * away, and the drawer carries counts so the reader can see what is on there.
 */
import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { INTERNATIONAL_LEAGUE, LEAGUES } from "@/lib/api";
import { useT } from "@/components/LanguageProvider";

const ODDS_OPTIONS = [
  { key: "any", value: null as number | null },
  { key: "1.50", value: 1.5 },
  { key: "1.70", value: 1.7 },
  { key: "1.90", value: 1.9 },
  { key: "2.20", value: 2.2 },
  { key: "2.50", value: 2.5 },
];

const CONF_OPTIONS = [
  { key: "any", value: null as string | null },
  { key: "high", value: "high" },
  { key: "medium", value: "medium" },
];

export interface LeagueCount {
  code: string;
  count: number;
}

export default function FilterBar({
  activeLeague,
  activeOdds,
  activeConfidence,
  counts,
  basePath = "/",
  showRefine: refineEnabled = true,
}: {
  activeLeague?: string;
  activeOdds?: number;
  activeConfidence?: string;
  /** Leagues present in the current window, with fixture counts. Pass [] on
      pages that have no cheap way to count — the bar then shows "All" plus the
      full-list drawer, which still beats printing 28 chips. */
  counts: LeagueCount[];
  basePath?: string;
  /** Odds/confidence only apply to the fixture list. /stats and /recent ignore
      those params, so offering them there would be a control that does nothing. */
  showRefine?: boolean;
}) {
  // `t` is read from context, NOT passed as a prop: this is a client component,
  // and a function cannot cross the server/client boundary — React rejects it at
  // runtime ("Functions cannot be passed directly to Client Components"), which
  // TypeScript cannot see. Server components pass resolved STRINGS (see SiteNav);
  // client components use the hook.
  const t = useT();
  const router = useRouter();
  const params = useSearchParams();
  const [showAll, setShowAll] = useState(false);
  const [showRefine, setShowRefine] = useState(false);
  const refineRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!showRefine) return;
    const onDown = (e: MouseEvent) => {
      if (!refineRef.current?.contains(e.target as Node)) setShowRefine(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setShowRefine(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [showRefine]);

  function push(mutate: (p: URLSearchParams) => void) {
    const next = new URLSearchParams(params.toString());
    next.delete("page"); // reset pagination on any filter change
    mutate(next);
    const qs = next.toString();
    router.push(qs ? `${basePath}?${qs}` : basePath);
  }

  const setLeague = (code?: string) =>
    push((p) => (code ? p.set("league", code) : p.delete("league")));
  const setOdds = (v: number | null) =>
    push((p) => (v != null ? p.set("min_odds", String(v)) : p.delete("min_odds")));
  const setConf = (v: string | null) =>
    push((p) => (v != null ? p.set("min_confidence", v) : p.delete("min_confidence")));

  const isLeague = (code: string) =>
    activeLeague?.toLowerCase() === code.toLowerCase();

  const chip = (on: boolean) =>
    [
      "shrink-0 rounded-lg px-3 py-1.5 text-sm transition-colors whitespace-nowrap",
      on
        ? "bg-chalk text-ink-900 font-semibold"
        : "bg-ink-700 text-chalk-2 hover:bg-ink-600 hover:text-chalk",
    ].join(" ");

  const label = (code: string) => {
    if (code === INTERNATIONAL_LEAGUE) return "🌍 " + t("league.international");
    const l = LEAGUES.find((x) => x.code === code);
    return l ? `${l.flag} ${l.label}` : code;
  };

  const total = counts.reduce((s, c) => s + c.count, 0);
  // /stats and /recent have no cheap way to count and pass []. Printing "0" next
  // to every chip there states something we did not measure — and states it
  // wrongly, since those pages plainly have data. A count is shown only where one
  // was taken; on the fixture list a real 0 still means "nothing on".
  const counted = counts.length > 0;
  const countByCode = new Map(counts.map((c) => [c.code, c.count]));
  const allCodes = [...LEAGUES.map((l) => l.code as string), INTERNATIONAL_LEAGUE];

  // The URL carries whatever the reader typed (?league=greeksl); the chip needs
  // the canonical code so label() can find its flag and name.
  const activeCode = activeLeague
    ? allCodes.find((c) => c.toLowerCase() === activeLeague.toLowerCase()) ?? activeLeague
    : undefined;

  // A league picked from the drawer has to stay visible in the bar — and visible
  // means FIRST. Appended after the eight busiest it lands past the right edge of
  // a strip that already overflows, so the active filter cannot be seen and a
  // short filtered list reads as a bug. It takes the eighth chip's place rather
  // than making the strip wider.
  const top = counts.slice(0, 8);
  const shown =
    activeCode && !top.some((c) => isLeague(c.code))
      ? [{ code: activeCode, count: countByCode.get(activeCode) ?? 0 }, ...top.slice(0, 7)]
      : top;

  const restCount = allCodes.length - shown.length;

  // The drawer used to list leagues in declaration order, so a reader opening it
  // to find tonight's Greek fixtures scanned past twenty codes, most of them
  // empty, with nothing saying which had matches. Order it the way the chips are
  // ordered — by how much is on — and print the count, so the drawer answers the
  // same question the bar does instead of being a flat directory.
  const drawerCodes = [...allCodes].sort(
    (a, b) => (countByCode.get(b) ?? 0) - (countByCode.get(a) ?? 0) || a.localeCompare(b),
  );

  const refineActive = activeOdds != null || activeConfidence != null;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        {/* Only the CHIPS scroll. The Filters control must stay outside this
            element: `overflow-x: auto` forces `overflow-y` to compute to `auto`
            as well (CSS cannot clip one axis and leave the other visible), so an
            absolutely-positioned popover inside it is clipped to the strip's
            38px height and never appears. It also keeps the control pinned to
            the right instead of scrolling away with the chips. */}
        <div className="flex min-w-0 flex-1 items-center gap-2 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <button onClick={() => setLeague(undefined)} className={chip(!activeLeague)}>
          {t("filter.all")}
          {counted && (
            <span className="ml-1.5 font-data text-[11px] opacity-60">{total}</span>
          )}
        </button>

        {shown.map((c) => (
          <button key={c.code} onClick={() => setLeague(c.code)} className={chip(isLeague(c.code))}>
            {label(c.code)}
            {counted && (
              <span className="ml-1.5 font-data text-[11px] opacity-60">{c.count}</span>
            )}
          </button>
        ))}

        </div>

        {restCount > 0 && (
          <button
            onClick={() => setShowAll((v) => !v)}
            aria-expanded={showAll}
            className={[
              "shrink-0 whitespace-nowrap rounded-lg border border-dashed px-3 py-1.5",
              "text-sm transition-colors",
              showAll
                ? "border-chalk-3 text-chalk"
                : "border-line text-chalk-3 hover:text-chalk-2",
            ].join(" ")}
          >
            {/* Two pinned controls on a 375px phone leave barely one chip visible,
                and the chips carry the counts. The word is dropped below `sm` —
                "+20" is as clear as "+20 leagues" next to a dashed border, and
                gives ~60px back to the strip. */}
            <span className="sm:hidden">{showAll ? "\u2715" : `+${restCount}`}</span>
            <span className="hidden sm:inline">
              {showAll ? t("filter.less") : t("filter.more", { n: restCount })}
            </span>
          </button>
        )}

        {refineEnabled && (
        <div className="relative shrink-0" ref={refineRef}>
          <button
            onClick={() => setShowRefine((v) => !v)}
            aria-expanded={showRefine}
            className={chip(refineActive)}
          >
            {t("filter.refine")} ▾
          </button>

          {showRefine && (
            <div className="card card-flat absolute right-0 top-full z-30 mt-1 w-64 space-y-3 p-3">
              <div>
                <p className="mb-1.5 text-[11px] uppercase tracking-wider text-chalk-3">
                  {t("filter.minOdds")}
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {ODDS_OPTIONS.map((o) => (
                    <button
                      key={o.key}
                      onClick={() => setOdds(o.value)}
                      className={`rounded-md px-2 py-1 text-xs transition-colors ${
                        activeOdds === (o.value ?? undefined) ||
                        (o.value === null && activeOdds == null)
                          ? "bg-chalk text-ink-900 font-semibold"
                          : "bg-ink-700 text-chalk-2 hover:text-chalk"
                      }`}
                    >
                      {o.value === null ? t("filter.anyOdds") : `${o.key}+`}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <p className="mb-1.5 text-[11px] uppercase tracking-wider text-chalk-3">
                  {t("filter.confidence")}
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {CONF_OPTIONS.map((o) => (
                    <button
                      key={o.key}
                      onClick={() => setConf(o.value)}
                      className={`rounded-md px-2 py-1 text-xs transition-colors ${
                        (activeConfidence ?? null) === o.value
                          ? "bg-chalk text-ink-900 font-semibold"
                          : "bg-ink-700 text-chalk-2 hover:text-chalk"
                      }`}
                    >
                      {t(`filter.conf.${o.key}`)}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
        )}
      </div>

      {showAll && (
        <div className="card card-flat flex flex-wrap gap-1.5 p-3">
          {drawerCodes.map((code) => {
            const n = countByCode.get(code) ?? 0;
            return (
              <button
                key={code}
                onClick={() => {
                  setLeague(code);
                  setShowAll(false);
                }}
                className={`rounded-md px-2 py-1 text-xs transition-colors ${
                  isLeague(code)
                    ? "bg-chalk font-semibold text-ink-900"
                    : n > 0
                      ? "bg-ink-700 text-chalk-2 hover:text-chalk"
                      : "bg-ink-800 text-chalk-3 hover:text-chalk-2"
                }`}
              >
                {label(code)}
                {n > 0 && (
                  <span className="ml-1.5 font-data text-[10px] opacity-60">{n}</span>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
