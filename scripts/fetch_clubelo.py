#!/usr/bin/env python3
"""
Fetch a daily ClubElo rating snapshot → backend/data/clubelo.json.

Why: our internal club Elo only knows teams that appear in our historical CSVs.
A newly-promoted side, a lower-division cup/friendly opponent (e.g. Wrexham) or a
European-qualifier minnow is absent, so `compute_match_features` silently defaults
its Elo to 1500 (ELO_START) — i.e. treats it as a perfectly average team. Seeding
a real rating for those clubs gives the model a strength signal instead of a flat
prior.

The raw ClubElo scale is NOT injected directly — compute_predictions.py fits a
linear ClubElo→our-Elo map on the overlap of teams present in both, so seeded
values land on our trained distribution. That fit is re-run every day, which is
why a change in the upstream scale (see below) needs no coefficient anywhere.

── Source, and why it changed (2026-08-26) ───────────────────────────────────
The CSV API this script used to call — http://api.clubelo.com/YYYY-MM-DD — died
on 2026-08-12. It still completes a TCP handshake in ~70ms and then never answers
the HTTP request; a 120s curl times out over both http and https. Thirteen daily
runs kept the 2026-08-11 snapshot.

The replacement is the clubelo.com home page itself, which is alive and rebuilt.
Reading it needs care, because the obvious parts of it are the wrong parts:

  · The Vega-Lite JSON blob embedded in the page (fields Name/Elo/FedURL/Level —
    exactly the shape this script wants) is only the top-50 chart. /Ranking is
    the same blob with 100. Federation pages like /ENG carry their top 25.
    A scraper built on any of those would look like it worked while seeding
    nothing that matters: `seed_cold_start` exists FOR the clubs no top-N list
    contains — Andorran, Faroese, Gibraltarian, San Marinese qualifier fodder.
  · The full table is in the HTML below the chart: an accordion, one section per
    federation, each an <table class="ast"> of <td class="l">…name…</td>
    <td class="r">Elo</td> rows grouped by "Level N (x teams)" headers. That is
    1,900+ clubs across 90 federations in ONE request — more coverage than the
    dead API had (594), including all four minnow federations.
  · clubelo.com/YYYY-MM-DD 302s to /, and clubelo.com/YYYY-MM-DD/ is a 404, so
    there is no historical fetch any more. Only "now" is available.

Three things about the page's names have to be handled, or the seam matches
nothing (see `_name_variants`): display names are truncated at 16 characters
("Sportivo Trinidense" → "Sportivo Trinide"), the chart and the table disagree
("Bayern München" vs the /Bayern link), and club-type tokens the shared `_slug`
does not strip (KF, PFK, …) sit in front of names our fixtures spell bare
("KF Ballkani" vs our "Ballkani").

Scope: UEFA federations only. The page also carries CONMEBOL/CONCACAF/AFC/CAF
clubs, which the dead API never did, and taking them costs more than it pays —
they collide with clubs we actually predict. "Athletic Club" (ESP) against Brazil's
"Athletic", "Newcastle" (ENG) against Australia's "Newcastle United", "Sporting"
(POR) against Costa Rica's "Sporting FC". Under the loader's drop-on-ambiguity
rule those collisions would silently delete Bilbao, Newcastle and Sporting CP
from the map. Restricting to UEFA keeps the pre-outage contract and the name
space clean; the cold-start population is European anyway.

Request budget: one unauthenticated GET (~600KB), no key, once per daily run —
same budget as the CSV API it replaces.

Idempotent: rewrites clubelo.json each run. Network failure is non-fatal — the
seeding path treats a missing/stale file as "no fallback" and behaves exactly as
before (flat 1500). See run_daily.sh step 5c.
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts._http_retry import get_with_retry  # noqa: E402

OUT_PATH = ROOT / "backend" / "data" / "clubelo.json"
SOURCE_URL = "https://clubelo.com/"
TIMEOUT = 30

# Cloudflare fronts the site and the default python-requests agent is a common
# thing to challenge. Ask as a browser would; this is one polite GET a day.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml",
}

# The 55 UEFA members, in the page's own three-letter codes. Note these are NOT
# the codes the dead API used — it said FAR/LAT/LIT/ROM/SLK/MOL/MAC/MNT/BHZ where
# the site now says FRO/LVA/LTU/ROU/SVK/MDA/MKD/MNE/BIH — so anything comparing
# an old snapshot's `country` against a new one must translate first.
UEFA_FEDERATIONS = frozenset({
    "ALB", "AND", "ARM", "AUT", "AZE", "BEL", "BIH", "BLR", "BUL", "CRO",
    "CYP", "CZE", "DEN", "ENG", "ESP", "EST", "FIN", "FRA", "FRO", "GEO",
    "GER", "GIB", "GRE", "HUN", "IRL", "ISL", "ISR", "ITA", "KAZ", "KOS",
    "LIE", "LTU", "LUX", "LVA", "MDA", "MKD", "MLT", "MNE", "NED", "NIR",
    "NOR", "POL", "POR", "ROU", "RUS", "SCO", "SMR", "SRB", "SUI", "SVK",
    "SVN", "SWE", "TUR", "UKR", "WAL",
})

# Below this the page did not render the way we parse it (a layout change, a
# Cloudflare interstitial, a truncated response) and the old file is worth more
# than what we just read. ~1,076 UEFA clubs is the steady state.
#
# 400 was too loose to do the job it was written for: the five biggest
# federations alone (ESP+ITA+ENG+GER+FRA) are 452 clubs, so an accordion that
# rendered only its opening sections would clear the floor and overwrite a good
# snapshot with a table missing every minnow — precisely the clubs this seam
# exists to rate. 800 still tolerates real shrinkage (a federation or two
# dropping out) while refusing a partial render.
MIN_CLUBS = 800

# Club-type tokens our shared `_slug` does NOT strip, which the page puts in
# front of (or behind) names our fixtures spell bare. `_name_variants` also
# strips any ≤3-character leading/trailing token generically; this list exists
# for the longer ones. Kept short on purpose — every extra variant is another
# chance to collide with a different club.
_AFFIXES = frozenset({"kf", "nk", "hnk", "gnk", "pfk", "mfk", "fsk", "sfk"})

# Names the page uses that no mechanical rule reaches from ours. Keyed by
# (federation, page name) because the name alone is ambiguous — this is exactly
# the case where it is: Gibraltar's "Lincoln" is our "Lincoln Red Imps FC", and
# England's "Lincoln City" is a different club with the same first word.
_EXTRA_NAMES: dict[tuple[str, str], list[str]] = {
    ("GIB", "Lincoln"): ["Lincoln Red Imps"],
    ("AZE", "Neftçi PFK"): ["Neftchi Baku", "Neftchi"],
}

# ── Page structure ────────────────────────────────────────────────────────────
# One <div class="accordion-item"> per federation; the header links to /XXX, the
# content is a table of club rows interrupted by "Level N" group headers.
_ITEM = re.compile(
    r'<div class="accordion-item">(.*?)(?=<div class="accordion-item">|\Z)', re.S)
_FED = re.compile(r'<div class="accordion-header">\s*<a href="/?([A-Z]{3})"')
_ROW = re.compile(r'<td class="l">(.*?)</td>\s*<td class="r">\s*([-\d.]+)\s*</td>', re.S)
_LEVEL = re.compile(r"<i>\s*Level\s+(\d+)\s*\(")
# The row's cell carries the club twice: a three-letter code for narrow screens
# and the (16-char-truncated) name for wide ones.
_DISPLAY = re.compile(r'<span class="Ast">(.*?)</span>', re.S)
# Clubs with their own page also carry a link, whose slug is the untruncated
# name — "/sportivo-trinidense" behind the displayed "Sportivo Trinide". Many
# clubs, including most of the minnows, have no link at all.
_HREF = re.compile(r'<a href="/([^"/]+)"><span class="NonAst"')
# The site's own current-rating date, e.g. <h1><a href="/2026-08-24/"></a></h1>.
# Two or three days behind today is normal — ratings settle after results do.
_AS_OF = re.compile(r'<h1><a href="/(\d{4}-\d{2}-\d{2})/"')

_TAGS = re.compile(r"<[^>]+>")


def _text(fragment: str) -> str:
    return html_mod.unescape(_TAGS.sub("", fragment)).strip()


# A trailing token that marks a reserve/academy side rather than club-type noise.
# `_name_variants` strips short trailing tokens ("Neftçi PFK" → "Neftçi"); doing
# that to "SL Benfica B" yields "SL Benfica", i.e. an alias that impersonates the
# FIRST TEAM. Five such aliases shipped in the 2026-08-24 snapshot — slbenfica,
# sportingcp, sdeibar, udalmeria, cdalaves each resolved to the B side's rating —
# and they were invisible only because we spell those clubs without the prefix.
_RESERVE_TOKEN = re.compile(r"^(?:II|III|B|C|U1\d|U2\d|Res)$", re.IGNORECASE)


def _name_variants(name: str, href: str | None, country: str) -> list[str]:
    """Every spelling of one club worth indexing, best first.

    The first two are authoritative (what the page displays, and the club's own
    URL); the rest are derived guesses that only get used for a slug the
    authoritative names did not already claim — see `load_clubelo`.
    """
    primary = [name]
    if href:
        # "/santos-fc_2" — the _N suffix is the site disambiguating two clubs
        # that would otherwise share a URL, not part of the name.
        primary.append(re.sub(r"_\d+$", "", href).replace("-", " "))

    derived: list[str] = []
    for base in primary:
        tokens = base.split()
        if len(tokens) < 2:
            continue
        # "KF Ballkani" → "Ballkani", "Neftçi PFK" → "Neftçi". Short tokens are
        # club-type noise far more often than they are the name.
        if len(tokens[0]) <= 3 or tokens[0].lower() in _AFFIXES:
            derived.append(" ".join(tokens[1:]))
        if ((len(tokens[-1]) <= 3 or tokens[-1].lower() in _AFFIXES)
                and not _RESERVE_TOKEN.match(tokens[-1])):
            derived.append(" ".join(tokens[:-1]))
    derived.extend(_EXTRA_NAMES.get((country, name), ()))

    out: list[str] = []
    for v in primary + derived:
        v = v.strip()
        if v and v not in out:
            out.append(v)
    return out


_RESERVE_SUFFIX = re.compile(r"\s+(?:II|III|B|C|U1\d|U2\d|Res)$")


def _reserve_names(clubs: dict[str, dict]) -> set[str]:
    """Names that are a first team's reserve/academy side.

    ClubElo rates "Dortmund II", "Jong PSV", "Betis B" alongside their first
    teams. We never predict them, and they actively hurt: "Betis B" reduces to
    the same slug as "Betis", which under drop-on-ambiguity costs us Betis.

    The test is deliberately relational, not a name pattern — a name only counts
    as a reserve side when the first team it names is ALSO in the table, in the
    same federation. Willem II is a first team in the Eredivisie and there is no
    "Willem" above it, so it stays.

    The comparison is on SLUGS, and on every spelling of each sibling, because
    the page does not name the two sides consistently: it lists the first team as
    "Benfica" but its reserves as "SL Benfica B", "Sporting"/"Sporting CP B",
    "Eibar"/"SD Eibar B", "Almería"/"UD Almería B", "Alavés"/"CD Alavés B",
    "Celta"/"RC Celta B", "Milan"/"AC Milan II", "Porto"/"FC Porto B". Raw string
    equality missed all twelve of them, so they stayed in the table and their
    aliases went on to claim slugs the first teams never spelled that way.
    """
    from backend.app.ml.clubelo import _slug

    # Every slug any sibling answers to, per federation. Built from the same
    # `_name_variants` the entries themselves get, because this runs BEFORE the
    # aka lists are attached — reading info["aka"] here would see nothing.
    by_fed: dict[str, set[str]] = {}
    by_fed_names: dict[str, set[str]] = {}
    for name, info in clubs.items():
        known = by_fed.setdefault(info["country"], set())
        by_fed_names.setdefault(info["country"], set()).add(name)
        for variant in _name_variants(name, info.get("href"), info["country"]):
            v = _slug(variant)
            if v:
                known.add(v)

    out: set[str] = set()
    for name, info in clubs.items():
        siblings = by_fed[info["country"]]
        base = None
        if name.startswith("Jong "):
            base = name[len("Jong "):]
        else:
            m = _RESERVE_SUFFIX.search(name)
            if m:
                base = name[:m.start()]
        if not base or base == name:
            continue
        # Two independent tests, because each catches what the other cannot.
        #
        # Raw name equality is what the original rule used, and it is still the
        # only thing that reaches "Athletic Club B": `_slug` treats both
        # "athletic" and "club" as noise, so the base slugs to the empty string
        # and no slug comparison can ever match it.
        if base in by_fed_names[info["country"]]:
            out.add(name)
            continue
        # Slugged variants catch the reverse case — the page naming the two
        # sides differently ("Benfica" but "SL Benfica B", "Sporting" but
        # "Sporting CP B"), which raw equality missed for all twelve of them.
        candidates = {_slug(v) for v in _name_variants(base, None, info["country"])}
        candidates.discard("")
        if candidates & siblings:
            out.add(name)
    return out


def parse_snapshot(page: str) -> tuple[str | None, dict[str, dict]]:
    """Parse the clubelo.com home page → (as_of, {club: {...}}).

    Pure: no network. `as_of` is the site's own rating date, None if the page
    does not carry one. Values are {"elo", "country", "level", "aka"}.
    """
    raw: dict[str, dict] = {}
    for item in _ITEM.findall(page):
        fed_m = _FED.search(item)
        if not fed_m:
            # The confederation roll-ups (Europe, Africa, …) have no federation
            # link and list national sides, not clubs.
            continue
        country = fed_m.group(1)
        if country not in UEFA_FEDERATIONS:
            continue

        level = 0
        for chunk in item.split("<tr>"):
            level_m = _LEVEL.search(chunk)
            if level_m:
                level = int(level_m.group(1))
                continue
            row_m = _ROW.search(chunk)
            if not row_m:
                continue
            cell, elo_raw = row_m.group(1), row_m.group(2)
            name_m = _DISPLAY.search(cell)
            if not name_m:
                continue
            name = _text(name_m.group(1))
            if not name:
                continue
            try:
                elo = float(elo_raw)
            except ValueError:
                continue
            href_m = _HREF.search(cell)
            # A club listed twice (it happens across level groups) keeps its
            # higher rating, as the CSV parser this replaces did.
            if name in raw and raw[name]["elo"] >= elo:
                continue
            raw[name] = {"elo": round(elo, 2), "country": country,
                         "level": level, "href": href_m.group(1) if href_m else None}

    for name in _reserve_names(raw):
        del raw[name]

    out: dict[str, dict] = {}
    for name, info in raw.items():
        # aka excludes the key itself; the loader indexes the key separately.
        aka = [v for v in _name_variants(name, info["href"], info["country"])
               if v != name]
        entry = {"elo": info["elo"], "country": info["country"],
                 "level": info["level"]}
        if aka:
            entry["aka"] = aka
        out[name] = entry

    as_of_m = _AS_OF.search(page)
    return (as_of_m.group(1) if as_of_m else None), out


def fetch_snapshot() -> tuple[str | None, dict[str, dict]]:
    """One GET to clubelo.com, parsed. Raises on transport failure."""
    resp = get_with_retry(SOURCE_URL, timeout=TIMEOUT, headers=HEADERS)
    resp.raise_for_status()
    return parse_snapshot(resp.text)


def _staleness() -> str:
    """One line on the snapshot we are falling back to, and how old it is."""
    try:
        payload = json.loads(OUT_PATH.read_text())
        as_of = date.fromisoformat(payload["as_of"])
    except Exception:  # noqa: BLE001
        return "no previous snapshot on disk — cold-start seeding is off entirely."
    age = (date.today() - as_of).days
    return (f"keeping the {as_of} snapshot ({payload.get('count', '?')} clubs), "
            f"now {age} day(s) old.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--html", type=Path,
                    help="parse a saved copy of the page instead of fetching "
                         "(offline debugging; writes the snapshot as usual)")
    ap.add_argument("date", nargs="?",
                    help="accepted for compatibility and ignored — clubelo.com "
                         "no longer serves historical snapshots")
    args = ap.parse_args()
    if args.date:
        print(f"[warn] ignoring date '{args.date}': clubelo.com redirects every "
              f"/YYYY-MM-DD to the current ratings.")

    try:
        if args.html:
            as_of, snap = parse_snapshot(args.html.read_text(encoding="utf-8"))
        else:
            as_of, snap = fetch_snapshot()
    except Exception as e:  # noqa: BLE001 — non-fatal by design
        print(f"[error] ClubElo fetch failed ({type(e).__name__}: {e}). "
              f"Leaving {OUT_PATH.name} untouched.")
        # How stale the file we are keeping already is. Without this the log
        # line is identical on day 1 and day 14 of an upstream outage, and the
        # snapshot quietly ages out of usefulness — api.clubelo.com stopped
        # answering on 2026-08-12 and nothing said so for thirteen runs.
        print(f"  {_staleness()}")
        return 1

    if len(snap) < MIN_CLUBS:
        print(f"[warn] only {len(snap)} UEFA clubs parsed (want ≥{MIN_CLUBS}) — "
              f"refusing to overwrite. The page layout most likely changed; "
              f"re-check the accordion selectors in parse_snapshot().")
        print(f"  {_staleness()}")
        return 1

    today = date.today().isoformat()
    if as_of is None:
        print("[warn] no rating date on the page — recording today's instead.")
        as_of = today

    payload = {"as_of": as_of, "fetched_on": today, "source": SOURCE_URL,
               "count": len(snap), "clubs": snap}
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Write-then-rename: a plain write_text truncates the file first, so a crash
    # or a full disk mid-write leaves a half-written JSON that the loader can
    # only read as "no ratings at all". os.replace is atomic within a
    # filesystem, so readers see either the old snapshot or the new one.
    tmp = OUT_PATH.with_suffix(OUT_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=0))
    os.replace(tmp, OUT_PATH)
    feds = len({c["country"] for c in snap.values()})
    print(f"✓ ClubElo snapshot (rated {as_of}, fetched {today}): "
          f"{len(snap)} clubs across {feds} federations → {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
