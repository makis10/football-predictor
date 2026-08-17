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
