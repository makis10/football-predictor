/**
 * What the deployed site actually returns.
 *
 * The other suites check code in isolation. This one fetches the real pages,
 * because the failures that reached visitors were never type errors — they were
 * a whole competition night rendering "no prediction", a league chip showing a
 * raw code, a projections table where every team had identical odds. All of
 * those served a 200 and compiled fine.
 *
 * Network-gated: skips entirely when the site is unreachable, so a CI runner
 * with no access to the host is not a red build. Point it elsewhere with
 * SMOKE_URL to test a local dev server:
 *
 *   SMOKE_URL=http://localhost:3000 npm run test
 */
import { beforeAll, describe, expect, it } from "vitest";

import { LEAGUES } from "@/lib/api";

const BASE = process.env.SMOKE_URL ?? "https://aitipster.net";
const TIMEOUT = 15_000;

let reachable = false;
let home = "";

async function get(path: string): Promise<Response> {
  return fetch(`${BASE}${path}`, { signal: AbortSignal.timeout(TIMEOUT) });
}

beforeAll(async () => {
  try {
    const res = await get("/");
    reachable = res.ok;
    if (reachable) home = await res.text();
  } catch {
    reachable = false;
  }
}, TIMEOUT + 5_000);

describe("deployed site", () => {
  it("serves the homepage", () => {
    if (!reachable) return;
    expect(home.length).toBeGreaterThan(1_000);
    expect(home).toContain("Football Predictor");
  });

  it.each(["/stats", "/recent", "/projections", "/sitemap.xml", "/robots.txt"])(
    "serves %s",
    async (path) => {
      if (!reachable) return;
      const res = await get(path);
      expect(res.status, `${path} returned ${res.status}`).toBe(200);
    },
  );

  it("renders every league chip with a name, never a raw code", () => {
    if (!reachable) return;
    // A league added to the backend but not to LEAGUES renders as "Belgium"
    // rather than "Pro League" — visible, ugly, and easy to miss in review.
    // The bar now lists only leagues that actually have fixtures in the window
    // — on a quiet midweek that is a handful — and parks the rest behind a
    // drawer whose markup is not server-rendered. So the count assertion is a
    // liveness check, not a census; the raw-code check below is the real guard.
    const rendered = LEAGUES.filter((l) => home.includes(l.label));
    expect(
      rendered.length,
      "no league labels at all — did the filter row stop rendering?",
    ).toBeGreaterThan(0);

    const rawCodes = LEAGUES
      .filter((l) => l.label !== l.code)
      .filter((l) => home.includes(`>${l.code}<`));
    expect(rawCodes.map((l) => l.code), "leagues rendered as raw codes").toEqual([]);
  });

  it("shows a headline pick with a probability", () => {
    if (!reachable) return;
    // The picks row is the first thing a visitor reads. It briefly showed an
    // "⚡ EV +x%" badge, which measured the model's disagreement with the
    // bookmaker rather than how likely the outcome was.
    expect(home).toMatch(/\d{1,3}%/);
    expect(home).not.toContain("EV +");
  });

  it("does not leak an error or a stack trace into the page", () => {
    if (!reachable) return;
    for (const marker of ["Traceback", "Internal Server Error", "ECONNREFUSED",
                          "Cannot read properties of undefined"]) {
      expect(home, `page contains ${marker}`).not.toContain(marker);
    }
  });

  it("keeps redirect-only routes out of the sitemap", async () => {
    if (!reachable) return;
    const xml = await (await get("/sitemap.xml")).text();
    expect(xml).not.toContain("/national");
    expect(xml).toContain("<urlset");
  });

  it("reports whether it ran, so a silent skip is visible", () => {
    // Every assertion above no-ops when the site is unreachable. Without this
    // line a fully offline run looks identical to a fully passing one.
    if (!reachable) {
      console.warn(`[smoke] ${BASE} unreachable — deployed-site checks skipped`);
    }
    expect(typeof reachable).toBe("boolean");
  });
});
