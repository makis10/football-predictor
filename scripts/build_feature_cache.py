"""Build the prepared training frame once and cache it for experiments.

`train.prepare_data` walks 211k rows in Python (~5 min) and every experiment
that starts from it would pay that again. This writes the exact frame train.py
fits on — after the history-only drop, the COVID drop, the core-feature dropna
and the optional-feature imputation — to backend/data/cache/ (gitignored).

It does NOT rewrite backend/data/models/impute_medians.json: prepare_data
normally persists the medians it computes, and an experiment must never touch
the production artefact.

  docker compose exec -T backend python scripts/build_feature_cache.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.ml import train as _train

CACHE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..",
                                         "backend", "data", "cache"))
OUT = os.path.join(CACHE_DIR, "features_prepared.pkl")


def main() -> int:
    os.makedirs(CACHE_DIR, exist_ok=True)
    _orig = _train._impute_optional
    _train._impute_optional = lambda df, save_medians=True: _orig(df, save_medians=False)
    t0 = time.time()
    df = _train.prepare_data(_train.RAW_DIR)
    df.to_pickle(OUT)
    print(f"cached {len(df):,} rows x {df.shape[1]} cols -> {OUT}  ({time.time()-t0:.0f}s)")
    print(f"date range {df['Date'].min().date()} -> {df['Date'].max().date()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
