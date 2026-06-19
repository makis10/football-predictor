"""
Monte Carlo simulation of the FIFA World Cup 2026 — winner & finalist odds.

Why a simulation (and not just our 72 match predictions):
  Winner / finalist is NOT a sum of single-match predictions. You must roll the
  whole tournament forward thousands of times: group stage → standings →
  Round-of-32 → … → final, propagating uncertainty at every step.

Engine:
  An Elo-Poisson model (Elo from our trained national snapshot) samples a
  scoreline for every match — consistent across group and knockout, gives
  goal-difference / goals-for for group tiebreakers, and naturally handles
  knockout draws (→ extra time → penalties). The Elo→goals scale C is
  CALIBRATED so the simulation's average home-win probability over the 72 group
  fixtures matches our trained result model's stored probabilities — i.e. the
  sim reflects "the stats we have".

Bracket:
  Real group draw (derived from the 72 fixtures) + the official WC-2026 R32
  template. Best-8-thirds are slotted by bipartite matching against each slot's
  allowed-group set (faithful to FIFA's constraints). Group→letter assignment is
  deterministic but approximate (martj42 fixtures carry no group label), so
  exact bracket *paths* are indicative, not official.

Output:
  P(win), P(reach final), P(reach SF), most-likely final pairing — and a
  side-by-side with the sharp bookmaker "World Cup Winner" market.

Usage:
  docker compose exec backend python scripts/simulate_wc.py
  docker compose exec backend python scripts/simulate_wc.py --sims 50000
  docker compose exec backend python scripts/simulate_wc.py --no-market
"""
from __future__ import annotations

import argparse
import os
import pickle
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA_DIR   = ROOT / "backend" / "data" / "raw" / "international"
SNAP_PATH  = ROOT / "backend" / "data" / "models" / "national" / "snapshot.pkl"
ELO_START  = 1500.0
MU_TOTAL   = 2.65          # WC historical avg goals/game
RNG        = np.random.default_rng(20260611)

# ── Official WC-2026 Round-of-32 template (group positions) ───────────────────
# Each entry: (slotA, slotB). "1X"=winner group X, "2X"=runner-up, "3:SET"=best
# third from one of the listed groups (filled by bipartite matching).
R32 = {
    73: ("2A", "2B"),
    74: ("1E", "3:ABCDF"),
    75: ("1F", "2C"),
    76: ("1C", "2F"),
    77: ("1I", "3:CDFGH"),
    78: ("2E", "2I"),
    79: ("1A", "3:CEFHI"),
    80: ("1L", "3:EHIJK"),
    81: ("1D", "3:BEFIJ"),
    82: ("1G", "3:AEHIJ"),
    83: ("2K", "2L"),
    84: ("1H", "2J"),
    85: ("1B", "3:EFGIJ"),
    86: ("1J", "2H"),
    87: ("1K", "3:DEIJL"),
    88: ("2D", "2G"),
}
# Round-of-16: winners of these R32 matches meet.
R16 = [(74, 77), (73, 75), (76, 78), (79, 80), (83, 84), (81, 82), (86, 88), (85, 87)]
# Balanced tree from R16 onward (adjacent pairs).
QF = [(0, 1), (2, 3), (4, 5), (6, 7)]   # indices into R16 winners
SF = [(0, 1), (2, 3)]                     # indices into QF winners
# Final = winners of the two SF.

THIRD_SLOTS = {  # R32 match → allowed third-place groups
    74: set("ABCDF"), 77: set("CDFGH"), 79: set("CEFHI"), 80: set("EHIJK"),
    81: set("BEFIJ"), 82: set("AEHIJ"), 85: set("EFGIJ"), 87: set("DEIJL"),
}


# ── Load data ─────────────────────────────────────────────────────────────────

def load_elo() -> dict[str, float]:
    with open(SNAP_PATH, "rb") as f:
        return dict(pickle.load(f)["elo"])


# ── Player goal shares (Golden Boot) ──────────────────────────────────────────
# martj42 goalscorers.csv: date,home_team,away_team,team,scorer,minute,own_goal,penalty
GOALSCORERS_PATH   = DATA_DIR / "goalscorers.csv"
SQUADS_PATH        = DATA_DIR / "wc_squads.json"   # scripts/fetch_wc_squads.py
TOP_K_PLAYERS      = 12     # named players per team; rest lumped into "other"
HALF_LIFE_DAYS     = 540.0  # recency decay: goal 18 months ago counts half
ACTIVE_WITHIN_DAYS = 730    # drop players with no international goal in 2 years
OTHER_SPLIT        = 6      # pseudo-players the "other" bucket is split into:
                            # the bucket is many players, not one — letting its
                            # TOTAL compete in the argmax would massively
                            # overestimate the field's Golden Boot chances.


