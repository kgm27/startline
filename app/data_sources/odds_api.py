"""The Odds API client (the-odds-api.com — double-check the hyphenated domain
when signing up; theoddsapi.com is an unauthorized impersonator).

Verified 2026-07-27 against a real free-tier key: fetch_upcoming_events()
returns real NFL games. fetch_player_props() returns the correct shape but
an empty "bookmakers" list for games that are still weeks away — sportsbooks
don't post player prop lines until close to game day, so an empty result
this far out is expected, not a bug. Re-verify closer to a game to see
populated props.

As of 2026-07-28: this single API also covers Underdog/PrizePicks DFS
projections — see the "us_dfs" region below — so there's no separate manual
entry step for those anymore (brief Section 4 was corrected accordingly).
"""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from app.config import get_settings
from app.db import SessionLocal
from app.models import Player, OddsProp, DfsProjection
from app.data_sources.sleeper import fetch_current_week

BASE_URL = "https://api.the-odds-api.com/v4"
SPORT = "americanfootball_nfl"

# The Odds API and Sleeper don't always agree on generational suffixes (e.g.
# "Kenneth Walker III" vs Sleeper's "Kenneth Walker"), which made an exact
# name match silently drop that player from every source everywhere on the
# site. Stripped as a fallback only, after an exact match has already failed.
_NAME_SUFFIX_RE = re.compile(r"\s+(Jr\.?|Sr\.?|II|III|IV)$", re.IGNORECASE)


def _strip_name_suffix(name: str) -> str:
    return _NAME_SUFFIX_RE.sub("", name).strip()


def _find_player(db, player_name: str):
    """Match a player by name, tolerating a generational suffix mismatch
    between data sources. Exact match first (the common, indexed-friendly
    path); only falls back to a suffix-stripped match if that fails."""
    player = db.query(Player).filter(Player.name.ilike(player_name)).first()
    if player:
        return player
    stripped = _strip_name_suffix(player_name)
    if stripped != player_name:
        player = db.query(Player).filter(Player.name.ilike(stripped)).first()
    return player

# Historical odds snapshots are for a fixed past moment, so they never
# change — safe (and cheap) to cache on disk forever. Live endpoints are
# NOT cached here: those genuinely change between calls, and caching them
# would silently serve stale odds instead of the fresh pull a refresh is
# supposed to get. Historical calls cost real credits (180/event), so this
# cache matters — the same test event got re-pulled 3+ times in one session
# before this existed.
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "_cache"


def _cache_get(cache_key: str):
    path = CACHE_DIR / f"{cache_key}.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def _cache_set(cache_key: str, data) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(CACHE_DIR / f"{cache_key}.json", "w") as f:
        json.dump(data, f)


def _safe_key(*parts: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "-", "_".join(parts))


def _short_hash(text: str) -> str:
    """Filesystems cap filenames around 255 bytes — the market list alone
    can blow past that once alternates are included, so long/variable
    components get hashed instead of embedded literally."""
    return hashlib.sha256(text.encode()).hexdigest()[:12]

SPORTSBOOK_PROP_MARKETS = [
    "player_pass_yds",
    "player_rush_yds",
    "player_reception_yds",
    "player_receptions",
    "player_pass_tds",
    "player_pass_interceptions",
    "player_anytime_td",
    "player_tds_over",  # "2+ touchdowns"-style market, distinct from anytime_td
]

# "Alternate" markets post MULTIPLE thresholds per player (e.g. rush yards at
# 24.5, 29.5, 39.5, ... all the way up), Over-only, instead of just the one
# main line — verified 2026-07-29 against real historical data. Together
# with the main line, these let us numerically estimate a real expected
# value from market pricing instead of assuming a distribution shape (CV) —
# see blend.py's threshold-pooling functions.
ALTERNATE_MARKETS = [
    "player_pass_yds_alternate",
    "player_rush_yds_alternate",
    "player_reception_yds_alternate",
    "player_receptions_alternate",
    "player_pass_tds_alternate",
    "player_pass_interceptions_alternate",
]

