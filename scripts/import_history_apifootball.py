"""
Back-fill match HISTORY for leagues we do not predict but whose clubs we do.

Two gaps this closes, both found on 2026-07-30 by looking at what the site
actually showed:

  1. PROMOTED CLUBS. Kalamata plays in the Greek Super League — which we
     predict — but its record is in Super League 2, which we never ingested, so
     eleven Greek fixtures rendered "no history, no prediction". Same for Amed /
     Erzurumspor / Çorum (Turkish 1. Lig), Lommel and SK Beveren (Belgian
     Challenger Pro), Elversberg (2. Bundesliga), Le Mans (Ligue 2) and
     Académico de Viseu (Liga 2).

  2. EUROPEAN QUALIFIERS. 88 clubs appeared only in CL/EL/ECL ties, from ~30
     countries with no free CSV source anywhere — Croatia, Czechia, Hungary,
     Serbia, Ukraine, Israel, Bulgaria, Cyprus, the Baltics, the Caucasus and
     the micro-leagues. football-data.co.uk publishes none of them.

API-Football has all of it and the account already pays for it: one request per
league-season returns the full season with scores.

These are HISTORY-ONLY leagues. They are loaded by features.load_raw_csvs, so
they build Elo, form and H2H for clubs that later turn up in a competition we
DO price — but train.py drops them before fitting (see HISTORY_ONLY_LEAGUES
there). We never predict a Faroese league match, and their scoring environments
would skew parameters shared with the leagues we do serve.

Output matches the football-data.co.uk main-set schema so load_raw_csvs ingests
it unchanged. Shots/odds/referee columns are absent — irrelevant here, since
these rows are context for the team snapshot, not training examples.

Idempotent: an existing season file is skipped unless --refresh. The current
season is always re-fetched (it grows).

Usage:
  docker compose exec -T backend python scripts/import_history_apifootball.py
  docker compose exec -T backend python scripts/import_history_apifootball.py --leagues Greece2,Turkey2
  docker compose exec -T backend python scripts/import_history_apifootball.py --from-season 2018
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.app.ml.league_registry import disambiguate  # noqa: E402
from scripts._http_retry import get_with_retry  # noqa: E402

API_BASE = "https://v3.football.api-sports.io"
API_KEY = os.getenv("API_SPORTS_KEY", "")
HEADERS = {"x-apisports-key": API_KEY}
RAW_DIR = ROOT / "backend" / "data" / "raw"

FINISHED = {"FT", "AET", "PEN", "WO", "AWD"}

# our league name → API-Football league id. Every id was read off the live
# /leagues endpoint per country; the naive "lowest id" is often the SECOND tier
# (Israel 382 is Liga Leumit, not Ligat Ha'al), so they are pinned explicitly.
#
# Names carry a "2" suffix for second tiers and are country-based otherwise, for
# the same reason as the July 2026 expansion: local names collide (three
# different "Premier League"s below) and load_raw_csvs keys off the filename.
LEAGUES: dict[str, int] = {
    # ── Second tiers: history for clubs promoted into a league we predict ──
    "Greece2":      494,   # Super League 2 (Kalamata)
    "GreeceFL":     198,   # old Football League, folded 2020 — deeper history
    "Turkey2":      204,   # 1. Lig (Amed, Erzurumspor, Çorum)
    "Belgium2":     145,   # Challenger Pro (Lommel, SK Beveren)
    "Germany2":      79,   # 2. Bundesliga (Elversberg)
    "France2":       62,   # Ligue 2 (Le Mans)
    "Portugal2":     95,   # Liga 2 (Académico de Viseu)
    "Spain2":       141,
    "Italy2":       136,
    "Netherlands2":  89,
    # 2026-08-03. Same gap as the ten above, found by sweeping every upcoming
    # fixture against the CSV team counts: these four promoted sides were being
    # priced off almost nothing, and — unlike Elversberg — they slipped past
    # _predictable(), because 1 historical row is enough to count as "known".
    # Ids read off /leagues per country, never guessed: Poland 106 is the
    # Ekstraklasa we already predict, 107 is the I Liga underneath it.
    "Poland2":      107,   # I Liga (Wieczysta Krakow) — API holds 2018+
    "Romania2":     284,   # Liga II (Corvinul) — 2016+
    "Sweden2":      114,   # Superettan (Orgryte) — 2016+
    "BrazilSerieB":  72,   # Serie B (Remo) — 2012+
    # ── Foreign top flights: history for European qualifying opponents ──
    "Croatia":      210, "Czechia":      345, "Hungary":     271,
    "Serbia":       286, "Ukraine":      333, "Israel":      383,
    "Bulgaria":     172, "Cyprus":       318, "Slovenia":    373,
    "Slovakia":     332, "Bosnia":       315, "Estonia":     329,
    "Latvia":       365, "Lithuania":    362, "Armenia":     342,
    "Georgia":      327, "Azerbaijan":   419, "Kazakhstan":  389,
    "Belarus":      116, "Albania":      310, "Kosovo":      664,
    "NMacedonia":   371, "Moldova":      394, "FaroeIslands": 367,
    "Iceland":      164, "Malta":        393, "NorthernIreland": 408,
    "Wales":        110, "Andorra":      312, "Luxembourg":  261,
    "Montenegro":   355, "Gibraltar":    758,
}

DEFAULT_FROM_SEASON = 2015
FIELDS = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"]


def _ascii(name: str) -> str:
    """Transliterate a club name to plain ASCII.

    load_raw_csvs reads every file as latin-1, because that is what
    football-data.co.uk actually publishes. Slavic and Baltic diacritics have no
    latin-1 representation, so writing them straight out turned "Železničar
    Pančevo" into "?elezni?ar Pan?evo" — and a name full of question marks
    slugs to something that matches nothing, which is exactly how these clubs
    stayed unknown after their history had already been imported.

    Stripping the accents instead keeps the slug identical to the fixture-side
    spelling ("Železničar Pančevo" and "Zeleznicar Pancevo" both slug to
    "zeleznicarpancevo"), so the existing resolver matches them with no alias.
    These leagues are history-only — the names are never displayed.
    """
    import unicodedata
    return unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode("ascii")


class Budget:
    def __init__(self, cap: int):
        self.cap, self.used = cap, 0

    def ok(self) -> bool:
        return self.used < self.cap

    def hit(self) -> None:
        self.used += 1


def _get(path: str, params: dict, budget: Budget) -> dict:
    budget.hit()
    r = get_with_retry(f"{API_BASE}{path}", headers=HEADERS, params=params, timeout=25)
    r.raise_for_status()
    body = r.json()
    errs = body.get("errors")
    if errs:
        # Quota errors arrive as HTTP 200 with an errors dict — without this an
        # exhausted plan is indistinguishable from an empty season.
        if isinstance(errs, dict) and "requests" in errs:
            raise SystemExit(f"[fatal] API-Football daily quota exhausted: {errs['requests']}")
        raise RuntimeError(f"API-Football error: {errs}")
    return body


def _seasons_for(league_id: int, budget: Budget, first: int) -> list[int]:
    """Seasons the API actually holds for this league, from `first` onward."""
    body = _get("/leagues", {"id": league_id}, budget)
    resp = body.get("response", [])
    if not resp:
        return []
    return sorted(s["year"] for s in resp[0]["seasons"] if s["year"] >= first)


def main() -> None:
    ap = argparse.ArgumentParser(description="Import league history from API-Football")
    ap.add_argument("--leagues", type=str, default=None,
                    help="Comma-separated subset of the league names below")
    ap.add_argument("--from-season", type=int, default=DEFAULT_FROM_SEASON)
    ap.add_argument("--max-requests", type=int, default=900)
    ap.add_argument("--refresh", action="store_true",
                    help="Re-download seasons whose file already exists")
    args = ap.parse_args()

    if not API_KEY:
        print("[error] API_SPORTS_KEY not set.")
        sys.exit(1)

    names = [s.strip() for s in args.leagues.split(",")] if args.leagues else list(LEAGUES)
    bad = [n for n in names if n not in LEAGUES]
    if bad:
        print(f"[error] unknown league(s): {', '.join(bad)}")
        sys.exit(1)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    budget = Budget(args.max_requests)
    current_year = datetime.now().year
    total_files = total_rows = 0

    for name in names:
        if not budget.ok():
            print(f"[budget] cap reached — {name} onwards not fetched.")
            break
        league_id = LEAGUES[name]
        try:
            seasons = _seasons_for(league_id, budget, args.from_season)
        except Exception as e:
            print(f"  [warn] {name}: could not list seasons — {e}")
            continue
        if not seasons:
            print(f"  [warn] {name}: no seasons from {args.from_season} onward")
            continue

        wrote = rows_total = skipped = 0
        for season in seasons:
            if not budget.ok():
                break
            path = RAW_DIR / f"{name}_{season}.csv"
            # Past seasons are immutable; only the live one needs refreshing.
            if path.exists() and not args.refresh and season < current_year:
                skipped += 1
                continue
            try:
                body = _get("/fixtures", {"league": league_id, "season": season}, budget)
            except SystemExit:
                raise
            except Exception as e:
                print(f"  [warn] {name} {season}: {e}")
                continue

            rows = []
            for entry in body.get("response", []):
                fx = entry.get("fixture", {})
                if fx.get("status", {}).get("short") not in FINISHED:
                    continue
                g = entry.get("goals", {})
                hg, ag = g.get("home"), g.get("away")
                if hg is None or ag is None:
                    continue
                # disambiguate() before storing: API-Football calls the
                # Belarusian club "Arsenal" and the Cypriot one "Olympiakos",
                # exactly as it calls Arsenal FC and Olympiacos Piraeus, and a
                # bare string cannot hold both. See league_registry.
                rows.append({
                    "Date":     fx["date"][:10],
                    "HomeTeam": disambiguate(
                        name, _ascii(entry["teams"]["home"]["name"]).strip()),
                    "AwayTeam": disambiguate(
                        name, _ascii(entry["teams"]["away"]["name"]).strip()),
                    "FTHG":     int(hg),
                    "FTAG":     int(ag),
                    "FTR":      "H" if hg > ag else ("A" if ag > hg else "D"),
                })
            if not rows:
                continue
            with open(path, "w", newline="", encoding="latin-1", errors="replace") as f:
                w = csv.DictWriter(f, fieldnames=FIELDS)
                w.writeheader()
                w.writerows(rows)
            wrote += 1
            rows_total += len(rows)

        total_files += wrote
        total_rows += rows_total
        print(f"  [ok] {name:18} {rows_total:6,} matches → {wrote} new file(s)"
              + (f", {skipped} already on disk" if skipped else ""))

    print(f"\nDone — {total_rows:,} matches across {total_files} new season file(s), "
          f"{budget.used} API requests.")
    if total_files:
        print("These are HISTORY-ONLY leagues: retrain to pick them up "
              "(they build Elo/form but are dropped before fitting).")


if __name__ == "__main__":
    main()
