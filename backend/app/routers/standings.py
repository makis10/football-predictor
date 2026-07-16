"""League standings — computed from stored results, not fetched."""
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.cache import CACHE_MISS, cache_get, cache_set
from backend.app.database import get_db
from backend.app.ml.standings import compute_standings

router = APIRouter(prefix="/standings", tags=["standings"])

_HIST_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "models" / "projections"

# The table only moves when a result lands, so a short TTL is plenty and keeps
# the page snappy without another cache-invalidation hook to forget about.
_TTL = 600  # 10 min


@router.get("/{league}")
def get_standings(league: str, season: str | None = None, db: Session = Depends(get_db)):
    key = f"standings:{league}:{season or 'current'}"
    cached = cache_get(key)
    if cached is not CACHE_MISS:
        return cached

    table = compute_standings(db, league, season)
    if not table:
        raise HTTPException(status_code=404, detail=f"No standings for {league}")

    cache_set(key, table, _TTL)
    return table


# A 10k-run Monte Carlo takes ~2 s — far too slow to sit in a page load, and the
# answer only moves when a result lands. Re-primed by the daily pipeline
# (run_daily step 9c), which runs ONCE a day — so the TTL must outlast a full
# day, or the entry expires mid-afternoon and the next visitor pays for the
# simulation. 25 h guarantees the 06:00 warm-up always lands before expiry.
_PROJECTION_TTL = 25 * 3600


@router.get("/{league}/projection")
def get_projection(league: str, db: Session = Depends(get_db)):
    """Season projection.

    Domestic league → title / Europe / relegation probabilities.
    UEFA competition → champion / final / last-16 probabilities (only once the
    league phase is drawn; during qualifying the field doesn't exist yet).
    """
    key = f"league_projection:{league}"
    cached = cache_get(key)
    if cached is not CACHE_MISS:
        return cached

    from backend.app.ml.standings import EUROPEAN_STRUCTURE
    if league in EUROPEAN_STRUCTURE:
        from backend.app.ml.european_sim import simulate_european
        proj = simulate_european(db, league)
    else:
        from backend.app.ml.league_sim import simulate_league
        proj = simulate_league(db, league)

    if not proj:
        # Season over, no fixtures, still in qualifying, or a play-off format we
        # refuse to guess at.
        raise HTTPException(status_code=404, detail=f"No projection for {league}")

    cache_set(key, proj, _PROJECTION_TTL)
    return proj


@router.get("/{league}/projection/history")
def get_projection_history(league: str):
    """Daily snapshots of each contender's title/champion odds (model, and
    bookmaker where offered) — appended by scripts/snapshot_projections.py.
    {available: false} until at least one snapshot exists."""
    path = _HIST_DIR / f"{league}.jsonl"
    if not path.exists():
        return {"available": False, "snapshots": []}
    snapshots: list[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            snapshots.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    snapshots.sort(key=lambda s: s.get("date", ""))
    return {"available": len(snapshots) > 0, "snapshots": snapshots}
