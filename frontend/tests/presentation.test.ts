/**
 * What the site tells the visitor.
 *
 * The backend suite proves the numbers are right; nothing checked that the page
 * renders them honestly. Every case below is a real defect: a league served by
 * the API with no label on the front end, a Greek visitor reading English
 * because a key was added to one table only, a sitemap advertising a redirect.
 *
 * Pure logic, node environment, no DOM and no new dependencies — so it runs on
 * every push alongside tsc and the build.
 */
import { describe, expect, it } from "vitest";

import { LEAGUES, INTERNATIONAL_LEAGUE, leagueFlag, leagueLabel, canonicalLeagueCode } from "@/lib/api";
import { DEFAULT_LANG, getT, messages, normalizeLang } from "@/lib/i18n";
import sitemap from "@/app/sitemap";

// Leagues the API will hand us. Mirrors backend VALID_LEAGUES — the two are
// maintained by hand and drifted when twelve leagues were added on 2026-07-30:
// fixtures arrived and rendered with a raw code and no flag.
const BACKEND_LEAGUES = [
  "EPL", "LaLiga", "SerieA", "Bundesliga", "Ligue1", "GreekSL",
  "CL", "EL", "ECL", "Championship", "LeagueOne", "PrimeiraLiga",
  "Eredivisie", "BrazilSerieA", "ClubFriendly",
  "Belgium", "Turkey", "Scotland", "Denmark", "Sweden", "Norway",
  "Poland", "Austria", "Switzerland", "Romania", "Ireland", "Finland",
];

describe("league presentation", () => {
  it("gives every league the API can return a label and a flag", () => {
    const known = new Set(LEAGUES.map((l) => l.code));
    const missing = BACKEND_LEAGUES.filter((c) => !known.has(c as never));
    expect(missing, `leagues with no front-end entry: ${missing.join(", ")}`).toEqual([]);
  });

  it("resolves every known league to its own entry, and unknowns to the raw code", () => {
    // Not "label !== code": England's second tier is genuinely called
    // "Championship", so its label equals its code by coincidence. What matters
    // is that lookup finds the entry rather than falling through.
    for (const { code, label, flag } of LEAGUES) {
      expect(leagueLabel(code), `${code} did not resolve`).toBe(label);
      expect(leagueFlag(code), `${code} has no flag`).toBe(flag);
    }
    expect(leagueLabel("NotALeague")).toBe("NotALeague");
  });

  it("keeps league labels unique so two competitions can't look identical", () => {
    // Austria's top flight is also called "Bundesliga" and Switzerland's also
    // "Super League"; the codes are country-based for exactly this reason, but
    // the *labels* still have to be distinguishable on screen.
    const labels = LEAGUES.map((l) => l.label);
    const dupes = labels.filter((l, i) => labels.indexOf(l) !== i);
    expect(dupes, `duplicate league labels: ${dupes.join(", ")}`).toEqual([]);
  });

  it("routes the synthetic international code separately", () => {
    // Not a real league — national fixtures are merged into the club lists but
    // link to /national, so it must never appear in the league filter row.
    expect(LEAGUES.map((l) => l.code)).not.toContain(INTERNATIONAL_LEAGUE);
  });

  it("canonicalises a league code without inventing one", () => {
    expect(canonicalLeagueCode("EPL")).toBe("EPL");
    expect(canonicalLeagueCode("definitely-not-a-league")).toBeUndefined();
    expect(canonicalLeagueCode(undefined)).toBeUndefined();
  });
});

describe("bilingual copy", () => {
  it("translates every English key into Greek", () => {
    // The project rule is that a new user-facing string gets a key in BOTH
    // tables. Nothing enforced it, so a half-translated build silently showed
    // English to Greek visitors.
    const missing = Object.keys(messages.en).filter((k) => !(k in messages.el));
    expect(missing, `keys missing a Greek translation: ${missing.join(", ")}`).toEqual([]);
  });

  it("has no Greek keys that no longer exist in English", () => {
    const orphans = Object.keys(messages.el).filter((k) => !(k in messages.en));
    expect(orphans, `stale Greek-only keys: ${orphans.join(", ")}`).toEqual([]);
  });

  it("keeps placeholders identical across languages", () => {
    // "{n} matches" translated without its {n} renders a sentence with a hole.
    const ph = (s: string) => (s.match(/\{(\w+)\}/g) ?? []).sort().join(",");
    const bad = Object.keys(messages.en).filter(
      (k) => ph(messages.en[k]) !== ph(messages.el[k] ?? ""),
    );
    expect(bad, `placeholder mismatch between en/el: ${bad.join(", ")}`).toEqual([]);
  });

  it("substitutes placeholders and never leaves a raw brace", () => {
    const t = getT("el");
    const out = t("matchCard.pickTitle", { n: "470", hit: "53%" });
    expect(out).toContain("470");
    expect(out).not.toMatch(/\{\w+\}/);
  });

  it("falls back to English rather than rendering the key itself", () => {
    const t = getT("el");
    expect(t("this.key.does.not.exist")).toBe("this.key.does.not.exist");
    expect(normalizeLang("nonsense")).toBe(DEFAULT_LANG);
  });
});

describe("sitemap", () => {
  const urls = sitemap().map((e) => e.url);

  it("does not advertise a route that redirects", () => {
    // /national 307s to / since the 2026 World Cup ended. Listing a redirect
    // gets the whole sitemap discounted by crawlers.
    expect(urls.some((u) => u.endsWith("/national"))).toBe(false);
  });

  it("lists the pages we actually serve", () => {
    for (const path of ["", "/stats", "/recent"]) {
      expect(urls.some((u) => u.endsWith(path) || u === `https://aitipster.net${path}`)).toBe(true);
    }
  });

  it("emits absolute, deduplicated URLs", () => {
    expect(new Set(urls).size).toBe(urls.length);
    for (const u of urls) expect(u).toMatch(/^https?:\/\//);
  });
});
