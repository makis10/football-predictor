"""
Ingest per-team, per-fixture CLUB statistics (corners + cards + shots) from
API-Football into team_match_stats — the foundation for club team props, so
club match pages reach parity with the national ones.

Team-id resolution is LEAGUE-BASED (one /teams?league&season call per league,
not per-team name search): far cheaper and unambiguous. API-Football names are
matched to our DB names via a slug + a small override table; unmatched teams are
logged so overrides can be added.

Budget-aware. Idempotent (unique fixture_id+team; done fixtures skipped).

Usage:
  docker compose exec backend python scripts/fetch_club_team_stats.py --days-ahead 5 --last 8
  docker compose exec backend python scripts/fetch_club_team_stats.py --refresh-ids
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts._http_retry import QuotaExhausted, get_with_retry  # noqa: E402
from scripts.team_resolver import COMMON_ALIASES, is_youth_side  # noqa: E402

API_BASE = "https://v3.football.api-sports.io"
API_KEY  = os.getenv("API_SPORTS_KEY", "")
HEADERS  = {"x-apisports-key": API_KEY}
ID_CACHE = ROOT / "backend" / "data" / "models" / "club_team_ids.json"
# our DB name → the exact name API-Football uses (= the name stored in
# team_match_stats / player_match_stats rows). Learned automatically from
# fixture responses; consumed by club_props._api_name so the read side never
# needs slug guessing for teams we ingest.
NAME_MAP = ROOT / "backend" / "data" / "models" / "club_name_map.json"

# our league code → API-Football league id.
#
# Read from odds_analysis_service instead of restating it: this copy was missing
# the twelve leagues added on 2026-07-30, so every one of their clubs fell
# through to the per-team /teams?search fallback — 177 search calls in a run
# that normally makes 54, and the ones that still missed showed up as 50
# "no API id" alerts. One league sweep costs a single request and resolves the
# whole division.
from backend.app.ml.odds_analysis_service import (  # noqa: E402
    _LEAGUE_API_SPORTS_ID, LEAGUE_COUNTRY,
)

LEAGUE_IDS = dict(_LEAGUE_API_SPORTS_ID)

# our DB name → API-Football name. Imported, NOT redefined: this table lived
# here AND in club_props.py, and the copies drifted — the July 2026 expansion
# was added only here, so stats were written for Sion/Thun/LASK/Rakow that the
# match page then couldn't find. One table, both directions.
from backend.app.ml.club_props import NAME_OVERRIDES  # noqa: E402


def _slug(name: str) -> str:
    import re
    import unicodedata
    s = unicodedata.normalize("NFKD", (name or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _search_terms(our: str, target: str) -> list[str]:
    """Query strings to try against /teams?search, best first.

    The endpoint 400s on anything but alphanumerics and spaces ("Athletico-PR")
    and matches on substrings, so the stripped API name can still miss
    ("1 FC Nurnberg" → 0 results) where the short name hits. Acceptance is
    still gated on the slug check below, so a loose query is safe.
    """
    import re
    import unicodedata
    terms = []
    for cand in (target, our):
        s = unicodedata.normalize("NFKD", (cand or "")).encode("ascii", "ignore").decode("ascii")
        s = re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9 ]", " ", s)).strip()
        if len(s) >= 3 and s not in terms:
            terms.append(s)
    return terms


class Budget:
    def __init__(self, cap): self.cap, self.used = cap, 0
    def ok(self): return self.used < self.cap
    def hit(self): self.used += 1


def _get(path, params, budget):
    budget.hit()
    r = get_with_retry(f"{API_BASE}{path}", headers=HEADERS, params=params, timeout=20)
    r.raise_for_status()
    body = r.json()
    errs = body.get("errors")
    # API-Football signals quota/plan errors as HTTP 200 + an errors dict —
    # without this check an exhausted quota silently looks like "0 fixtures".
    if errs:
        if isinstance(errs, dict) and "requests" in errs:
            raise QuotaExhausted(f"[fatal] API-Football daily quota exhausted: {errs['requests']}")
        raise RuntimeError(f"API-Football error: {errs}")
    return body



def _to_int(v):
    try:
        return int(str(v).replace("%", "")) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


_HISTORY_COUNTRY: dict[str, str] | None = None


def _country_from_history(team: str) -> str:
    """The country a club plays in according to the TRAINING data.

    The fixture league is the first source, but a club whose only upcoming
    match is a friendly has no country there — ClubFriendly draws from
    everywhere. That is how Brazil's Athletic Club, of Serie B, was searched
    unfiltered and cached as Athletic Bilbao, id 531. The CSVs know which
    league it plays; this reads that.

    A club appearing in more than one country's files gets no answer rather
    than a guess.
    """
    global _HISTORY_COUNTRY
    if _HISTORY_COUNTRY is None:
        import collections
        import csv
        import glob

        from backend.app.ml.league_registry import LEAGUE_COUNTRY_TIER

        seen: dict[str, set[str]] = collections.defaultdict(set)
        raw = os.path.join(ROOT, "backend", "data", "raw")
        for path in glob.glob(os.path.join(raw, "*.csv")):
            league = os.path.basename(path)[:-4].rpartition("_")[0]
            entry = LEAGUE_COUNTRY_TIER.get(league)
            if not entry:
                continue
            with open(path, newline="", encoding="latin-1") as fh:
                reader = csv.DictReader(fh)
                cols = reader.fieldnames or []
                home = "home_team" if "home_team" in cols else "HomeTeam"
                away = "away_team" if "away_team" in cols else "AwayTeam"
                if home not in cols or away not in cols:
                    continue
                for row in reader:
                    for name in (row.get(home), row.get(away)):
                        if name:
                            seen[name.strip()].add(entry[0])
        _HISTORY_COUNTRY = {n: next(iter(cs)) for n, cs in seen.items() if len(cs) == 1}
    return _HISTORY_COUNTRY.get(team, "")


# ── Country equivalence ──────────────────────────────────────────────────────
# The guard below compares the country API-Football reports against the country
# our training data says a club plays in. Those are two different vocabularies,
# and a raw `!=` rejected ten correctly-identified clubs every run: we write
# "Czechia", the API writes "Czech-Republic"; ours is "NMacedonia", theirs is
# "Macedonia". Sparta Praha, Jablonec, Hradec Králové, Shkendija, KI Klaksvik
# and NSÍ Runavík were all thrown away on spelling alone.
_COUNTRY_ALIASES = {
    "czech-republic": "czechia",
    "macedonia": "nmacedonia",
    "north-macedonia": "nmacedonia",
    "faroe-islands": "faroeislands",
    "northern-ireland": "northernireland",
    "bosnia-and-herzegovina": "bosnia",
    "republic-of-ireland": "ireland",
}

# Clubs that legitimately play outside their own country. The guard exists to
# stop a same-name club abroad being mistaken for ours ("Porto" of Brazil), and
# for that it has to be strict — but these are the real exceptions, and without
# them Cardiff and Swansea, who have played in the English pyramid for decades,
# were rejected as impostors.
_PLAYS_ABROAD = {
    ("wales", "england"),          # Cardiff, Swansea, Wrexham
    ("liechtenstein", "switzerland"),  # Vaduz
    ("monaco", "france"),
    ("northernireland", "ireland"),    # Derry City
    ("england", "scotland"),           # Berwick Rangers
}


def _country_key(name: str) -> str:
    k = (name or "").strip().lower().replace(" ", "-")
    return _COUNTRY_ALIASES.get(k, k.replace("-", ""))


def _same_country(api_country: str, our_country: str) -> bool:
    """True when the API's country and ours refer to the same football nation.

    Returns True when either side is unknown: the guard should only ever fire on
    a POSITIVE contradiction, never on missing information.
    """
    a, o = _country_key(api_country), _country_key(our_country)
    if not a or not o:
        return True
    return a == o or (a, o) in _PLAYS_ABROAD or (o, a) in _PLAYS_ABROAD


def build_id_cache(our_teams: set[str], season: int, budget: Budget,
                   roster_out: set | None = None, search_missing: bool = True,
                   team_league: dict[str, str] | None = None) -> dict:
    """Map our team names → API-Football team ids, league by league."""
    slug_to_name = {_slug(t): t for t in our_teams}
    override_slug = {_slug(k): _slug(v) for k, v in NAME_OVERRIDES.items()}
    # invert: API-slug we should accept for each our-name
    api_alias = {_slug(v): k for k, v in NAME_OVERRIDES.items()}
    # team_resolver.COMMON_ALIASES already records the same pairs in the other
    # direction (API name → our CSV name) for the fixture feeds. Reuse it rather
    # than restating thirty entries here: after the 2026-07-30 expansion the
    # league sweep was missing AIK, Basel, Hearts, Legia, Göteborg, HJK, LASK …
    # purely because this map didn't know what the other one already did.
    for api_name, our_name in COMMON_ALIASES.items():
        if our_name in our_teams:
            api_alias.setdefault(_slug(api_name), our_name)

    cache: dict[str, int] = {}
    league_roster: set[int] = set()   # every team id seen in a tracked league
    matched, unmatched = set(), []
    for code, lid in LEAGUE_IDS.items():
        if not budget.ok():
            break
        try:
            resp = _get("/teams", {"league": lid, "season": season}, budget).get("response", [])
            # In July/August the new season may not be registered on API-Football
            # yet (empty list) — fall back to the previous season's team list
            # (same team ids, only promoted/relegated sides differ).
            if not resp and budget.ok():
                resp = _get("/teams", {"league": lid, "season": season - 1}, budget).get("response", [])
                if resp:
                    print(f"  [info] /teams {code}: season {season} empty — using {season - 1}")
        except Exception as e:
            print(f"  [warn] /teams {code}: {e}"); continue
        for t in resp:
            api_name = t["team"]["name"]; api_id = t["team"]["id"]
            league_roster.add(api_id)
            if roster_out is not None:
                roster_out.add(api_id)
            aslug = _slug(api_name)
            our = slug_to_name.get(aslug) or api_alias.get(aslug)
            # `slug_to_name` spans every club we hold, not just this league's,
            # so a roster name that collides with a club elsewhere lands on the
            # wrong one: La Liga's "Athletic Club" is Bilbao, and it was being
            # filed against Brazil's Athletic Club of Serie B — the same
            # collision the /teams?search path already guards against.
            if our:
                api_country = (t["team"].get("country") or "").strip()
                our_country = _country_from_history(our)
                if not _same_country(api_country, our_country):
                    print(f"  [skip] {api_name} ({api_country}) is not our "
                          f"{our!r} ({our_country})")
                    continue
                cache[our] = api_id
                matched.add(our)
    # Fallback: /teams?search= for teams outside the tracked leagues (friendly
    # opponents from lower divisions, e.g. Chesterfield, De Graafschap). Only
    # accept a result whose slug matches the target (or its override) exactly —
    # a fuzzy hit on the wrong club would poison the cache.
    for team in sorted(our_teams - matched) if search_missing else []:
        if not budget.ok():
            break
        target = NAME_OVERRIDES.get(team, team)
        tslug = _slug(target)
        hit = None
        for i, term in enumerate(_search_terms(team, target)):
            if not budget.ok():
                break
            try:
                resp = _get("/teams", {"search": term}, budget).get("response", [])
            except Exception as e:
                print(f"  [warn] /teams search '{term}': {e}"); continue
            # Youth, reserve and WOMEN'S sides are different teams at the same
            # club and must never stand in for the senior men's side — their
            # match stats would land on the first team's cards/corners. A
            # /teams?search for "SK Rapid" returns "SK Rapid W" as its ONLY hit,
            # so the single-result shortcut below accepted it without question
            # (and did: the cache pointed SK Rapid at the women's team, CFR Cluj
            # at its reserves).
            resp = [t for t in resp if not is_youth_side(t["team"]["name"])]
            # A club that plays in a league we know belongs to that league's
            # country. Without this the search happily returns "Porto" from
            # BRAZIL for Portugal's Porto, "Milan" from Gambia, "Roma" from
            # Slovenia — all accepted, all wrong, none detectable downstream.
            want_country = (LEAGUE_COUNTRY.get((team_league or {}).get(team, ""))
                            or _country_from_history(team))
            if want_country:
                resp = [t for t in resp
                        if (t["team"].get("country") or "") == want_country]
            hit = next((t for t in resp if _slug(t["team"]["name"]) == tslug), None)
            if hit is None and i == 0 and len(resp) == 1:
                hit = resp[0]  # unambiguous single result for the exact name
            if hit:
                break
        if hit:
            cache[team] = hit["team"]["id"]
            matched.add(team)
            print(f"  [search] {team} → {hit['team']['name']} (id {hit['team']['id']})")

    unmatched = sorted(our_teams - matched)
    print(f"  resolved {len(matched)}/{len(our_teams)} club teams "
          f"({budget.used} API calls).")
    if unmatched:
        print(f"  [unmatched — add to NAME_OVERRIDES] {unmatched[:25]}")
    return cache


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest club team match stats")
    ap.add_argument("--days-ahead", type=int, default=5, help="Upcoming window for target teams")
    ap.add_argument("--last", type=int, default=8, help="Recent finished fixtures per team")
    ap.add_argument("--season", type=int, default=None, help="Season start year (default auto)")
    ap.add_argument("--max-requests", type=int, default=1200)
    ap.add_argument("--refresh-ids", action="store_true", help="Rebuild the team-id cache")
    args = ap.parse_args()

    if not API_KEY:
        print("[error] API_SPORTS_KEY not set."); sys.exit(1)

    season = args.season or (date.today().year if date.today().month >= 7 else date.today().year - 1)

    from sqlalchemy import text
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from backend.app.database import SessionLocal
    from backend.app.models.team_match_stats import TeamMatchStats

    budget = Budget(args.max_requests)
    db = SessionLocal()
    try:
        # Teams playing in the upcoming window (club leagues only).
        hi = (date.today() + timedelta(days=args.days_ahead)).isoformat()
        rows = db.execute(text(
            "SELECT DISTINCT home_team, league FROM matches WHERE home_goals IS NULL "
            "AND match_date BETWEEN :lo AND :hi "
            "UNION SELECT DISTINCT away_team, league FROM matches WHERE away_goals IS NULL "
            "AND match_date BETWEEN :lo AND :hi"
        ), {"lo": date.today().isoformat(), "hi": hi}).fetchall()
        target = sorted({r[0] for r in rows})

        # ── Staleness order, not alphabetical ─────────────────────────────
        # `target` used to be walked A→Z against a 1,200-request cap. At ~9
        # requests per club and ~365 clubs the cap is reached somewhere around
        # "M", so every club later in the alphabet was never reached — not once,
        # on any run. Odense, Paide, SJK, Slovan Bratislava and Valur Reykjavik
        # alerted as "no stored stats" every single morning for exactly that
        # reason, and the alert was right: the data was never coming.
        #
        # Ordering by how stale a club's stats are makes the cap a throttle
        # instead of a wall. Clubs with nothing stored go first, then the
        # longest-untouched; a club that got its stats yesterday goes last and
        # loses nothing, because already-stored fixtures are skipped for free.
        freshness = {
            t: d for t, d in db.execute(text(
                "SELECT team, MAX(match_date) FROM team_match_stats GROUP BY team"
            )).fetchall()
        }
        # "" sorts before any ISO date, so never-seen clubs lead. Within a
        # bucket the order ROTATES by date instead of staying alphabetical:
        # ~150 clubs have nothing stored and share the same "" key, so a
        # stable sort would still walk them A→Z and still stop at the same
        # place every morning — the wall moved, it did not go away. Seeding
        # on the date gives every club its turn within a couple of weeks,
        # and keeps a single run reproducible if it has to be re-run.
        rot = random.Random(date.today().toordinal())
        target.sort(key=lambda t: (freshness.get(t) or "", rot.random()))
        # Only clubs playing in a league we sweep can be checked against a
        # roster; a friendly opponent from an untracked division legitimately
        # has an id that appears in no roster.
        team_league = {t: lg for t, lg in rows if lg in LEAGUE_IDS}
        print(f"{len(target)} club teams with upcoming fixtures.")

        # Team-id cache. `known` is every club we have EVER resolved; `cache` is
        # what we keep. --refresh-ids distrusts the stored ids but must still
        # re-resolve the same clubs, otherwise the cache silently shrinks to
        # whatever happens to have a fixture in the next --days-ahead days:
        # running it on 2026-08-02 cut 530 entries to 303 and turned 5
        # "no API id" alerts into 74.
        known = json.loads(ID_CACHE.read_text()) if ID_CACHE.exists() else {}
        cache = {} if args.refresh_ids else dict(known)
        # Treat null-valued entries as missing too: earlier runs cached
        # unresolved teams as None, which permanently blocked re-resolution
        # (the Greek league outage — see 2026-07-11).
        missing = [t for t in target if cache.get(t) is None]
        # The league sweep runs on EVERY run, not just when something is
        # missing: it is ~26 requests against a 7,500/day plan, and it is the
        # only thing that can catch an id already sitting in the cache pointing
        # at the wrong club. A poisoned entry is never "missing", so gating the
        # sweep on `missing` made the guard below unreachable in normal use —
        # which is exactly how "Milan" spent days pointing at a Gambian club.
        # The EXPENSIVE part (per-team /teams?search for everything the sweep
        # couldn't place) stays conditional.
        roster: set = set()
        resolved = build_id_cache(set(target) | set(known), season, budget, roster,
                                  search_missing=bool(missing or args.refresh_ids),
                                  team_league=team_league)
        # Freshly resolved ids win; anything the sweep couldn't reach this
        # run keeps its previous id rather than vanishing.
        cache = {**known, **cache, **resolved}
        ID_CACHE.parent.mkdir(parents=True, exist_ok=True)
        ID_CACHE.write_text(json.dumps(cache, indent=2, ensure_ascii=False))

        # ── Wrong-club guard ──────────────────────────────────────────────
        # /teams?search matches on name alone, so a club with the SAME NAME
        # in another country is a perfectly good hit and nothing downstream
        # can tell: "Porto" resolved to a Brazilian club, "Milan" to a
        # Gambian one, "Roma" to a Slovenian one, "Lugano" to an Argentinian
        # one. Their stats would simply have been someone else's.
        #
        # Only clubs that PLAY in a league we sweep are checked — a friendly
        # opponent from an untracked division has an id in no roster and
        # that is fine. Free: the sweep already fetched every roster.
        if roster:
            wrong = {t: cache[t] for t, lg in team_league.items()
                     if cache.get(t) and cache[t] not in roster}
            if wrong:
                print(f"  [alert] {len(wrong)} club(s) in a TRACKED league resolved to an "
                      f"id that is in no roster — almost certainly a same-name club "
                      f"abroad. Add a NAME_OVERRIDES entry: {wrong}")

        have = {r[0] for r in db.execute(
            text("SELECT DISTINCT fixture_id FROM team_match_stats")).fetchall()}

        n_fx = n_rows = 0
        name_map: dict[str, str] = {}
        if NAME_MAP.exists():
            try:
                name_map = json.loads(NAME_MAP.read_text())
            except Exception:
                name_map = {}
        for team in target:
            if not budget.ok():
                print("  [budget] cap reached."); break
            tid = cache.get(team)
            if not tid:
                continue
            try:
                fx = _get("/fixtures", {"team": tid, "last": args.last}, budget).get("response", [])
            except Exception as e:
                print(f"  [warn] fixtures {team}: {e}"); continue
            # Learn the exact API-Football spelling for this team (the name the
            # stats rows are stored under) from the fixture header — no extra
            # API credits, keeps club_props._api_name exact instead of fuzzy.
            for f in fx:
                for side in ("home", "away"):
                    t_blk = f["teams"][side]
                    if t_blk["id"] == tid and t_blk.get("name"):
                        if name_map.get(team) != t_blk["name"]:
                            name_map[team] = t_blk["name"]
                        break
                else:
                    continue
                break
            for f in fx:
                if not budget.ok():
                    break
                fid = f["fixture"]["id"]
                if fid in have or f["fixture"]["status"]["short"] not in ("FT", "AET", "PEN"):
                    continue
                try:
                    sresp = _get("/fixtures/statistics", {"fixture": fid}, budget).get("response", [])
                except Exception:
                    continue
                if len(sresp) != 2:
                    continue
                th, ta = f["teams"]["home"], f["teams"]["away"]
                names = {b["team"]["id"]: b["team"]["name"] for b in sresp}
                for block in sresp:
                    bid = block["team"]["id"]
                    st = {s.get("type"): s.get("value") for s in (block.get("statistics") or [])}
                    row = {
                        "fixture_id": fid, "match_date": f["fixture"]["date"][:10],
                        "league_id": f["league"]["id"],
                        "team": names.get(bid, ""), "opponent": names.get(ta["id"] if bid == th["id"] else th["id"], ""),
                        "is_home": bid == th["id"],
                        "corners": _to_int(st.get("Corner Kicks")),
                        "possession": _to_int(st.get("Ball Possession")),
                        "shots_total": _to_int(st.get("Total Shots")),
                        "shots_on": _to_int(st.get("Shots on Goal")),
                        "fouls": _to_int(st.get("Fouls")),
                        "yellow_cards": _to_int(st.get("Yellow Cards")),
                        "red_cards": _to_int(st.get("Red Cards")),
                    }
                    db.execute(pg_insert(TeamMatchStats).values(**row)
                               .on_conflict_do_nothing(constraint="uq_team_match_stats"))
                db.commit()
                have.add(fid); n_fx += 1; n_rows += 2
            print(f"  {team}: {n_fx} fixtures so far  [req {budget.used}]")
        NAME_MAP.write_text(json.dumps(name_map, indent=2, ensure_ascii=False, sort_keys=True))
        print(f"\nDone. {n_fx} new fixtures, {n_rows} rows, {budget.used} API requests. "
              f"Name map: {len(name_map)} teams → {NAME_MAP.name}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
