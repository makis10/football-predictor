/**
 * The probability bar — this design's signature element.
 *
 * The problem it solves: a 55% pick at HIGH confidence and a 55% pick at LOW
 * confidence used to render identically, with the difference reduced to a small
 * grey word underneath that nobody reads. But that difference is the entire
 * product. This model publishes ~50.7% accuracy, drops picks it cannot justify,
 * and deliberately shrinks toward uncertainty; a bar that hides how sure we are
 * says something the code does not.
 *
 * So: the solid fill is the estimate, and the hatched band across it is the
 * range we would not be surprised by. Tight band = we mean it. Wide band = the
 * number is 55% but do not lean on it.
 *
 * The band width is presentational, derived from the confidence tier the model
 * already assigns — it is NOT a computed confidence interval, and nothing here
 * claims it is. It is the tier, drawn to scale, so two cards can be compared by
 * eye instead of by reading two adjectives.
 */
import type { TFunc } from "@/lib/i18n";

/** Half-width of the band, in percentage points, per confidence tier. */
const BAND: Record<string, number> = {
  high: 6,
  medium: 13,
  low: 22,
};

export type BarTone = "win" | "neutral" | "lose";

const TONE_FILL: Record<BarTone, string> = {
  win: "bg-win/85",
  neutral: "bg-chalk-2/50",
  lose: "bg-lose/80",
};

export function ProbabilityBar({
  label,
  probability,
  confidence,
  tone = "neutral",
  emphasis = false,
  showRange = false,
  t,
}: {
  label: string;
  probability: number; // 0–1
  /** high | medium | low — omit to draw a plain bar with no band. */
  confidence?: string | null;
  tone?: BarTone;
  emphasis?: boolean;
  /** Print the numeric range under the bar (detail views; too noisy in a list). */
  showRange?: boolean;
  t?: TFunc;
}) {
  const pct = Math.max(0, Math.min(100, probability * 100));
  const band = confidence ? (BAND[confidence] ?? 0) : 0;
  const lo = Math.max(0, pct - band);
  const hi = Math.min(100, pct + band);

  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <span
          className={
            emphasis
              ? "font-display text-sm font-bold text-chalk"
              : "text-sm text-chalk-2"
          }
        >
          {label}
        </span>
        <span
          className={`font-data tabular-nums ${
            emphasis ? "text-base font-bold text-chalk" : "text-sm text-chalk-2"
          }`}
        >
          {Math.round(pct)}%
        </span>
      </div>

      <div className="relative h-2.5 w-full overflow-hidden rounded-full bg-ink-700">
        <div
          className={`absolute inset-y-0 left-0 rounded-full ${TONE_FILL[tone]}`}
          style={{ width: `${pct}%` }}
        />
        {band > 0 && (
          <div
            className="absolute inset-y-0"
            style={{
              left: `${lo}%`,
              width: `${hi - lo}%`,
              // Chalk hatching — the same pitch-marking material as the rest of
              // the system, so the band reads as "drawn on" rather than as a
              // fourth colour competing with the three signal hues. Reads the
              // flood token so it inverts with the theme instead of staying
              // white-on-white.
              backgroundImage:
                "repeating-linear-gradient(115deg, var(--color-flood) 0 1px, transparent 1px 6px)",
            }}
            aria-hidden
          />
        )}
      </div>

      {showRange && band > 0 && t && (
        <p className="mt-1 text-[11px] text-chalk-3">
          {t("pred.range", { lo: Math.round(lo), hi: Math.round(hi) })}
        </p>
      )}
    </div>
  );
}

/** Legend for the band — shown once per page, not once per card. */
export function ConfidenceLegend({ t }: { t: TFunc }) {
  return (
    <p className="flex items-center gap-2 text-[11px] text-chalk-3">
      <span
        className="inline-block h-2.5 w-9 rounded-full bg-ink-700"
        style={{
          backgroundImage:
            "repeating-linear-gradient(115deg, var(--color-flood) 0 1px, transparent 1px 6px)",
        }}
        aria-hidden
      />
      {t("pred.bandLegend")}
    </p>
  );
}