DFS_FANTASY_MARKET = "player_fantasy_points"
ALL_MARKETS = SPORTSBOOK_PROP_MARKETS + ALTERNATE_MARKETS + [DFS_FANTASY_MARKET]

# anytime_td and tds_over are both priced as a single yes/no-style
# probability (American odds on one outcome) rather than a two-sided
# Over/Under line, but both get stored with an explicit "line" so they slot
# into the same threshold ladder as everything else in blend.py: anytime_td
# is implicitly the "at least 1" (0.5) threshold; tds_over already carries
# its own point value (0.5/1.5/2.5/...) and every threshold it offers is
# kept, not just 1.5 as in an earlier version of this code.

# All four bookmaker keys under the "us_dfs" region — confirmed against
# the-odds-api.com's bookmaker list (2026-07-28). Not all of them post a
# player_fantasy_points market for every player/game (e.g. Pick6 appears to
# be stat-props-only, no combined fantasy score market at all; Betr/Underdog
# sometimes skip specific players) — _ingest_dfs_projections just contributes
# whatever each one actually has, which is the whole point of broadening
# past the two platforms named in the brief: more coverage, no single point
# of failure if one book doesn't list a given player.
DFS_BOOKMAKER_KEYS = {"prizepicks", "underdog", "betr_us_dfs", "pick6"}
DFS_SOURCE_LABELS = {
    "prizepicks": "PrizePicks",
    "underdog": "Underdog",
    "betr_us_dfs": "Betr Picks",
    "pick6": "DraftKings Pick6",
}
REGIONS = "us,us_dfs"


class OddsAPINotConfigured(Exception):
    pass


def _require_key() -> str:
    key = get_settings().odds_api_key
    if not key:
        raise OddsAPINotConfigured(
            "ODDS_API_KEY is not set in .env — sign up at the-odds-api.com and add your key."
        )
    return key


def fetch_upcoming_events() -> list[dict]:
    """List this week's NFL games (needed to look up player props per-event)."""
    key = _require_key()
    resp = httpx.get(
        f"{BASE_URL}/sports/{SPORT}/events",
        params={"apiKey": key},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_near_term_events(days_ahead: int = 8) -> list[dict]:
    """Filters fetch_upcoming_events() down to games starting soon. Player
    props only exist close to game day, and pulling props per-event costs
    credits, so there's no point checking games weeks/months out."""
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=days_ahead)
    near_term = []
    for event in fetch_upcoming_events():
        commence = datetime.fromisoformat(event["commence_time"].replace("Z", "+00:00"))
        if now <= commence <= cutoff:
            near_term.append(event)
    return near_term


