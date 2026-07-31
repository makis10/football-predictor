/**
 * @vitest-environment jsdom
 */
/**
 * The row a visitor reads first.
 *
 * It shipped with the subtitle "highest-confidence predictions" sitting
 * directly above three cards that each read "LOW CONFIDENCE" — the ranking has
 * always been by probability, and the two are different things. It also once
 * risked surfacing no-history fixtures, whose default-derived probabilities are
 * identical for every such match.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import TopPicks from "@/components/TopPicks";
import { getT } from "@/lib/i18n";
import type { Match } from "@/lib/api";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

afterEach(cleanup);

const t = getT("en");

let nextId = 1;
function match(home: string, probs: [number, number, number],
               opts: Partial<Match["prediction"]> = {}): Match {
  const [h, d, a] = probs;
  return {
    id: nextId++,
    league: "EPL",
    season: "2026/27",
    match_date: "2026-08-15",
    kickoff_time: "17:00:00",
    home_team: home,
    away_team: `${home} Opponent`,
    home_goals: null,
    away_goals: null,
    result: null,
    created_at: "2026-08-01T00:00:00Z",
    prediction: {
      home_win_prob: h,
      draw_prob: d,
      away_win_prob: a,
      over_2_5_prob: 0.5,
      goals_prediction: "OVER",
      model_version: "1.0.0",
      confidence: "low",
      suggested_market: null,
      ev_score: null,
      insufficient_data: false,
      ...opts,
    },
  } as Match;
}

describe("TopPicks", () => {
  it("describes what it actually ranks by", () => {
    render(<TopPicks matches={[match("Arsenal", [0.7, 0.2, 0.1])]} t={t} />);
    const text = document.body.textContent ?? "";
    expect(text).toContain("highest model probability");
    // The old copy promised confidence while sorting on probability, so the
    // subtitle contradicted the tier printed on every card beneath it.
    expect(text).not.toContain("highest-confidence");
  });

  it("shows the three most likely outcomes, strongest first", () => {
    // Ranked on the highest 1×2 probability, so the names below are ordered by
    // that number and nothing else.
    const matches = [
      match("Third", [0.40, 0.31, 0.29]),
      match("First", [0.80, 0.12, 0.08]),
      match("Second", [0.55, 0.25, 0.20]),
      match("Fourth", [0.34, 0.33, 0.33]),
    ];
    render(<TopPicks matches={matches} t={t} />);
    const body = document.body.textContent ?? "";
    expect(body).toContain("First");
    expect(body).toContain("Second");
    expect(body).toContain("Third");
    expect(body).not.toContain("Fourth");   // 4th by probability → cut
    expect(body.indexOf("First")).toBeLessThan(body.indexOf("Second"));
    expect(body.indexOf("Second")).toBeLessThan(body.indexOf("Third"));
  });

  it("never surfaces a fixture we have no history for", () => {
    // Their probabilities come from a default feature vector and are identical
    // across every such match — the opposite of a "top pick".
    const matches = [
      match("Unknown", [0.95, 0.03, 0.02], { insufficient_data: true }),
      match("Real", [0.60, 0.25, 0.15]),
    ];
    render(<TopPicks matches={matches} t={t} />);
    const body = document.body.textContent ?? "";
    expect(body).toContain("Real");
    expect(body).not.toContain("Unknown");
  });

  it("renders nothing rather than an empty shell when there is no candidate", () => {
    const { container } = render(<TopPicks matches={[]} t={t} />);
    expect(container.textContent).toBe("");
  });

  it("takes its copy from the translation function, not hard-coded English", () => {
    // Shared presentational components receive `t` as a prop; hard-coding text
    // here is how a Greek visitor ends up reading English.
    render(<TopPicks matches={[match("Arsenal", [0.7, 0.2, 0.1])]} t={getT("el")} />);
    expect(document.body.textContent).toContain("μεγαλύτερη πιθανότητα μοντέλου");
  });

  it("labels the pick with the outcome that carries the probability", () => {
    render(<TopPicks matches={[match("Arsenal", [0.1, 0.2, 0.7])]} t={t} />);
    const body = document.body.textContent ?? "";
    expect(body).toContain("70%");
    expect(body).toMatch(/Away Win/i);
  });
});