# ── Squad filter (official call-ups) ─────────────────────────────────────────

def _norm_name(s: str) -> str:
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", s.lower())
    return nfkd.encode("ascii", "ignore").decode("ascii")


def _name_keys(full: str) -> tuple[str, str, str]:
    """(full_slug, first_initial, last_token_slug) for fuzzy name matching.

    Handles 'Lionel Messi' vs API-Football 'L. Messi', accents, hyphens."""
    import re
    toks = [t for t in re.split(r"[\s.]+", _norm_name(full)) if t]
    slug = re.sub(r"[^a-z0-9]", "", "".join(toks))
    last = re.sub(r"[^a-z0-9]", "", toks[-1]) if toks else ""
    init = toks[0][0] if toks and toks[0] else ""
    return slug, init, last


def _load_squad_index() -> dict[str, dict]:
    """team → {"slugs": set, "by_last": {last: set(initials)}} from wc_squads.json."""
    if not SQUADS_PATH.exists():
        return {}
    try:
        import json
        raw = json.loads(SQUADS_PATH.read_text())
    except Exception as e:
        print(f"[golden-boot] could not read {SQUADS_PATH}: {e}")
        return {}
    index: dict[str, dict] = {}
    for team, entry in raw.items():
        slugs: set[str] = set()
        by_last: dict[str, set[str]] = {}
        for name in entry.get("players", []):
            slug, init, last = _name_keys(name)
            if slug:
                slugs.add(slug)
            if last:
                by_last.setdefault(last, set()).add(init)
        index[team] = {"slugs": slugs, "by_last": by_last}
    return index


def _in_squad(scorer: str, squad: dict) -> bool:
    slug, init, last = _name_keys(scorer)
    if slug in squad["slugs"]:
        return True
    # 'Lionel Messi' vs 'L. Messi': same last token + same first initial.
    if last in squad["by_last"] and init in squad["by_last"][last]:
        return True
    # Containment fallback for compound names ('Vinicius Junior' vs 'Vinicius Jr').
    if len(slug) >= 6:
        for s in squad["slugs"]:
            if len(s) >= 6 and (slug in s or s in slug):
                return True
    return False


def load_player_shares(teams: set[str], top_k: int = TOP_K_PLAYERS) -> dict[str, list[tuple[str, float]]]:
    """
    Recency-weighted share of each WC team's goals per player.

    Share_i = (decay-weighted goals by player i) / (decay-weighted TEAM goals).
    Own goals stay in the team total but credit no player, and players without
    a goal in the last ACTIVE_WITHIN_DAYS are dropped (retired / out of squad)
    — both flow into the implicit "other" bucket (1 − Σ shares).

    When wc_squads.json exists (scripts/fetch_wc_squads.py), scorers NOT in the
    official squad are dropped too — their share flows to "other". Teams
    without squad data (or with a degenerate match) fall back to unfiltered.
    """
    if not GOALSCORERS_PATH.exists():
        print(f"[golden-boot] {GOALSCORERS_PATH} missing — skipping player shares.")
        return {}
    df = pd.read_csv(GOALSCORERS_PATH, parse_dates=["date"])
    df = df[df["team"].isin(teams) & (df["date"] >= "2018-01-01")].dropna(subset=["scorer"])
    if df.empty:
        return {}
    today = pd.Timestamp.today()
    df = df.assign(weight=np.power(0.5, (today - df["date"]).dt.days / HALF_LIFE_DAYS))

    team_tot = df.groupby("team")["weight"].sum()
    own = df["own_goal"].astype(str).str.upper().isin(("TRUE", "1"))
    pl = (
        df[~own]
        .groupby(["team", "scorer"])
        .agg(w=("weight", "sum"), last_goal=("date", "max"))
        .reset_index()
    )
    pl = pl[pl["last_goal"] >= today - pd.Timedelta(days=ACTIVE_WITHIN_DAYS)]

    squad_index = _load_squad_index()
    if squad_index:
        print(f"[golden-boot] Squad filter active for {len(squad_index)} teams (wc_squads.json).")
    n_dropped = 0

    shares: dict[str, list[tuple[str, float]]] = {}
    for team in teams:
        tot = float(team_tot.get(team, 0.0))
        if tot <= 0:
            shares[team] = []
            continue
        sub = pl[pl["team"] == team]
        squad = squad_index.get(team)
        if squad is not None:
            keep = sub["scorer"].apply(lambda n: _in_squad(n, squad))
            # Guard: a degenerate match (almost everyone dropped) means name
            # formats didn't line up — better unfiltered than wrong.
            if keep.sum() >= 3:
                n_dropped += int((~keep).sum())
                sub = sub[keep]
        sub = sub.sort_values("w", ascending=False).head(top_k)
        shares[team] = [(r["scorer"], float(r["w"]) / tot) for _, r in sub.iterrows()]
    if squad_index and n_dropped:
        print(f"[golden-boot] {n_dropped} historical scorers dropped (not in official squads).")
    return shares


