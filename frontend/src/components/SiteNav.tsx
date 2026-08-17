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
  /** Sub-items. Desktop shows a dropdown; the mobile drawer indents them. */
  children?: { href: string; label: string }[];
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
  const [menu, setMenu] = useState<string | null>(null);
  const pathname = usePathname();
  const panelId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);

  // Navigating away must close both — otherwise tapping a link leaves the panel
  // covering the page it just loaded.
  useEffect(() => {
    setOpen(false);
    setMenu(null);
  }, [pathname]);

  // A dropdown left open behind a click elsewhere is a stuck menu.
  useEffect(() => {
    if (!menu) return;
    const onDown = (e: MouseEvent) => {
      if (!(e.target as HTMLElement).closest("[data-nav-group]")) setMenu(null);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [menu]);

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
        {items.map((it) =>
          it.children?.length ? (
            <div key={it.href} className="relative" data-nav-group>
              {/* The parent still navigates on click — a section with a submenu
                  is a place, not just a folder. The caret opens the list. */}
              <div className="flex items-center">
                <Link href={it.href} className={linkClass(it.href)}>
                  {it.label}
                </Link>
                <button
                  type="button"
                  onClick={() => setMenu(menu === it.href ? null : it.href)}
                  aria-expanded={menu === it.href}
                  aria-label={`${it.label} — ${openLabel}`}
                  className="-ml-1 rounded-lg px-1 py-1.5 text-chalk-3 transition-colors hover:text-chalk"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
                       stroke="currentColor" strokeWidth="3" strokeLinecap="round"
                       strokeLinejoin="round" aria-hidden
                       className={menu === it.href ? "rotate-180 transition-transform" : "transition-transform"}>
                    <path d="m6 9 6 6 6-6" />
                  </svg>
                </button>
              </div>

              {menu === it.href && (
                <div className="card card-flat absolute left-0 top-full z-30 mt-1 w-56 p-1">
                  {it.children.map((c) => (
                    <Link
                      key={c.href}
                      href={c.href}
                      onClick={() => setMenu(null)}
                      className="block rounded-md px-3 py-2 text-sm text-chalk-2
                                 transition-colors hover:bg-ink-700 hover:text-chalk"
                    >
                      {c.label}
                    </Link>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <Link key={it.href} href={it.href} className={linkClass(it.href)}>
              {it.label}
            </Link>
          ),
        )}
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
            <div key={it.href}>
              <Link href={it.href} className={linkClass(it.href, true)}>
                {it.label}
              </Link>
              {/* No collapsing on mobile: the drawer is already a disclosure,
                  and nesting a second one costs a tap to reach two links. */}
              {it.children?.map((c) => (
                <Link
                  key={c.href}
                  href={c.href}
                  className="ml-3 block rounded-lg border-l border-line px-3 py-2 text-sm
                             text-chalk-2 transition-colors hover:bg-ink-700 hover:text-chalk"
                >
                  {c.label}
                </Link>
              ))}
            </div>
          ))}
        </nav>
      </div>
    </>
  );
}
