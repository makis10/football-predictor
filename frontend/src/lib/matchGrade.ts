import type { Match } from "@/lib/api";

/**
 * Single source of truth (frontend) for "did the prediction hit?".
 *
 * MUST mirror the backend `stats.py` accuracy definition so the Recent-Results
 * page and the /stats page can't drift apart:
 *   • result correct = argmax of (home_win, draw, away_win) == actual H/D/A
 *   • goals  correct = goals_prediction (OVER/UNDER) matches actual total vs 2.5
 *
 * Note: the Recent page grades the matches it DISPLAYS (a date-window sample),
 * so its numbers are legitimately a subset of the /stats aggregate — but the
 * GRADING RULE here is identical, which is what stops the two from diverging.
 */
export type Grade = "correct" | "partial" | "wrong";

export function hasResult(m: Match): boolean {
  return !!m.prediction && m.home_goals != null && m.away_goals != null;
}

function actualResult(m: Match): "H" | "D" | "A" {
  return m.home_goals! > m.away_goals! ? "H" : m.home_goals === m.away_goals ? "D" : "A";
}

export function resultHit(m: Match): boolean {
  const p = m.prediction!;
  const probs = [p.home_win_prob, p.draw_prob, p.away_win_prob];
  const pick = (["H", "D", "A"] as const)[probs.indexOf(Math.max(...probs))];
  return pick === actualResult(m);
}

export function goalsHit(m: Match): boolean {
  const total = m.home_goals! + m.away_goals!;
  return m.prediction!.goals_prediction === (total > 2.5 ? "OVER" : "UNDER");
}

export function gradeMatch(m: Match): Grade {
  const r = resultHit(m);
  const g = goalsHit(m);
  if (r && g) return "correct";
  if (!r && !g) return "wrong";
  return "partial";
}

export interface AccuracySummary {
  total: number;            // matches with a prediction AND a result
  correct: number;
  partial: number;
  wrong: number;
  bothPct: number | null;
  resultCorrect: number;
  goalsCorrect: number;
  resultPct: number | null;
  goalsPct: number | null;
}

export function accuracySummary(matches: Match[]): AccuracySummary {
  const wp = matches.filter(hasResult);
  const n = wp.length;
  const correct = wp.filter((m) => gradeMatch(m) === "correct").length;
  const partial = wp.filter((m) => gradeMatch(m) === "partial").length;
  const wrong = wp.filter((m) => gradeMatch(m) === "wrong").length;
  const resultCorrect = wp.filter(resultHit).length;
  const goalsCorrect = wp.filter(goalsHit).length;
  const pct = (x: number) => (n > 0 ? Math.round((x / n) * 100) : null);
  return {
    total: n,
    correct,
    partial,
    wrong,
    bothPct: pct(correct),
    resultCorrect,
    goalsCorrect,
    resultPct: pct(resultCorrect),
    goalsPct: pct(goalsCorrect),
  };
}