def load_wc_2026() -> tuple[dict[tuple[str, str], tuple[int, int]],
                            list[tuple[str, str]],
                            list[tuple[str, str]]]:
    """Load the 2026 WC group stage, split into played and remaining.

    Returns:
      played_map    — {(home, away): (home_goals, away_goals)} for finished games
      all_pairs     — every group fixture (played + upcoming); used to derive the
                      12 groups robustly even after results start coming in
      upcoming_pairs — still-to-play fixtures (used only to calibrate the scale)

    Restricted to 2026 (date ≥ 2026-06-01) so historical World Cups in the same
    file aren't pulled in.
    """
    df = pd.read_csv(DATA_DIR / "results.csv")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    wc = df[(df["tournament"] == "FIFA World Cup") & (df["date"] >= "2026-06-01")]

    played_map: dict[tuple[str, str], tuple[int, int]] = {}
    all_pairs: list[tuple[str, str]] = []
    upcoming_pairs: list[tuple[str, str]] = []
    for _, r in wc.iterrows():
        h, a = r["home_team"], r["away_team"]
        all_pairs.append((h, a))
        if pd.notna(r["home_score"]) and pd.notna(r["away_score"]):
            played_map[(h, a)] = (int(r["home_score"]), int(r["away_score"]))
        else:
            upcoming_pairs.append((h, a))
    return played_map, all_pairs, upcoming_pairs


def derive_groups(fixtures: list[tuple[str, str]]) -> dict[str, list[str]]:
    """Connected-components of the co-appearance graph → 12 groups of 4."""
    adj: dict[str, set[str]] = defaultdict(set)
    for h, a in fixtures:
        adj[h].add(a); adj[a].add(h)
    seen: set[str] = set()
    comps: list[list[str]] = []
    for team in adj:
        if team in seen:
            continue
        stack, comp = [team], []
        while stack:
            t = stack.pop()
            if t in seen:
                continue
            seen.add(t); comp.append(t)
            stack.extend(adj[t] - seen)
        comps.append(sorted(comp))
    # Deterministic letter assignment: order groups by their strongest team's name
    comps.sort(key=lambda c: c[0])
    return {chr(ord("A") + i): comp for i, comp in enumerate(comps)}


# ── Elo-Poisson match engine ──────────────────────────────────────────────────

def _lambdas(elo_a: float, elo_b: float, scale: float) -> tuple[float, float]:
    gd = (elo_a - elo_b) / scale
    la = max(0.15, MU_TOTAL / 2 + gd / 2)
    lb = max(0.15, MU_TOTAL / 2 - gd / 2)
    return la, lb


def calibrate_scale(elo: dict, fixtures: list, target_home_wp: float) -> float:
    """Grid-search C so mean P(home win) over group fixtures ≈ model's mean."""
    best_c, best_err = 300.0, 9.9
    for c in range(120, 601, 20):
        hw = []
        for h, a in fixtures:
            la, lb = _lambdas(elo.get(h, ELO_START), elo.get(a, ELO_START), c)
            # analytic-ish via quick MC of Poisson (vectorised)
            hs = RNG.poisson(la, 4000); as_ = RNG.poisson(lb, 4000)
            hw.append(float(np.mean(hs > as_)))
        err = abs(np.mean(hw) - target_home_wp)
        if err < best_err:
            best_err, best_c = err, c
    return float(best_c)


