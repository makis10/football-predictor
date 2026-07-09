"""Team expected goals (λ_home, λ_away) for a national fixture, derived from the
snapshot Elo — the SAME engine the WC simulator and player-prop / correct-score
computations use (scripts/compute_player_props.py). Kept here so the analysis
endpoint can build the full Poisson stat block on demand without persisting λ.
"""
from __future__ import annotations

import pickle
from pathlib import Path

_SNAP = Path(__file__).resolve().parents[3] / "data" / "models" / "national" / "snapshot.pkl"
ELO_START, MU_TOTAL, ELO_SCALE = 1500.0, 2.65, 220.0

_cache: tuple[float, dict] | None = None   # (mtime, elo)


def _load_elo() -> dict:
    """Snapshot Elo ratings, reloaded when the snapshot file changes (daily retrain)."""
    global _cache
    try:
        mtime = _SNAP.stat().st_mtime
    except OSError:
        return {}
    if _cache is None or _cache[0] != mtime:
        try:
            with open(_SNAP, "rb") as f:
                _cache = (mtime, pickle.load(f).get("elo", {}) or {})
        except Exception:
            _cache = (mtime, {})
    return _cache[1]


def national_lambdas(home: str, away: str) -> tuple[float, float] | None:
    """(λ_home, λ_away) expected goals, or None if the snapshot isn't available."""
    elo = _load_elo()
    if not elo:
        return None
    gd = (elo.get(home, ELO_START) - elo.get(away, ELO_START)) / ELO_SCALE
    return (max(0.2, MU_TOTAL / 2 + gd / 2), max(0.2, MU_TOTAL / 2 - gd / 2))
