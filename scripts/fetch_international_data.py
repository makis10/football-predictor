"""
Download international football data from martj42/international_results.

Sources:
  results.csv   — all international results 1872-present (includes upcoming WC 2026 fixtures)
  goalscorers.csv — individual goalscorer data
  shootouts.csv   — penalty shootout results

Usage:
  python scripts/fetch_international_data.py
  python scripts/fetch_international_data.py --force   # re-download even if files exist
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "backend" / "data" / "raw" / "international"

sys.path.insert(0, str(ROOT))
from scripts._http_retry import get_with_retry  # noqa: E402

BASE_URL = "https://raw.githubusercontent.com/martj42/international_results/master"
FILES = ["results.csv", "goalscorers.csv", "shootouts.csv"]


def download(url: str, dest: Path, force: bool = False) -> None:
    if dest.exists() and not force:
        print(f"  [skip] {dest.name} already exists (use --force to re-download)")
        return
    print(f"  Downloading {url} …", end=" ", flush=True)
    r = get_with_retry(url, timeout=60)
    r.raise_for_status()
    dest.write_bytes(r.content)
    print(f"done ({len(r.content)/1024:.0f} KB)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Downloading to {DATA_DIR}")
    for fname in FILES:
        download(f"{BASE_URL}/{fname}", DATA_DIR / fname, force=args.force)

    # Quick stats on results
    import pandas as pd
    df = pd.read_csv(DATA_DIR / "results.csv")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    played = df[df["home_score"].notna() & (df["home_score"] != "NA")]
    upcoming = df[df["home_score"].isna() | (df["home_score"] == "NA")]

    print(f"\nresults.csv summary:")
    print(f"  Total rows  : {len(df):,}")
    print(f"  Played      : {len(played):,}")
    print(f"  Upcoming    : {len(upcoming):,}")
    if len(upcoming):
        print(f"  Upcoming tournaments:")
        for t, c in upcoming["tournament"].value_counts().head(10).items():
            print(f"    {c:>4}  {t}")


if __name__ == "__main__":
    main()