def play(elo_a: float, elo_b: float, scale: float, knockout: bool) -> tuple:
    """Group mode: returns (pts_a, pts_b, gd_a, goals_a).
    Knockout mode: returns (winner, goals_a, goals_b) where winner is 0=A, 1=B
    (draws resolved by Elo-weighted penalty shoot-out; shoot-out goals don't
    count toward goal tallies, matching Golden Boot rules)."""
    la, lb = _lambdas(elo_a, elo_b, scale)
    ga, gb = int(RNG.poisson(la)), int(RNG.poisson(lb))
    if not knockout:
        if ga > gb:   return 3, 0, ga - gb, ga
        if ga < gb:   return 0, 3, ga - gb, ga
        return 1, 1, 0, ga
    # knockout: resolve draws via penalties (slight Elo tilt)
    if ga != gb:
        return (0 if ga > gb else 1, ga, gb)
    p_a = 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400))
    return (0 if RNG.random() < p_a else 1, ga, gb)


# ── One full tournament ───────────────────────────────────────────────────────

def simulate_once(
    groups: dict[str, list[str]], elo: dict, scale: float,
    played_map: dict[tuple[str, str], tuple[int, int]] | None = None,
) -> tuple[str, tuple[str, str], dict[str, int], dict[str, tuple[bool, bool, bool]]]:
    """Returns (champion, (finalistA, finalistB), goals_per_team, group_outcome).

    group_outcome: team → (won_group, top2, qualified) for this simulation.

    played_map: real, already-finished group results to CONDITION on. Each such
    fixture uses its actual scoreline (no randomness); only the remaining
    fixtures are sampled. This makes the projection a live conditional one,
    not a from-scratch re-roll."""
    played_map = played_map or {}
    standings: dict[str, list] = {}      # group → ranked team list
    thirds: list[tuple] = []             # (pts, gd, gf, team, group)
    goals_acc: dict[str, int] = defaultdict(int)   # team → tournament goals (Golden Boot)

    def _pair_goals(ta: str, tb: str) -> tuple[int, int]:
        """(goals_ta, goals_tb) — actual result if played, else sampled."""
        if (ta, tb) in played_map:
            return played_map[(ta, tb)]
        if (tb, ta) in played_map:
            gb, ga = played_map[(tb, ta)]   # stored home,away → swap to (ta,tb)
            return ga, gb
        la, lb = _lambdas(elo.get(ta, ELO_START), elo.get(tb, ELO_START), scale)
        return int(RNG.poisson(la)), int(RNG.poisson(lb))

    for g, teams in groups.items():
        pts = {t: 0 for t in teams}; gd = {t: 0 for t in teams}; gf = {t: 0 for t in teams}
        for ta, tb in combinations(teams, 2):
            ga, gb = _pair_goals(ta, tb)
            if ga > gb:   pts[ta] += 3
            elif ga < gb: pts[tb] += 3
            else:         pts[ta] += 1; pts[tb] += 1
            gd[ta] += ga - gb; gd[tb] += gb - ga
            gf[ta] += ga;      gf[tb] += gb
            goals_acc[ta] += ga; goals_acc[tb] += gb
        ranked = sorted(teams, key=lambda t: (pts[t], gd[t], gf[t], RNG.random()), reverse=True)
        standings[g] = ranked
        third = ranked[2]
        thirds.append((pts[third], gd[third], gf[third], third, g))

    # Best 8 thirds
    thirds.sort(key=lambda x: (x[0], x[1], x[2], RNG.random()), reverse=True)
    best8 = thirds[:8]
    qualifying_third_groups = {t[4] for t in best8}
    third_team_by_group = {t[4]: t[3] for t in best8}

    # Per-team group outcome for this sim: won group / top-2 / qualified (top-2
    # or one of the 8 best thirds).
    qualified_thirds = set(third_team_by_group.values())
    group_outcome: dict[str, tuple[bool, bool, bool]] = {}
    for g, ranked in standings.items():
        for pos, team in enumerate(ranked):
            won  = pos == 0
            top2 = pos <= 1
            qual = top2 or team in qualified_thirds
            group_outcome[team] = (won, top2, qual)

    # Bipartite-match qualifying third groups to the 8 third slots (by allowed set)
    slot_assign = _match_thirds(qualifying_third_groups)
    if slot_assign is None:
        # Fallback: arbitrary valid-ish assignment (rare)
        slot_assign = dict(zip(sorted(THIRD_SLOTS), sorted(qualifying_third_groups)))

    def resolve(slot: str) -> str:
        pos, grp = slot[0], slot[1:]
        if pos == "1":  return standings[grp][0]
        if pos == "2":  return standings[grp][1]
        return ""  # third handled separately

    # Build R32 fixtures
    r32_teams: dict[int, tuple[str, str]] = {}
    for m, (sa, sb) in R32.items():
        ta = third_team_by_group[slot_assign[m]] if sa.startswith("3:") else resolve(sa)
        tb = third_team_by_group[slot_assign[m]] if sb.startswith("3:") else resolve(sb)
        r32_teams[m] = (ta, tb)

    def winner(ta: str, tb: str) -> str:
        w, ga, gb = play(elo.get(ta, ELO_START), elo.get(tb, ELO_START), scale, knockout=True)
        goals_acc[ta] += ga; goals_acc[tb] += gb
        return ta if w == 0 else tb

    r32_w = {m: winner(*r32_teams[m]) for m in R32}
    r16_w = [winner(r32_w[a], r32_w[b]) for a, b in R16]
    qf_w  = [winner(r16_w[a], r16_w[b]) for a, b in QF]
    sf_w  = [winner(qf_w[a], qf_w[b])   for a, b in SF]
    champ = winner(sf_w[0], sf_w[1])
    finalists = (sf_w[0], sf_w[1])
    return champ, finalists, goals_acc, group_outcome


