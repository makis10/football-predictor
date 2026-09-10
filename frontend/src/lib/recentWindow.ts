/**
 * Which days each page of /recent shows.
 *
 * Page 1 is the last seven days including today; page p is the seven days
 * before page p − 1. The pages tile the calendar — no day on two pages, none on
 * neither. They used to be eight days long (both ends reached one day too far),
 * so every boundary day was listed on two pages.
 *
 * Dates are Athens calendar days (YYYY-MM-DD), the ones the cards are grouped
 * under, and the same window is used for club and national matches.
 */
export const DAYS_PER_PAGE = 7;

export const shiftDays = (iso: string, n: number): string =>
  new Date(new Date(`${iso}T00:00:00Z`).getTime() + n * 86_400_000).toISOString().slice(0, 10);

/** `?page=` as a page number. Anything that is not a whole number ≥ 1 is page 1
 *  — `Number("abc")` used to flow through as NaN and render "Could not reach
 *  the API" for a URL typo. */
export function parsePage(raw: string | undefined): number {
  const n = Number(raw ?? "1");
  return Number.isInteger(n) && n >= 1 ? n : 1;
}

/** Inclusive [from, to] for `page`, counted back from `today`. */
export function recentWindow(page: number, today: string): { from: string; to: string } {
  const newest = (page - 1) * DAYS_PER_PAGE;
  return {
    from: shiftDays(today, -(newest + DAYS_PER_PAGE - 1)),
    to: shiftDays(today, -newest),
  };
}

export function recentPageLabel(page: number): string {
  const newest = (page - 1) * DAYS_PER_PAGE;
  if (newest === 0) return `last ${DAYS_PER_PAGE} days`;
  return `${newest + DAYS_PER_PAGE - 1}–${newest} days ago`;
}
