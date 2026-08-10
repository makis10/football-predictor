/**
 * @vitest-environment jsdom
 */
/**
 * What a fixture card actually renders.
 *
 * The card is where almost every user-visible defect showed up: an "⚡ EV +x%"
 * badge that measured the model's disagreement with the bookmaker rather than
 * how likely the outcome was, and an "unknown teams" line on a PAOK tie. The
 * logic suites could not catch either — both are rendering decisions.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import MatchCard from "@/components/MatchCard";
import { getT } from "@/lib/i18n";
import type { Match } from "@/lib/api";

// TrackButton is a client component behind next-auth; it is not what these
// tests are about, and its session hook would need a provider.
vi.mock("@/components/TrackButton", () => ({ default: () => null }));
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

// Auto-cleanup only registers itself when vitest runs with globals enabled;
// we import explicitly, so without this every render stacks up in the same
// document and `screen` finds the PREVIOUS test's card. That is exactly how
// the "no Home 55%" assertion below failed against a correct component.
afterEach(cleanup);

const t = getT("en");

function match(overrides: Partial<Match> = {}): Match {
  return {
    id: 1,
    league: "EPL",
    season: "2026/27",
    match_date: "2026-08-15",
    kickoff_time: "17:00:00",
    home_team: "Arsenal",
    away_team: "Chelsea",
    home_goals: null,
    away_goals: null,
    result: null,
    created_at: "2026-08-01T00:00:00Z",
    prediction: {
      home_win_prob: 0.55,
      draw_prob: 0.25,
      away_win_prob: 0.20,
      over_2_5_prob: 0.6,
      goals_prediction: "OVER",
      model_version: "1.0.0",
      confidence: "high",
      suggested_market: "Home Win @ 1.80",
      ev_score: null,
      insufficient_data: false,
    },
    ...overrides,
  } as Match;
}

describe("MatchCard", () => {
  it("names both teams and the pick with its probability", () => {
    render(<MatchCard match={match()} t={t} />);
    expect(screen.getByText("Arsenal")).toBeDefined();
    expect(screen.getByText("Chelsea")).toBeDefined();
    // 0.55 is the highest of the three → "Home", shown with its own number.
    // Label and percentage are separate nodes (they sit at opposite ends of
    // the bar), so match against the card text rather than a single element.
    expect(screen.getByRole("link").textContent).toMatch(/Home\s*55%/);
  });

  it("picks the outcome the model rates highest, not the stored suggestion", () => {
    // suggested_market deliberately disagrees: the badge is derived from the
    // probabilities so a stale row can never contradict the bars beside it.
    const m = match();
    m.prediction!.home_win_prob = 0.20;
    m.prediction!.away_win_prob = 0.55;
    m.prediction!.suggested_market = "Home Win @ 1.80";
    render(<MatchCard match={m} t={t} />);
    const card = screen.getByRole("link").textContent ?? "";
    expect(card).toMatch(/Away\s*55%/);
    expect(card).not.toMatch(/Home\s*55%/);
  });

  it("never shows an expected-value badge", () => {
    // EV was anti-predictive: those picks landed 32% of the time against 53%
    // for simply taking the favourite. Showing it invites the wrong inference.
    const m = match();
    m.prediction!.ev_score = 0.42;
    const { container } = render(<MatchCard match={m} t={t} />);
    expect(container.textContent).not.toContain("EV +");
  });

  it("names the club we lack history for instead of blaming both", () => {
    const m = match({
      home_team: "PAOK",
      away_team: "Dynamo Kyiv",
      unknown_teams: ["Dynamo Kyiv"],
    });
    m.prediction!.insufficient_data = true;
    const { container } = render(<MatchCard match={m} t={t} />);
    expect(container.textContent).toContain("Dynamo Kyiv");
    expect(container.textContent).not.toContain("unknown teams");
  });

  it("falls back to the generic wording when the API says nothing", () => {
    const m = match();
    m.prediction!.insufficient_data = true;
    const { container } = render(<MatchCard match={m} t={t} />);
    expect(container.textContent).toContain("Insufficient data");
  });

  it("withholds the probability bars entirely on an insufficient-data fixture", () => {
    // Serving a default-feature triple as a real prediction is worse than
    // serving nothing — 14 of 24 UEFA qualifiers once shared four triples.
    const m = match();
    m.prediction!.insufficient_data = true;
    const { container } = render(<MatchCard match={m} t={t} />);
    expect(container.textContent).not.toMatch(/\d{1,3}%\s*·/);
  });

  it("shows the score once the match is played", () => {
    const m = match({ home_goals: 2, away_goals: 1, result: "H" });
    const { container } = render(<MatchCard match={m} t={t} />);
    // Tight en dash: "2–1" is how a scoreline is set, and the spaced form
    // wrapped awkwardly between the two team names on a narrow card.
    expect(container.textContent).toContain("2–1");
  });

  it("renders a fixture with no prediction at all without crashing", () => {
    const { container } = render(<MatchCard match={match({ prediction: null })} t={t} />);
    expect(container.textContent).toContain("Arsenal");
  });
});