def _match_thirds(groups_set: set[str]) -> dict[int, str] | None:
    """Assign each qualifying third group to a slot within its allowed set."""
    slots = list(THIRD_SLOTS)
    assign: dict[int, str] = {}
    used: set[str] = set()

    def bt(i: int) -> bool:
        if i == len(slots):
            return len(used) == len(groups_set)
        slot = slots[i]
        for g in groups_set:
            if g not in used and g in THIRD_SLOTS[slot]:
                assign[slot] = g; used.add(g)
                if bt(i + 1):
                    return True
                used.discard(g); del assign[slot]
        # also allow leaving slot empty only if more slots than groups (8==8 here)
        return False

    return assign if bt(0) else None


# ── Golden Boot from simulated team goals ─────────────────────────────────────

def compute_golden_boot(
    team_goals: dict[str, "np.ndarray"],
    shares: dict[str, list[tuple[str, float]]],
    n: int,
) -> tuple[list[dict], float]:
    """
    Distribute each team's simulated tournament goals among its players via a
    multinomial draw on the recency-weighted shares (sum of per-match
    multinomials with equal p == one tournament-level multinomial). The
    "other" bucket (unlisted players + own goals) competes in the argmax, so a
    named player's win probability isn't inflated; sims where "other" tops the
    list are reported as field_pct.

    Returns ([{player, team, gb_pct, exp_goals, p4plus}, ...] top 25, field_pct).
    """
    cols: list[tuple[str, str | None]] = []   # (team, player | None=field pseudo-player)
    mats: list[np.ndarray] = []
    for team, garr in team_goals.items():
        plist = shares.get(team) or []
        p = [s for _, s in plist]
        other = max(0.0, 1.0 - sum(p))
        # Split the residual share across OTHER_SPLIT pseudo-players so each
        # competes individually — approximates "the best unlisted player".
        pvals = np.array(p + [other / OTHER_SPLIT] * OTHER_SPLIT, dtype=float)
        pvals /= pvals.sum()
        mats.append(RNG.multinomial(garr, pvals))          # (n, k+OTHER_SPLIT)
        cols.extend([(team, name) for name, _ in plist] + [(team, None)] * OTHER_SPLIT)

    M = np.hstack(mats)                                     # (n, total_cols)
    # Random tie-break: noise < 1 never reorders distinct integer tallies.
    win_idx = np.argmax(M + RNG.random(M.shape) * 0.5, axis=1)
    wins = np.bincount(win_idx, minlength=len(cols))

    players: list[dict] = []
    field_wins = 0
    for i, (team, name) in enumerate(cols):
        if name is None:
            field_wins += int(wins[i])
            continue
        players.append({
            "player":    name,
            "team":      team,
            "gb_pct":    round(int(wins[i]) / n, 4),
            "exp_goals": round(float(M[:, i].mean()), 2),
            "p4plus":    round(float((M[:, i] >= 4).mean()), 4),
        })
    players.sort(key=lambda r: (-r["gb_pct"], -r["exp_goals"]))
    return players[:25], round(field_wins / n, 4)


