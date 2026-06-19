"""
One-off generator: build scripts/upcoming_friendlies.csv from the accurate
ESPN-sourced June 2026 pre-World-Cup friendly schedule.

Maps ESPN team names → martj42/snapshot spelling, drops any match where a
team is not in the trained Elo snapshot (minnows we can't rate), and writes
the CSV consumed by add_upcoming_national.py.

Re-runnable. Already-played June-2 matches (Colombia-Costa Rica,
Canada-Uzbekistan) are intentionally excluded — martj42 carries those as
played results, we don't predict them retroactively.
"""
from __future__ import annotations

import pickle
from pathlib import Path

import pandas as pd

ROOT     = Path(__file__).resolve().parent.parent
SNAP     = ROOT / "backend" / "data" / "models" / "national" / "snapshot.pkl"
OUT      = ROOT / "scripts" / "upcoming_friendlies.csv"

# ESPN name → snapshot/martj42 name
NAME_MAP = {
    "Czechia":              "Czech Republic",
    "Türkiye":              "Turkey",
    "Congo DR":             "DR Congo",
    "Bosnia-Herzegovina":   "Bosnia and Herzegovina",
    "Kyrgyz Republic":      "Kyrgyzstan",
    "China":                "China PR",
}

# Venues confirmed in a third country → neutral
NEUTRAL = {
    ("Spain", "Peru"),
    ("Netherlands", "Uzbekistan"),
}

# (date, home, away) — ESPN schedule, June 2-8 2026. Already-played June-2
# matches excluded.
FIXTURES = [
    # June 2 (upcoming today)
    ("2026-06-02", "Croatia", "Belgium"),
    ("2026-06-02", "Georgia", "Romania"),
    ("2026-06-02", "Morocco", "Madagascar"),
    ("2026-06-02", "Wales", "Ghana"),
    ("2026-06-02", "Haiti", "New Zealand"),
    # June 3
    ("2026-06-03", "Philippines", "Guam"),
    ("2026-06-03", "Kyrgyz Republic", "Kenya"),
    ("2026-06-03", "Gibraltar", "British Virgin Islands"),
    ("2026-06-03", "Albania", "Israel"),
    ("2026-06-03", "Congo DR", "Denmark"),
    ("2026-06-03", "Luxembourg", "Italy"),
    ("2026-06-03", "Netherlands", "Algeria"),
    ("2026-06-03", "Poland", "Nigeria"),
    ("2026-06-03", "Panama", "Dominican Republic"),
    ("2026-06-03", "South Korea", "El Salvador"),
    # June 4
    ("2026-06-04", "Cambodia", "Bhutan"),
    ("2026-06-04", "Lesotho", "Kenya"),
    ("2026-06-04", "Burundi", "Equatorial Guinea"),
    ("2026-06-04", "Northern Ireland", "Guinea"),
    ("2026-06-04", "Slovenia", "Cyprus"),
    ("2026-06-04", "Andorra", "Liechtenstein"),
    ("2026-06-04", "Sweden", "Greece"),
    ("2026-06-04", "Spain", "Iraq"),
    ("2026-06-04", "France", "Ivory Coast"),
    ("2026-06-04", "Czechia", "Guatemala"),
    ("2026-06-04", "Mexico", "Serbia"),
    # June 5
    ("2026-06-05", "Tanzania", "Uganda"),
    ("2026-06-05", "Singapore", "China"),
    ("2026-06-05", "Angola", "Botswana"),
    ("2026-06-05", "Hong Kong", "Mongolia"),
    ("2026-06-05", "Thailand", "Kuwait"),
    ("2026-06-05", "Indonesia", "Oman"),
    ("2026-06-05", "Belarus", "Syria"),
    ("2026-06-05", "Georgia", "Bahrain"),
    ("2026-06-05", "Slovakia", "Montenegro"),
    ("2026-06-05", "Moldova", "Bulgaria"),
    ("2026-06-05", "Russia", "Burkina Faso"),
    ("2026-06-05", "San Marino", "Bangladesh"),
    ("2026-06-05", "Hungary", "Finland"),
    ("2026-06-05", "Azerbaijan", "Malta"),
    ("2026-06-05", "Paraguay", "Nicaragua"),
    ("2026-06-05", "Puerto Rico", "Saudi Arabia"),
    ("2026-06-05", "Canada", "Republic of Ireland"),
    ("2026-06-05", "Haiti", "Peru"),
    # June 6
    ("2026-06-06", "Myanmar", "Guam"),
    ("2026-06-06", "Ethiopia", "Malawi"),
    ("2026-06-06", "Belgium", "Tunisia"),
    ("2026-06-06", "Armenia", "Kazakhstan"),
    ("2026-06-06", "Palestine", "Kenya"),
    ("2026-06-06", "Comoros", "Rwanda"),
    ("2026-06-06", "Gibraltar", "Cayman Islands"),
    ("2026-06-06", "Portugal", "Chile"),
    ("2026-06-06", "Romania", "Wales"),
    ("2026-06-06", "Albania", "Luxembourg"),
    ("2026-06-06", "United States", "Germany"),
    ("2026-06-06", "Australia", "Switzerland"),
    ("2026-06-06", "Panama", "Bosnia-Herzegovina"),
    ("2026-06-06", "Bolivia", "Scotland"),
    ("2026-06-06", "England", "New Zealand"),
    ("2026-06-06", "Qatar", "El Salvador"),
    ("2026-06-06", "Brazil", "Egypt"),
    ("2026-06-06", "Venezuela", "Türkiye"),
    ("2026-06-06", "Argentina", "Honduras"),
    ("2026-06-06", "Curacao", "Aruba"),
    # June 7
    ("2026-06-07", "Kenya", "Lesotho"),
    ("2026-06-07", "Liechtenstein", "Cyprus"),
    ("2026-06-07", "Denmark", "Ukraine"),
    ("2026-06-07", "Kosovo", "Andorra"),
    ("2026-06-07", "Croatia", "Slovenia"),
    ("2026-06-07", "Greece", "Italy"),
    ("2026-06-07", "Morocco", "Norway"),
    ("2026-06-07", "Ecuador", "Guatemala"),
    ("2026-06-07", "Colombia", "Jordan"),
    # June 8
    ("2026-06-08", "Netherlands", "Uzbekistan"),
    ("2026-06-08", "France", "Northern Ireland"),
    ("2026-06-08", "Spain", "Peru"),
]


def main() -> None:
    known = set(pickle.load(open(SNAP, "rb"))["elo"].keys())

    rows, dropped = [], []
    for date, h_raw, a_raw in FIXTURES:
        h = NAME_MAP.get(h_raw, h_raw)
        a = NAME_MAP.get(a_raw, a_raw)
        if h not in known or a not in known:
            miss = [t for t in (h, a) if t not in known]
            dropped.append((date, h_raw, a_raw, miss))
            continue
        neutral = (h, a) in NEUTRAL
        rows.append({
            "date": date, "home_team": h, "away_team": a,
            "tournament": "Friendly", "city": "", "country": "",
            "neutral": neutral,
        })

    df = pd.DataFrame(rows, columns=["date", "home_team", "away_team",
                                     "tournament", "city", "country", "neutral"])
    df.to_csv(OUT, index=False)

    print(f"✓ Wrote {len(df)} fixtures → {OUT}")
    print(f"  Dropped {len(dropped)} (team not in Elo snapshot):")
    for date, h, a, miss in dropped:
        print(f"    {date}  {h} vs {a}   missing: {miss}")


if __name__ == "__main__":
    main()