def fetch_player_props(event_id: str) -> dict:
    """Player prop + DFS fantasy-points odds for a single game. Costs more
    credits than the main odds feed since it's pulled per-event, and pulling
    two regions (us + us_dfs) roughly doubles the credit cost of a single
    call (credit cost = markets x regions) — see brief Section 4."""
    key = _require_key()
    resp = httpx.get(
        f"{BASE_URL}/sports/{SPORT}/events/{event_id}/odds",
        params={
            "apiKey": key,
            "regions": REGIONS,
            "markets": ",".join(ALL_MARKETS),
            "oddsFormat": "american",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_historical_events(date: str, commence_time_from: str = None, commence_time_to: str = None) -> list[dict]:
    """Lists real NFL games around a past date — needed to get event IDs
    before pulling historical odds for them. Cheap: costs 1 credit total
    (not per-event), 0 if nothing matches. Requires the paid plan.
    Cached to disk — a past snapshot never changes, so a repeat call with
    the same arguments never needs to hit the network again."""
    cache_key = "events_" + _safe_key(date, commence_time_from or "", commence_time_to or "")
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    key = _require_key()
    params = {"apiKey": key, "date": date}
    if commence_time_from:
        params["commenceTimeFrom"] = commence_time_from
    if commence_time_to:
        params["commenceTimeTo"] = commence_time_to
    resp = httpx.get(
        f"{BASE_URL}/historical/sports/{SPORT}/events",
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json().get("data", [])
    _cache_set(cache_key, data)
    return data


def fetch_historical_player_props(event_id: str, date: str) -> dict:
    """Player prop + DFS odds as they stood at a past snapshot time. Requires
    the paid plan. Costs 10 credits per region per market per event — with
    2 regions (us + us_dfs) and 15 markets (ALL_MARKETS: 8 core props + 6
    alternate-line markets + the DFS fantasy-points market), that's 300
    credits per game pulled, far more than the live equivalent. (Verified
    2026-07-29 — this was previously documented as 180 credits/9 markets,
    stale since ALTERNATE_MARKETS was added without updating this count.)

    Cached to disk (data/_cache/) — a past snapshot never changes, so a
    repeat call for the same event/date/markets/regions never needs to pay
    for the same data twice. The cache key includes the current market and
    region list, so if either is ever expanded, that's treated as new data
    and fetched fresh rather than silently reusing an incomplete old cache."""
    cache_key = _safe_key("props", event_id, date, REGIONS, _short_hash(",".join(ALL_MARKETS)))
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    key = _require_key()
    resp = httpx.get(
        f"{BASE_URL}/historical/sports/{SPORT}/events/{event_id}/odds",
        params={
            "apiKey": key,
            "date": date,
            "regions": REGIONS,
            "markets": ",".join(ALL_MARKETS),
            "oddsFormat": "american",
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json().get("data", {})
    _cache_set(cache_key, data)
    return data


def american_odds_to_implied_probability(american_odds: float) -> float:
    """Converts American odds (e.g. -150, +130) to raw implied probability.
    Does NOT remove the vig (bookmaker margin) — that requires normalizing
    both sides of a market together, which we can add once we're pulling
    real two-sided markets."""
    if american_odds < 0:
        return -american_odds / (-american_odds + 100)
    return 100 / (american_odds + 100)


def _ingest_sportsbook_props(db, event_odds: dict, week: int, now: datetime) -> tuple[int, set]:
    """Stores ONE OddsProp row per bookmaker per market per player per
    THRESHOLD — not just whichever book responds first, and not just one
    line per market. Main-line markets (Over+Under, one threshold) and
    alternate-line markets (Over-only, many thresholds) both land here, so
    blend.py can pool every threshold it has data for into one estimate
    instead of trusting a single line. anytime_td and tds_over are treated
    as threshold markets too (0.5 and whatever point tds_over offers), not
    special-cased, so they pool into the same touchdown-count ladder.

    Verified 2026-07-28 against real historical data: the API's outcome
    schema is {"name": "Over"/"Under"/"Yes", "description": "<player name>",
    "price": ..., "point": ...} — the bet side is "name" and the player is
    "description", which is the OPPOSITE of what earlier synthetic tests in
    this codebase assumed. Fixed here; the live /refresh path had the same
    bug and would have silently stored nothing once real games started."""
    stored = 0
    unmatched = set()
    all_prop_markets = set(SPORTSBOOK_PROP_MARKETS) | set(ALTERNATE_MARKETS)

    for bookmaker in event_odds.get("bookmakers", []):
        bookmaker_key = bookmaker.get("key")
        if bookmaker_key in DFS_BOOKMAKER_KEYS:
            continue  # DFS books go through _ingest_dfs_projections instead

        for market in bookmaker.get("markets", []):
            market_key = market.get("key")
            if market_key not in all_prop_markets:
                continue

            if market_key == "player_anytime_td":
                # No "point" field at all — this market IS the "at least 1"
                # (0.5) threshold, just not labeled with one.
                for outcome in market.get("outcomes", []):
                    player_name = outcome.get("description")
                    if not player_name:
                        continue
                    odds = outcome.get("price")
                    player = _find_player(db, player_name)
                    if not player:
                        unmatched.add(player_name)
                        continue
                    _upsert_odds_prop(db, player.id, week, market_key, bookmaker_key, now,
                                       line=0.5, implied_probability=american_odds_to_implied_probability(odds),
                                       odds=odds, under_odds=None)
                    stored += 1
                continue

            # Every other market (main-line yardage/receptions/pass_tds/
            # interceptions, their _alternate variants, and tds_over) is
            # threshold-shaped: pair Over+Under per (player, threshold) so
            # we keep both sides' prices where they exist, but alternates
            # only ever have an Over side and that's fine.
            by_player_threshold = {}
            for outcome in market.get("outcomes", []):
                player_name = outcome.get("description")
                side = outcome.get("name")
                point = outcome.get("point")
                if not player_name or side not in ("Over", "Under") or point is None:
                    continue
                by_player_threshold.setdefault((player_name, point), {})[side] = outcome

            for (player_name, point), sides in by_player_threshold.items():
                over = sides.get("Over")
                if not over:
                    continue  # need at least the Over side for a price at this threshold
                under = sides.get("Under")

                player = _find_player(db, player_name)
                if not player:
                    unmatched.add(player_name)
                    continue

                # Store alternate rows under their base market name so they
                # pool with the main line in blend.py's threshold ladder.
                storage_market_key = market_key.removesuffix("_alternate") if market_key != "player_tds_over" else market_key

                _upsert_odds_prop(db, player.id, week, storage_market_key, bookmaker_key, now,
                                   line=point, implied_probability=None,
                                   odds=over.get("price"),
                                   under_odds=under.get("price") if under else None)
                stored += 1

    return stored, unmatched


def _upsert_odds_prop(db, player_id, week, market_key, bookmaker_key, now,
                       line, implied_probability, odds, under_odds):
    existing = (
        db.query(OddsProp)
        .filter_by(player_id=player_id, week=week, market=market_key, bookmaker=bookmaker_key, line=line)
        .first()
    )
    if existing:
        existing.line = line
        existing.implied_probability = implied_probability
        existing.odds = odds
        existing.under_odds = under_odds
        existing.updated_at = now
    else:
        db.add(OddsProp(
            player_id=player_id,
            week=week,
            market=market_key,
            bookmaker=bookmaker_key,
            line=line,
            implied_probability=implied_probability,
            odds=odds,
            under_odds=under_odds,
            updated_at=now,
        ))


def _ingest_dfs_projections(db, event_odds: dict, week: int, now: datetime) -> tuple[int, set]:
    """Pulls the player_fantasy_points market from the prizepicks/underdog
    bookmakers specifically — these are the DFS pick'em lines that used to
    be entered by hand.

    Verified 2026-07-28 against real historical data: outcome schema is
    {"name": "Over"/"Under", "description": "<player name>"} — player is in
    "description", not "name" (see _ingest_sportsbook_props for the same
    fix). Both DFS books use plain "Over"/"Under" wording, not Underdog's
    consumer-facing "Higher/Lower"."""
    stored = 0
    unmatched = set()

    for bookmaker in event_odds.get("bookmakers", []):
        source = bookmaker.get("key")
        if source not in DFS_BOOKMAKER_KEYS:
            continue

        for market in bookmaker.get("markets", []):
            if market.get("key") != DFS_FANTASY_MARKET:
                continue

            for outcome in market.get("outcomes", []):
                player_name = outcome.get("description")
                if not player_name or outcome.get("name") != "Over":
                    continue  # Under side isn't needed for a point estimate

                player = _find_player(db, player_name)
                if not player:
                    unmatched.add(player_name)
                    continue

                points = outcome.get("point")
                existing = (
                    db.query(DfsProjection)
                    .filter_by(player_id=player.id, source=source, week=week)
                    .first()
                )
                if existing:
                    existing.projected_points = points
                    existing.updated_at = now
                else:
                    db.add(DfsProjection(
                        player_id=player.id,
                        source=source,
                        week=week,
                        projected_points=points,
                        updated_at=now,
                    ))
                stored += 1

    return stored, unmatched


def _ingest_event_odds(db, event_odds: dict, week: int, now: datetime) -> dict:
    """Parses one event's odds into OddsProp + DfsProjection rows. Separated
    from sync_odds so this parsing logic can be unit-tested without a live
    network call."""
    props_stored, props_unmatched = _ingest_sportsbook_props(db, event_odds, week, now)

    dfs_stored, dfs_unmatched = _ingest_dfs_projections(db, event_odds, week, now)

    return {
        "props_stored": props_stored,
        "dfs_stored": dfs_stored,
        "unmatched": props_unmatched | dfs_unmatched,
    }


def sync_odds(db: SessionLocal = None, days_ahead: int = 8) -> dict:
    """Pulls props + DFS projections for every near-term game and stores
    them. Returns counts so the caller (the /refresh route) can report what
    happened — including the normal case where nothing's posted yet."""
    owns_session = db is None
    db = db or SessionLocal()
    try:
        week = fetch_current_week()
        events = fetch_near_term_events(days_ahead)
        now = datetime.now(timezone.utc)
        total_props = 0
        total_dfs = 0
        all_unmatched = set()

        for event in events:
            event_odds = fetch_player_props(event["id"])
            result = _ingest_event_odds(db, event_odds, week, now)
            total_props += result["props_stored"]
            total_dfs += result["dfs_stored"]
            all_unmatched |= result["unmatched"]

        db.commit()
        return {
            "events_checked": len(events),
            "props_stored": total_props,
            "dfs_stored": total_dfs,
            "unmatched": sorted(all_unmatched),
        }
    finally:
        if owns_session:
            db.close()


def sync_historical_odds(
    week: int,
    commence_time_from: str,
    commence_time_to: str,
    snapshot_hours_before_kickoff: float = 2,
    db: SessionLocal = None,
) -> dict:
    """Backfills OddsProp/DfsProjection rows for real past games — e.g. to
    populate a past week with real historical lines for backtesting/UX work.
    Requires the paid plan; historical endpoints 404 on free-tier keys.
    Pulls one props snapshot per event, taken shortly before that game's
    actual kickoff — the closest equivalent to "final pregame line" without
    paying for multiple snapshots per game (each snapshot costs full price,
    300 credits per event at our current market/region count — see
    fetch_historical_player_props)."""
    owns_session = db is None
    db = db or SessionLocal()
    try:
        # The events-list snapshot must be taken BEFORE the games happened,
        # or they no longer show up as "upcoming" as of that snapshot — using
        # commence_time_to here was a bug (returned 0 events) since games in
        # the window had already started by then.
        events = fetch_historical_events(
            date=commence_time_from,
            commence_time_from=commence_time_from,
            commence_time_to=commence_time_to,
        )
        now = datetime.now(timezone.utc)
        total_props = 0
        total_dfs = 0
        all_unmatched = set()
        games = []

        for event in events:
            commence = datetime.fromisoformat(event["commence_time"].replace("Z", "+00:00"))
            snapshot_time = commence - timedelta(hours=snapshot_hours_before_kickoff)
            snapshot_date = snapshot_time.strftime("%Y-%m-%dT%H:%M:%SZ")

            event_odds = fetch_historical_player_props(event["id"], snapshot_date)
            result = _ingest_event_odds(db, event_odds, week, now)
            total_props += result["props_stored"]
            total_dfs += result["dfs_stored"]
            all_unmatched |= result["unmatched"]
            games.append(f"{event.get('away_team')} @ {event.get('home_team')}")

        db.commit()
        return {
            "events_checked": len(events),
            "games": games,
            "props_stored": total_props,
            "dfs_stored": total_dfs,
            "unmatched": sorted(all_unmatched),
        }
    finally:
        if owns_session:
            db.close()