# ── Market odds ───────────────────────────────────────────────────────────────

def fetch_market_winner() -> dict[str, float] | None:
    import requests
    key = os.getenv("ODDS_API_KEY", "")
    if not key:
        return None
    try:
        r = requests.get(
            "https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup_winner/odds/",
            params={"apiKey": key, "regions": "eu", "markets": "outrights", "oddsFormat": "decimal"},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[market] fetch failed: {e}")
        return None
    # Average implied prob across bookmakers, then de-vig
    acc: dict[str, list] = defaultdict(list)
    for ev in data:
        for bm in ev.get("bookmakers", []):
            for mk in bm.get("markets", []):
                if mk.get("key") != "outrights":
                    continue
                for o in mk.get("outcomes", []):
                    if o.get("price"):
                        acc[o["name"]].append(1.0 / float(o["price"]))
    if not acc:
        return None
    raw = {team: float(np.mean(v)) for team, v in acc.items()}
    tot = sum(raw.values())
    return {team: p / tot for team, p in raw.items()} if tot else None


# ── Main ──────────────────────────────────────────────────────────────────────

_MARKET_ALIASES = {  # market name → our team name
    "USA": "United States", "Bosnia and Herzegovina": "Bosnia and Herzegovina",
}


def main() -> None:
    ap = argparse.ArgumentParser(description="Monte Carlo WC 2026 simulation")
    ap.add_argument("--sims", type=int, default=20000)
    ap.add_argument("--no-market", action="store_true")
    ap.add_argument("--save-json", action="store_true",
                    help="Write results to backend/data/models/national/wc_simulation.json")
    args = ap.parse_args()

    elo = load_elo()
    played_map, all_pairs, upcoming_pairs = load_wc_2026()
    if len(all_pairs) < 12:
        print(f"Only {len(all_pairs)} WC 2026 group fixtures in the dataset — nothing "
              f"to simulate (tournament not scheduled). Exiting.")
        return
    # Derive groups from ALL fixtures (played + upcoming) so the 12 groups stay
    # intact once results start removing edges from the co-appearance graph.
    groups = derive_groups(all_pairs)
    n_groups = len(groups)
    print(f"Derived {n_groups} groups from {len(all_pairs)} fixtures "
          f"({len(played_map)} already played, {len(upcoming_pairs)} remaining).")
    if played_map:
        print(f"→ Conditioning the projection on {len(played_map)} real result(s).")
    missing = {t for g in groups.values() for t in g if t not in elo}
    if missing:
        print(f"[warn] {len(missing)} team(s) missing Elo (→ {ELO_START}): {sorted(missing)}")

    # Calibrate Elo→goals scale to our trained result model
    try:
        from backend.app.database import SessionLocal
        from backend.app.models.national_prediction import NationalPrediction
        db = SessionLocal()
        rows = db.query(NationalPrediction).filter(
            NationalPrediction.tournament == "FIFA World Cup",
            NationalPrediction.actual_result.is_(None),
        ).all()
        db.close()
        target = float(np.mean([r.home_win_prob for r in rows])) if rows else 0.40
    except Exception:
        target = 0.40
    scale = calibrate_scale(elo, all_pairs, target)
    print(f"Calibrated Elo→goals scale C={scale:.0f} (model mean home-win {target:.1%}).\n")

    champ_ct: Counter = Counter()
    final_ct: Counter = Counter()   # reach final
    sf_ct:    Counter = Counter()   # reach SF (= finalists' SF opponents tracked via finalists only)
    pair_ct:  Counter = Counter()
    win_grp_ct: Counter = Counter()   # finish 1st in group
    top2_ct:    Counter = Counter()   # finish top-2
    qual_ct:    Counter = Counter()   # qualify (top-2 or best-third)

    # Golden Boot: per-team tournament-goal arrays across sims
    all_teams = [t for g in groups.values() for t in g]
    player_shares = load_player_shares(set(all_teams))
    team_goals = {t: np.zeros(args.sims, dtype=np.int64) for t in all_teams}

    print(f"Simulating {args.sims:,} tournaments …")
    for i in range(args.sims):
        champ, (fa, fb), gacc, gout = simulate_once(groups, elo, scale, played_map)
        champ_ct[champ] += 1
        final_ct[fa] += 1; final_ct[fb] += 1
        pair_ct[tuple(sorted((fa, fb)))] += 1
        for t, g in gacc.items():
            team_goals[t][i] = g
        for t, (won, top2, qual) in gout.items():
            if won:  win_grp_ct[t] += 1
            if top2: top2_ct[t] += 1
            if qual: qual_ct[t] += 1

    gb_players: list[dict] = []
    gb_field_pct = 0.0
    if player_shares:
        gb_players, gb_field_pct = compute_golden_boot(team_goals, player_shares, args.sims)

    n = args.sims
    print("\n══════════ WINNER PROBABILITY (our model) ══════════")
    print(f"{'Team':<24}{'Win%':>7}{'Final%':>9}")
    market = None if args.no_market else fetch_market_winner()
    for team, c in champ_ct.most_common(15):
        print(f"{team:<24}{c/n:>6.1%}{final_ct[team]/n:>9.1%}")

    print("\n══════════ MOST-LIKELY FINAL PAIRING ══════════")
    for (a, b), c in pair_ct.most_common(8):
        print(f"  {a} vs {b:<22}{c/n:>6.1%}")

    if gb_players:
        print("\n══════════ GOLDEN BOOT (top scorer) ══════════")
        print(f"{'Player':<28}{'Team':<18}{'GB%':>6}{'xGoals':>8}{'P(4+)':>8}")
        for p in gb_players[:15]:
            print(f"{p['player']:<28}{p['team']:<18}{p['gb_pct']:>6.1%}{p['exp_goals']:>8.2f}{p['p4plus']:>8.1%}")
        print(f"{'— field (unlisted players) —':<46}{gb_field_pct:>6.1%}")

    def market_for(team: str) -> float | None:
        if not market:
            return None
        return market.get(team) or market.get("USA" if team == "United States" else team)

    if market:
        print("\n══════════ OUR MODEL vs SHARP MARKET (Win%) ══════════")
        print(f"{'Team':<24}{'Model':>8}{'Market':>8}{'Edge':>8}")
        for team, _ in champ_ct.most_common(15):
            mp = champ_ct[team] / n
            kp = market_for(team) or 0.0
            print(f"{team:<24}{mp:>7.1%}{kp:>8.1%}{mp - kp:>+8.1%}")
        print("\n(Edge = model − market. Large positive = model over-rates vs sharps.)")
    elif not args.no_market:
        print("\n[market] no outright odds available.")

    # ── Persist for the frontend ─────────────────────────────────────────────
    if args.save_json:
        import json
        from datetime import datetime, timezone
        out_path = SNAP_PATH.parent / "wc_simulation.json"
        result = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "n_sims":       n,
            "scale":        scale,
            "model_mean_home_wp": target,
            "played_games": len(played_map),
            "remaining_games": len(upcoming_pairs),
            "has_market":   bool(market),
            "teams": [
                {
                    "team":       team,
                    "win_pct":    round(champ_ct[team] / n, 4),
                    "final_pct":  round(final_ct[team] / n, 4),
                    "market_pct": (round(market_for(team), 4) if market_for(team) else None),
                }
                for team, _ in champ_ct.most_common(24)
            ],
            "pairings": [
                {"team_a": a, "team_b": b, "pct": round(c / n, 4)}
                for (a, b), c in pair_ct.most_common(12)
            ],
            "golden_boot": {
                "players":        gb_players,
                "field_pct":      gb_field_pct,
                "squad_filtered": SQUADS_PATH.exists(),
            },
            "groups": groups,
            "group_standings": {
                gletter: sorted(
                    [
                        {
                            "team":       t,
                            "p_first":    round(win_grp_ct[t] / n, 4),
                            "p_top2":     round(top2_ct[t] / n, 4),
                            "p_qualify":  round(qual_ct[t] / n, 4),
                        }
                        for t in gteams
                    ],
                    key=lambda x: x["p_qualify"], reverse=True,
                )
                for gletter, gteams in groups.items()
            },
        }
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"\n✓ Saved → {out_path}")


if __name__ == "__main__":
    main()
