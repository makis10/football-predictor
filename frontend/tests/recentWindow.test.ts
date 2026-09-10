/**
 * /recent's pages, and the two ways they showed the wrong matches.
 *
 * 1. Both ends of every window reached one day too far, so each page was eight
 *    days long and the day at every boundary was listed on two pages.
 * 2. Club matches came from one request capped at 200 rows. The busiest week of
 *    the season holds ~330, so the first page silently lost its oldest days —
 *    and computed its accuracy summary on what was left.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { parsePage, recentPageLabel, recentWindow, shiftDays } from "@/lib/recentWindow";
import { getPastMatchesBetween } from "@/lib/api";

const TODAY = "2026-09-10";

const days = (from: string, to: string): string[] => {
  const out: string[] = [];
  for (let d = from; d <= to; d = shiftDays(d, 1)) out.push(d);
  return out;
};

describe("recentWindow", () => {
  it("page 1 is the last seven days, today included", () => {
    expect(recentWindow(1, TODAY)).toEqual({ from: "2026-09-04", to: "2026-09-10" });
  });

  it("pages tile the calendar: no day twice, none skipped", () => {
    const seen: string[] = [];
    for (let p = 1; p <= 20; p++) {
      const { from, to } = recentWindow(p, TODAY);
      const span = days(from, to);
      expect(span).toHaveLength(7);
      seen.push(...span);
    }
    expect(new Set(seen).size).toBe(seen.length);
    expect([...seen].sort()).toEqual(days(shiftDays(TODAY, -139), TODAY));
  });

  it("the label names the days the page shows", () => {
    expect(recentPageLabel(1)).toBe("last 7 days");
    expect(recentPageLabel(2)).toBe("13–7 days ago");
    expect(recentWindow(2, TODAY)).toEqual({
      from: shiftDays(TODAY, -13),
      to: shiftDays(TODAY, -7),
    });
  });

  it("anything that is not a page number is page 1", () => {
    for (const raw of [undefined, "abc", "0", "-3", "1.5", ""]) {
      expect(parsePage(raw)).toBe(1);
    }
    expect(parsePage("4")).toBe(4);
  });
});

describe("getPastMatchesBetween", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps paging past the endpoint's 200-row cap", async () => {
    const total = 333;
    const calls: URL[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const u = new URL(String(input));
        calls.push(u);
        const offset = Number(u.searchParams.get("offset"));
        const limit = Number(u.searchParams.get("limit"));
        const n = Math.max(0, Math.min(limit, total - offset));
        const rows = Array.from({ length: n }, (_, i) => ({ id: offset + i }));
        return new Response(JSON.stringify(rows), { status: 200 });
      }),
    );

    const rows = await getPastMatchesBetween("Bundesliga", "2026-09-04", "2026-09-10");

    expect(rows).toHaveLength(total);
    expect(new Set(rows.map((r) => r.id)).size).toBe(total);
    expect(calls).toHaveLength(2);
    for (const u of calls) {
      expect(u.searchParams.get("status")).toBe("past");
      expect(u.searchParams.get("date_from")).toBe("2026-09-04");
      expect(u.searchParams.get("date_to")).toBe("2026-09-10");
      expect(u.searchParams.get("league")).toBe("Bundesliga");
    }
  });
});
