/**
 * Theme guards.
 *
 * The light theme works by overriding `--color-*` under `:root[data-theme]`, so
 * every surface follows automatically — as long as it is expressed in tokens. A
 * single hardcoded colour silently opts one element out, and the failure is
 * invisible to whoever wrote it because they were looking at the dark theme.
 *
 * Real examples this catches, both shipped and both found only by measuring:
 *   • `bg-white/50` for the bookmaker tick in MatchAnalysis — vanished on white.
 *   • `rgba(242,245,250,.5)` for the confidence hatching — same.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const SRC = path.resolve(__dirname, "../src");
const CSS = path.join(SRC, "app/globals.css");

// Charts pick per-series colours; those are data, not chrome, and they are
// allowed to be literals. Everything else must go through a token.
// opengraph-image renders to a PNG through satori, which has no document and
// therefore no CSS custom properties: `var(--color-…)` resolves to nothing and
// the social card comes out black. Its literals mirror the dark theme by hand.
// global-error renders when the ROOT LAYOUT itself threw, so globals.css was
// never applied and `var(--color-…)` resolves to nothing — the one file that
// must inline its colours or show white-on-white to someone already having a
// bad time.
const ALLOWED = /Chart|Calibration|ProjectionHistory|opengraph-image|global-error/;

// Third-party brand marks. PayPal's blue is PayPal's blue on a white page too,
// and Google's "G" is a fixed four-colour logo — tokenising either would be
// wrong, not tidy. Narrow by design: a file earns a place here only for a mark
// it does not own, and the rest of that file is still checked by the other two
// assertions.
const BRAND_LITERALS: Record<string, string[]> = {
  "app/layout.tsx": ["#0070ba", "#005ea6"],                       // PayPal
  "app/login/page.tsx": ["#4285F4", "#34A853", "#FBBC05", "#EA4335"], // Google
};

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (/\.tsx?$/.test(entry)) out.push(full);
  }
  return out;
}

const files = walk(SRC)
  .filter((f) => !ALLOWED.test(path.basename(f)))
  .map((f) => ({ rel: path.relative(SRC, f), src: readFileSync(f, "utf8") }));

describe("theme tokens", () => {
  it("defines both themes", () => {
    const css = readFileSync(CSS, "utf8");
    expect(css).toContain('[data-theme="light"]');
    // Every token the dark theme declares needs a light counterpart, or that
    // one surface stays dark on a white page.
    const dark = [...css.matchAll(/--color-([a-z0-9-]+):/g)].map((m) => m[1]);
    const lightBlock = css.slice(css.indexOf('[data-theme="light"]'));
    const light = new Set(
      [...lightBlock.matchAll(/--color-([a-z0-9-]+):/g)].map((m) => m[1]),
    );
    const missing = [...new Set(dark)].filter((k) => !light.has(k) && k !== "on-signal");
    expect(missing, "tokens with no light-theme value").toEqual([]);
  });

  it("no component hardcodes white or black", () => {
    const offenders = files
      .filter(({ src }) => /\b(?:bg|text|border|divide|ring)-(?:white|black)\b/.test(src))
      .map(({ rel }) => rel);
    expect(offenders).toEqual([]);
  });

  it("no component hardcodes a hex or rgb() colour", () => {
    const offenders: string[] = [];
    for (const { rel, src } of files) {
      // Strip comments — the token values are quoted in prose all over this repo.
      let code = src
        .replace(/\/\*[\s\S]*?\*\//g, "")
        .split("\n")
        .filter((l) => !l.trim().startsWith("//"))
        .join("\n");
      for (const literal of BRAND_LITERALS[rel] ?? []) code = code.split(literal).join("");
      if (/#[0-9a-fA-F]{6}\b|\brgba?\(\s*\d+\s*,/.test(code)) offenders.push(rel);
    }
    expect(offenders).toEqual([]);
  });
});

/**
 * Contrast.
 *
 * Both themes were built to WCAG AA and one existing dark-theme value failed on
 * the way: chalk-3 measured 2.95:1 against ink-700, below even the large-text
 * floor, on every caption sitting on a chip or a bar track. It had been shipped
 * for months. Nothing catches that by eye — a colour a shade too dim looks
 * deliberate — so it gets a test.
 */
function luminance(hex: string): number {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  const f = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

function tokensFrom(block: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const m of block.matchAll(/--color-([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})/g)) {
    out[m[1]] = m[2];
  }
  return out;
}

describe("contrast", () => {
  const css = readFileSync(CSS, "utf8");
  const lightStart = css.indexOf('[data-theme="light"]');
  const themes = {
    dark: tokensFrom(css.slice(0, lightStart)),
    light: tokensFrom(css.slice(lightStart)),
  };

  const SURFACES = ["ink-900", "ink-800", "ink-700"];
  const FOREGROUNDS = ["chalk", "chalk-2", "chalk-3", "win", "lose", "est"];

  it.each(Object.keys(themes))("%s theme meets AA on every surface", (name) => {
    const t = themes[name as keyof typeof themes];
    const failures: string[] = [];
    for (const fg of FOREGROUNDS) {
      for (const bg of SURFACES) {
        if (!t[fg] || !t[bg]) continue;
        const ratio = contrast(t[fg], t[bg]);
        if (ratio < 4.5) failures.push(`${fg} on ${bg}: ${ratio.toFixed(2)}:1`);
      }
    }
    expect(failures, `${name} theme below 4.5:1`).toEqual([]);
  });

  it("reads real values, not an empty table", () => {
    // Without this the loops above pass vacuously if the parser ever breaks.
    expect(Object.keys(themes.dark).length).toBeGreaterThan(8);
    expect(Object.keys(themes.light).length).toBeGreaterThan(8);
  });
});
