/**
 * Parity tests for the frontend grading rule (lib/matchGrade.ts).
 *
 * matchGrade MUST mirror the backend stats.py definition:
 *   • result correct = argmax of (home_win, draw, away_win) == actual H/D/A
 *   • goals  correct = OVER/UNDER pick matches actual total vs 2.5
 * If someone changes one side without the other, these tests are the tripwire —
 * the Recent-Results page and /stats must never disagree on what "correct" means.
 */
import { describe, expect, it } from "vitest";
import {
  accuracySummary,
  gradeMatch,
  goalsHit,
  hasResult,
  resultHit,
} from "@/lib/matchGrade";
import type { Match } from "@/lib/api";

function match(
  probs: [number, number, number],
  goals: [number, number],
  goalsPick: "OVER" | "UNDER",
): Match {
  return {
    home_goals: goals[0],
    away_goals: goals[1],
    prediction: {
      home_win_prob: probs[0],
      draw_prob: probs[1],
      away_win_prob: probs[2],
      goals_prediction: goalsPick,
    },
  } as unknown as Match;
}

describe("resultHit — argmax 1×2 vs actual (stats.py parity)", () => {
  it("home pick + home win = hit", () => {
    expect(resultHit(match([0.6, 0.25, 0.15], [2, 0], "OVER"))).toBe(true);
  });
  it("home pick + away win = miss", () => {
    expect(resultHit(match([0.6, 0.25, 0.15], [0, 1], "UNDER"))).toBe(false);
  });
  it("draw pick (argmax) + draw = hit", () => {
    expect(resultHit(match([0.3, 0.4, 0.3], [1, 1], "UNDER"))).toBe(true);
  });
  it("away pick + away win = hit", () => {
    expect(resultHit(match([0.2, 0.25, 0.55], [0, 3], "OVER"))).toBe(true);
  });
});

describe("goalsHit — O/U 2.5 (stats.py parity)", () => {
  it("OVER pick + 3 goals = hit", () => {
    expect(goalsHit(match([0.6, 0.25, 0.15], [2, 1], "OVER"))).toBe(true);
  });
  it("OVER pick + 2 goals = miss", () => {
    expect(goalsHit(match([0.6, 0.25, 0.15], [1, 1], "OVER"))).toBe(false);
  });
  it("UNDER pick + 2 goals = hit (exactly under the 2.5 line)", () => {
    expect(goalsHit(match([0.6, 0.25, 0.15], [2, 0], "UNDER"))).toBe(true);
  });
});

describe("gradeMatch — correct / partial / wrong", () => {
  it("both hit → correct", () => {
    expect(gradeMatch(match([0.6, 0.25, 0.15], [3, 0], "OVER"))).toBe("correct");
  });
  it("result hit, goals miss → partial", () => {
    expect(gradeMatch(match([0.6, 0.25, 0.15], [1, 0], "OVER"))).toBe("partial");
  });
  it("both miss → wrong", () => {
    expect(gradeMatch(match([0.6, 0.25, 0.15], [0, 1], "OVER"))).toBe("wrong");
  });
});

describe("hasResult + accuracySummary", () => {
  it("skips matches without a prediction or score", () => {
    const unplayed = { home_goals: null, away_goals: null, prediction: null } as unknown as Match;
    expect(hasResult(unplayed)).toBe(false);
    const s = accuracySummary([unplayed]);
    expect(s.total).toBe(0);
    expect(s.bothPct).toBeNull();
  });

  it("aggregates counts + percentages consistently", () => {
    const s = accuracySummary([
      match([0.6, 0.25, 0.15], [3, 0], "OVER"),   // correct
      match([0.6, 0.25, 0.15], [1, 0], "OVER"),   // partial (result only)
      match([0.6, 0.25, 0.15], [0, 1], "OVER"),   // wrong
      match([0.2, 0.25, 0.55], [0, 3], "OVER"),   // correct
    ]);
    expect(s.total).toBe(4);
    expect(s.correct).toBe(2);
    expect(s.partial).toBe(1);
    expect(s.wrong).toBe(1);
    expect(s.resultCorrect).toBe(3);
    expect(s.goalsCorrect).toBe(2);
    expect(s.bothPct).toBe(50);
    expect(s.resultPct).toBe(75);
    expect(s.goalsPct).toBe(50);
  });
});
