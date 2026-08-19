/**
 * Server/client boundary guards.
 *
 * These catch a class of bug TypeScript cannot see. `t` is a function, and a
 * function cannot cross from a server component into a client component —
 * React throws at RUNTIME ("Functions cannot be passed directly to Client
 * Components"), the page returns a 500, and the type-checker and the production
 * build both pass happily on the way there. That is exactly what happened when
 * FilterBar was first wired up: `tsc --noEmit` clean, `next build` clean,
 * homepage dead on arrival.
 *
 * The rule the codebase follows:
 *   • server component → client component: pass resolved STRINGS (see SiteNav)
 *   • client component: read `t` from context with useT()
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const SRC = path.resolve(__dirname, "../src");

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (/\.tsx?$/.test(entry)) out.push(full);
  }
  return out;
}

const files = walk(SRC).map((f) => ({ file: f, src: readFileSync(f, "utf8") }));

/** Components whose module opts into the client bundle. */
const clientComponents = new Set(
  files
    .filter(({ src }) => /^\s*["']use client["']/m.test(src))
    .map(({ file }) => path.basename(file).replace(/\.tsx?$/, "")),
);

describe("server → client boundary", () => {
  it("finds the client components it is meant to police", () => {
    // If this ever reads zero, the detector silently stops guarding anything.
    expect(clientComponents.size).toBeGreaterThan(3);
    expect(clientComponents.has("FilterBar")).toBe(true);
  });

  it("never passes the t function into a client component", () => {
    const offenders: string[] = [];
    for (const { file, src } of files) {
      for (const name of clientComponents) {
        // <Name ...props... t={t} — across newlines, up to the closing bracket.
        const re = new RegExp(`<${name}\\b[^>]*?\\bt=\\{t\\}`, "s");
        if (re.test(src)) {
          offenders.push(`${path.relative(SRC, file)} → <${name} t={t}>`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it("client components that need translations use the hook", () => {
    const missing: string[] = [];
    for (const { file, src } of files) {
      if (!/^\s*["']use client["']/m.test(src)) continue;
      // Uses t(...) for lookups but never obtains it from context or a prop.
      const usesT = /\bt\(["'][\w.]+["']/.test(src);
      const hasSource = /useT\s*\(/.test(src) || /\bt:\s*TFunc/.test(src);
      if (usesT && !hasSource) missing.push(path.relative(SRC, file));
    }
    expect(missing).toEqual([]);
  });
});

/**
 * The footer must not state an accuracy figure it made up.
 *
 * It carried "~52% result / ~58% O/U" hardcoded in the translation table while
 * the live numbers were 50.6% / 56.7% all-time and 47.8% / 55.7% over 30 days.
 * A literal can only ever drift in the flattering direction, because nobody
 * edits it downwards when accuracy falls — and this is the one project whose
 * whole pitch is not doing that.
 */
describe("footer accuracy claim", () => {
  const i18n = readFileSync(path.join(SRC, "lib/i18n.ts"), "utf8");

  it("states no percentage of its own", () => {
    const lines = i18n
      .split("\n")
      .filter((l) => /"footer\.(disclaimer|notFinancial)"/.test(l));
    expect(lines.length, "footer strings not found — did the keys move?").toBe(4);
    for (const line of lines) {
      expect(line, `hardcoded figure in ${line.trim()}`).not.toMatch(/\d+\s*%/);
    }
  });

  it("takes the numbers as parameters instead", () => {
    for (const key of ["{result}", "{goals}", "{n}"]) {
      expect(i18n, `footer.accuracy is missing ${key}`).toContain(key);
    }
    // …and the layout has to actually fetch them.
    const layout = readFileSync(path.join(SRC, "app/layout.tsx"), "utf8");
    expect(layout).toContain("getFooterAccuracy");
  });
});

// ── Freemium gate ─────────────────────────────────────────────────────────────
// Tickets and long-term projections went members-only on 2026-08-19. The gate
// is only worth anything if it is rendered SERVER-side instead of the premium
// content — a client-side hide still ships the numbers in the HTML, where any
// visitor can read them from dev-tools.

describe("premium surfaces are gated server-side", () => {
  it("tickets page renders the lock instead of the slips", () => {
    const page = readFileSync(path.join(SRC, "app/tickets/page.tsx"), "utf8");
    expect(page).toContain("getSession");
    expect(page).toContain("LockedDetailPanel");
    // The lock must come before the slips in the same conditional, not beside
    // them: `{session && <Slips/>}` next to `{!session && <Lock/>}` drifts
    // apart the first time someone edits one branch.
    expect(page).toMatch(/!session \?[\s\S]{0,400}LockedDetailPanel/);
  });

  it("projections page gates before fetching anything", () => {
    const page = readFileSync(path.join(SRC, "app/projections/page.tsx"), "utf8");
    expect(page).toContain("LockedDetailPanel");
    const gateAt = page.indexOf("await getSession()");
    const fetchAt = page.indexOf("getLeagueProjection(league)");
    expect(gateAt).toBeGreaterThan(-1);
    expect(fetchAt).toBeGreaterThan(-1);
    expect(gateAt).toBeLessThan(fetchAt);
  });

  it("the settled record stays public on both pages", () => {
    // The accuracy proof is the one thing a stranger can check us against.
    // Gating it would leave the lock asking them to take our word for it.
    const page = readFileSync(path.join(SRC, "app/tickets/page.tsx"), "utf8");
    const gateAt = page.indexOf("locked.tickets.title");
    const recordAt = page.indexOf("tickets.record.title");
    expect(recordAt).toBeGreaterThan(gateAt);
  });

  it("every gate string exists in both languages", () => {
    const i18n = readFileSync(path.join(SRC, "lib/i18n.ts"), "utf8");
    for (const key of [
      "locked.tickets.title", "locked.tickets.body",
      "locked.projections.title", "locked.projections.body",
      "tickets.estimatedSlip",
    ]) {
      const hits = i18n.split(`"${key}"`).length - 1;
      expect(hits, `${key} appears ${hits}x, expected 2 (en + el)`).toBe(2);
    }
  });
});

describe("the ticket gate does not leak live slips through the history", () => {
  it("open slips are withheld from logged-out visitors", () => {
    // A slip is cut with a horizon of up to seven days, so an OPEN slip from
    // two days ago is still bettable — listing its legs in the public history
    // hands over exactly what the lock above withholds. Settled ones are the
    // record and stay public.
    const page = readFileSync(path.join(SRC, "app/tickets/page.tsx"), "utf8");
    expect(page).toMatch(/TicketHistory[\s\S]{0,200}session \?[\s\S]{0,120}outcome/);
  });
});
