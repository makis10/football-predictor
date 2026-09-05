/**
 * @vitest-environment jsdom
 */
/**
 * The filter bar, and one bug that shipped.
 *
 * The Filters popover opened correctly — React state flipped, the element
 * mounted, `aria-expanded` went true — and was invisible. It sat inside the
 * horizontally-scrolling chip strip, and `overflow-x: auto` forces `overflow-y`
 * to compute to `auto` too: CSS cannot clip one axis and leave the other
 * visible. So a 191px popover was clipped to a 38px strip.
 *
 * Nothing in the stack catches that. It type-checks, it builds, it renders, and
 * the DOM assertions all pass — only the pixels are wrong. What IS checkable is
 * the structure: an absolutely-positioned layer must not be a descendant of a
 * scroll container. jsdom has no layout engine but it has the tree, so that is
 * exactly the assertion to make.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import FilterBar from "@/components/FilterBar";
import { getT } from "@/lib/i18n";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/components/LanguageProvider", () => ({ useT: () => getT("en") }));

afterEach(cleanup);

const counts = [
  { code: "EPL", count: 6 },
  { code: "CL", count: 4 },
];

function clipsItsChildren(el: Element | null): Element | null {
  let node: Element | null = el;
  while (node) {
    const cls = typeof node.className === "string" ? node.className : "";
    if (/overflow-(x|y)-(auto|scroll|hidden)/.test(cls)) return node;
    node = node.parentElement;
  }
  return null;
}

describe("FilterBar", () => {
  it("opens the refine popover", () => {
    render(<FilterBar counts={counts} />);
    const trigger = screen.getByRole("button", { name: /filters/i });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText(/minimum odds/i)).toBeDefined();
  });

  it("renders the popover outside any scrolling ancestor", () => {
    render(<FilterBar counts={counts} />);
    fireEvent.click(screen.getByRole("button", { name: /filters/i }));
    // Walk up from the popover's content; nothing above it may clip.
    const popover = screen.getByText(/minimum odds/i).closest("div.absolute");
    expect(popover, "popover should be absolutely positioned").not.toBeNull();
    const clipper = clipsItsChildren(popover!.parentElement);
    expect(
      clipper && (typeof clipper.className === "string" ? clipper.className : ""),
      "popover is inside a scroll container and will be clipped",
    ).toBeFalsy();
  });

  it("still scrolls the chips", () => {
    // The strip must keep its overflow — the fix moves the popover out, it does
    // not remove scrolling, or 27 leagues would wrap into a wall again.
    const { container } = render(<FilterBar counts={counts} />);
    expect(container.querySelector('[class*="overflow-x-auto"]')).not.toBeNull();
  });

  it("shows only leagues with fixtures, plus a way to reach the rest", () => {
    render(<FilterBar counts={counts} />);
    expect(screen.getByRole("button", { name: /premier league/i })).toBeDefined();
    expect(screen.getByRole("button", { name: /\+\d+ leagues/i })).toBeDefined();
  });

  /**
   * 2026-09-05. The same CSS property, a second bug, and this one hid content
   * rather than a control's own panel.
   *
   * "+N leagues" was the LAST child of the scrolling strip. Eight chips already
   * overflow a 1280px viewport, so the one control that reveals the other
   * twenty leagues was itself scrolled past the right edge — rendered, in the
   * DOM, asserted on by the test above, and never visible. A reader looking for
   * the Greek league (8 fixtures, ranked 9th, one place past the cut) had no way
   * to learn the drawer existed at all.
   *
   * jsdom cannot see that either. What it can see is the tree: a control that
   * must always be reachable cannot live inside a scroll container.
   */
  const many = [
    { code: "Championship", count: 12 },
    { code: "BrazilSerieA", count: 10 },
    { code: "EPL", count: 9 },
    { code: "LaLiga", count: 9 },
    { code: "SerieA", count: 9 },
    { code: "Belgium", count: 8 },
    { code: "Bundesliga", count: 8 },
    { code: "Eredivisie", count: 8 },
    { code: "GreekSL", count: 8 }, // 9th: one past the eight-chip cut
    { code: "Ligue1", count: 6 },
  ];

  const strip = (container: HTMLElement) =>
    container.querySelector('[class*="overflow-x-auto"]') as HTMLElement;

  it("keeps the way into the full league list out of the scrolling strip", () => {
    const { container } = render(<FilterBar counts={many} />);
    const more = screen.getByRole("button", { name: /\+\d+ leagues/i });
    expect(
      strip(container).contains(more),
      "the +N trigger scrolls off the right edge with the chips it is meant to reveal",
    ).toBe(false);
  });

  it("puts an off-list league at the FRONT of the bar once it is picked", () => {
    // Appended after the eight busiest it lands past the same right edge, so the
    // active filter is invisible and a short filtered list reads as a bug.
    const { container } = render(<FilterBar counts={many} activeLeague="GreekSL" />);
    const chips = [...strip(container).querySelectorAll("button")];
    expect(chips[0].textContent).toMatch(/all/i);
    expect(chips[1].textContent).toContain("Super League");
    expect(chips[1].textContent).toContain("8");
    // It replaces the eighth chip rather than making the strip wider.
    expect(chips.length).toBe(9);
  });

  it("resolves whatever case the URL carried to the real league", () => {
    // ?league=greeksl must still produce the flag-and-name chip, not the raw code.
    const { container } = render(<FilterBar counts={many} activeLeague="greeksl" />);
    const chips = [...strip(container).querySelectorAll("button")];
    expect(chips[1].textContent).toContain("Super League");
    expect(chips[1].textContent).not.toContain("greeksl");
  });

  it("orders the drawer by what is on, and says how much", () => {
    // It used to list 28 codes in declaration order with nothing marking which
    // had fixtures, so the drawer was a directory rather than an answer.
    const { container } = render(<FilterBar counts={many} />);
    fireEvent.click(screen.getByRole("button", { name: /\+\d+ leagues/i }));
    const drawer = container.querySelector("div.card.card-flat.flex-wrap");
    expect(drawer, "drawer did not open").not.toBeNull();
    const buttons = [...drawer!.querySelectorAll("button")];
    const labels = buttons.map((b) => b.textContent ?? "");

    // Read the count from its own element, not from textContent: "Ligue 1" + "6"
    // concatenates to "Ligue 16", and a regex on the tail reads that as sixteen.
    // Only a league with fixtures gets a count at all, so its presence is the
    // marker — every one of the ten must come before every empty league.
    const priced = buttons.map((b) => {
      const el = b.querySelector("span.font-data");
      return el ? Number(el.textContent) : null;
    });
    expect(priced.slice(0, many.length).every((n) => n !== null)).toBe(true);
    expect(priced.slice(many.length).every((n) => n === null)).toBe(true);

    // …and those ten are ordered by how much is on, biggest first.
    const shownCounts = priced.slice(0, many.length) as number[];
    expect(shownCounts).toEqual([...shownCounts].sort((a, b) => b - a));
    expect(shownCounts[0]).toBe(12);

    // The league this whole change is about is in there, with its count.
    const greek = buttons.findIndex((b) => (b.textContent ?? "").includes("🇬🇷"));
    expect(greek, "the Greek league is missing from the drawer").toBeGreaterThan(-1);
    expect(priced[greek]).toBe(8);
    expect(labels.length).toBe(28); // nothing dropped: 27 leagues + International
  });

  it("does not print a count on pages that never took one", () => {
    // /stats and /recent pass counts=[]. "All 0" there is not a measurement, it
    // is a wrong claim about pages that plainly have data.
    const { container } = render(<FilterBar counts={[]} activeLeague="GreekSL" />);
    expect(strip(container).querySelector("span.font-data")).toBeNull();
    // …while a real zero on the fixture list still says "nothing on".
    cleanup();
    const home = render(<FilterBar counts={many} activeLeague="LeagueOne" />);
    const pinned = [...strip(home.container).querySelectorAll("button")][1];
    expect(pinned.querySelector("span.font-data")?.textContent).toBe("0");
  });

  it("hides the refine control where odds and confidence do nothing", () => {
    // /stats and /recent ignore those query params.
    render(<FilterBar counts={counts} showRefine={false} />);
    expect(screen.queryByRole("button", { name: /filters/i })).toBeNull();
  });
});
