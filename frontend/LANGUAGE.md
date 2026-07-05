# UI language convention

The app deliberately mixes two languages. To stop it drifting into random
Greeklish, keep to this split:

## English — structural chrome
Navigation, page titles, section headers, table column labels, admin tooling.
These are terse, scannable, and read fine to a Greek audience.
Examples: `Upcoming`, `Recent Results`, `Stats`, `EXPECTED CORNERS`,
`CHAMPION PROBABILITY`, `Market Record`, `Training History`.

## Greek — user-facing content & verdicts
Anything that talks *to* the reader: result verdicts, explanations, the AI
analysis prose, caveats, empty states, tooltips.
Examples: `πιάσαμε` / `χάσαμε` / `top-6`, `Υπό παρακολούθηση (αναπόδεικτο)`,
`Πραγματικό σκορ`, the LLM match analysis, responsible-gambling disclaimers.

## Rules of thumb
- A **label** (what a thing *is*) → English.
- A **sentence** (something said to the user) → Greek.
- Never mix languages inside a single sentence/phrase (no Greeklish).
- Numbers, market names (GG, NG, Over 2.5) and team names stay as-is.

A full single-language rebrand (all-English or all-Greek) is a product decision,
not a bug — this file documents the current, intentional convention so new UI
stays consistent with it.
