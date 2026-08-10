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

  it("hides the refine control where odds and confidence do nothing", () => {
    // /stats and /recent ignore those query params.
    render(<FilterBar counts={counts} showRefine={false} />);
    expect(screen.queryByRole("button", { name: /filters/i })).toBeNull();
  });
});
