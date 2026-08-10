"use client";

/**
 * Primary navigation — inline on desktop, a drawer on a phone.
 *
 * This exists because of a measured bug, not a style preference. The links laid
 * out in a row are ~385px wide; against a 375px viewport that made the whole
 * DOCUMENT 740px, so every page on the site scrolled sideways or rendered at
 * half scale on a phone. Constraining the row instead (min-w-0 / flex-1 /
 * overflow-x-auto) was tried first and is worse: flexbox collapses the nav to
 * zero and the links disappear entirely.
 *
 * Below `md` the links move into a drawer. The row that remains is brand +
 * language + bell + trigger, which fits 375px with room to spare.
 *
 * `t` cannot cross the server/client boundary, so the labels arrive already
 * translated from the layout.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";

export interface NavItem {
  href: string;
  label: string;
}

export default function SiteNav({
  items,
  closeLabel,
  openLabel,
}: {
  items: NavItem[];
  openLabel: string;
  closeLabel: string;
}) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const panelId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);

  // Navigating away must close the drawer — otherwise tapping a link leaves it
  // covering the page it just loaded.
  useEffect(() => setOpen(false), [pathname]);

  // Esc closes and returns focus to the trigger, so keyboard users are not
  // stranded inside a panel they cannot see a way out of.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  const linkClass = (href: string, block = false) =>
    [
      "rounded-lg text-sm transition-colors",
      block ? "block px-3 py-2.5" : "px-3 py-1.5",
      isActive(href)
        ? "bg-ink-600 text-chalk font-medium"
        : "text-chalk-2 hover:text-chalk hover:bg-ink-700",
    ].join(" ");

  return (
    <>
      {/* Desktop: inline. Hidden below md, where it would force the overflow. */}
      <nav className="ml-3 hidden items-center gap-1 md:flex">
        {items.map((it) => (
          <Link key={it.href} href={it.href} className={linkClass(it.href)}>
            {it.label}
          </Link>
        ))}
      </nav>

      {/* Mobile trigger */}
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={open ? closeLabel : openLabel}
        /* order-last parks the trigger at the far right of the header row, past
           the ml-auto controls group. Without it the button sits directly after
           the wordmark and reads as floating in the middle of the row. */
        className="order-last ml-1 flex h-9 w-9 shrink-0 flex-col items-center justify-center
                   gap-[3px] rounded-lg border border-line bg-ink-700 text-chalk-2
                   transition-colors hover:text-chalk md:hidden"
      >
        <span
          className={`block h-px w-4 bg-current transition-transform ${
            open ? "translate-y-[4px] rotate-45" : ""
          }`}
        />
        <span className={`block h-px w-4 bg-current ${open ? "opacity-0" : ""}`} />
        <span
          className={`block h-px w-4 bg-current transition-transform ${
            open ? "-translate-y-[4px] -rotate-45" : ""
          }`}
        />
      </button>

      {/* Drawer. Positioned against the sticky header, full-bleed, so it never
          widens the document the way the inline row did. */}
      <div
        id={panelId}
        hidden={!open}
        className="absolute inset-x-0 top-full border-b border-line
                   bg-ink-800/95 backdrop-blur md:hidden"
      >
        <nav className="mx-auto flex max-w-6xl flex-col gap-0.5 px-4 py-3">
          {items.map((it) => (
            <Link key={it.href} href={it.href} className={linkClass(it.href, true)}>
              {it.label}
            </Link>
          ))}
        </nav>
      </div>
    </>
  );
}
