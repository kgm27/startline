"""Kalshi (kalshi.com) — a CFTC-regulated prediction market, not a
sportsbook. It runs real per-player, per-game threshold contracts (e.g.
"Jonathan Taylor: 110+ rushing yards") that settle on real NFL stats, the
same shape as a sportsbook's alternate-line props.

Two things make this a genuinely different input, not just another
bookmaker: its price IS a probability already (a $0-1 contract price, not
American odds needing conversion), and it's a real two-sided trading
market rather than a book setting a line — the bid/ask spread is its own
margin, already netted out by averaging the two before storage.

Verified 2026-09-05 against the real, live API: the market-listing and
event/market-detail endpoints are public and unauthenticated — no API
key, no account, no per-call cost, unlike The Odds API. Confirmed real
open contracts for Week 1 2026 games (e.g. the Ravens@Colts game) before
writing this.
"""
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.db import SessionLocal
from app.models import OddsProp
from app.name_utils import find_player_by_name

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

# Every Kalshi series that prices one of our tracked stats per player, per
# game. Stored under the SAME market key the corresponding Odds API market
# uses (see MARKET_TO_STAT in app/scoring/blend.py), so a Kalshi price
# pools directly into the same threshold curve as sportsbook lines for
# that stat rather than sitting in a separate, unblended silo.
SERIES_TO_MARKET = {
    "KXNFLPASSYDS": "player_pass_yds",
    "KXNFLRSHYDS": "player_rush_yds",
    "KXNFLRECYDS": "player_reception_yds",
    "KXNFLREC": "player_receptions",
    "KXNFLPASSTDS": "player_pass_tds",
    "KXNFLPASSINT": "player_pass_interceptions",
    "KXNFLANYTD": "player_anytime_td",
}

BOOKMAKER_KEY = "kalshi"


class KalshiRequestFailed(Exception):
    pass


def _get(path: str, **params) -> dict:
    resp = httpx.get(f"{BASE_URL}{path}", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_open_events(series_ticker: str) -> list[dict]:
    """Every currently-open event for one stat series. No date filtering
    here: Kalshi opens/closes a game's markets on its own schedule around
    that game's real date, so "open" already approximates "this week or
    very soon" — the same imprecision the Odds API's own near-term window
    has, just via a different mechanism."""
    return _get("/events", series_ticker=series_ticker, status="open", limit=200).get("events", [])


def fetch_event_markets(event_ticker: str) -> list[dict]:
    """Every per-player market under one event (one game)."""
    return _get("/markets", event_ticker=event_ticker, limit=200).get("markets", [])


def _player_name_from_title(title: str) -> str:
    """"Jonathan Taylor: 110+ rushing yards" -> "Jonathan Taylor". Every
    sampled market title follows this "Name: threshold stat" shape."""
    return title.split(":", 1)[0].strip()


def _midpoint_probability(market: dict) -> Optional[float]:
    """The market's own fair-value estimate: the average of what buyers
    will pay and sellers will accept for the Yes side. Already a real
    probability (Kalshi contracts pay $1 on Yes, $0 on No) — nothing to
    de-vig, the bid/ask spread already IS this market's margin."""
    try:
        bid = float(market["yes_bid_dollars"])
        ask = float(market["yes_ask_dollars"])
    except (KeyError, TypeError, ValueError):
        return None
    if bid <= 0 and ask <= 0:
        return None  # no real quotes yet, not a $0 probability
    return (bid + ask) / 2


def _upsert_kalshi_prop(db, player_id, week, market_key, line, implied_probability, now):
    existing = (
        db.query(OddsProp)
        .filter_by(player_id=player_id, week=week, market=market_key, bookmaker=BOOKMAKER_KEY, line=line)
        .first()
    )
    if existing:
        existing.implied_probability = implied_probability
        existing.updated_at = now
    else:
        db.add(OddsProp(
            player_id=player_id,
            week=week,
            market=market_key,
            bookmaker=BOOKMAKER_KEY,
            line=line,
            implied_probability=implied_probability,
            odds=None,
            under_odds=None,
            updated_at=now,
        ))


def sync_kalshi(week: int, db: SessionLocal = None) -> dict:
    """Pulls every mapped series' currently-open per-player contracts and
    stores them. Free — no credits, no key — so this can run as often as
    is useful without a cost decision, unlike sync_odds()."""
    owns_session = db is None
    db = db or SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        stored = 0
        unmatched = set()
        events_checked = 0

        for series_ticker, market_key in SERIES_TO_MARKET.items():
            try:
                events = fetch_open_events(series_ticker)
            except httpx.HTTPError:
                continue  # a bad response for one series shouldn't sink the whole refresh
            for event in events:
                events_checked += 1
                try:
                    markets = fetch_event_markets(event["event_ticker"])
                except httpx.HTTPError:
                    # One flaky event (of what can be 80+ sequential calls
                    # in a single refresh) shouldn't lose everything already
                    # fetched — confirmed 2026-09-05 this was a real gap:
                    # an unhandled failure here raised all the way out and
                    # rolled back the whole sync, since it only committed
                    # once at the very end.
                    continue
                for market in markets:
                    if market.get("primary_participant_key") != "football_player":
                        continue  # a team- or game-level market slipped into this series
                    if market.get("strike_type") != "greater":
                        continue  # only "X+" (Over-shaped) contracts match our survival-curve math
                    line = market.get("floor_strike")
                    if line is None:
                        continue
                    probability = _midpoint_probability(market)
                    if probability is None:
                        continue
                    player_name = _player_name_from_title(market.get("title", ""))
                    player = find_player_by_name(db, player_name)
                    if not player:
                        unmatched.add(player_name)
                        continue
                    _upsert_kalshi_prop(db, player.id, week, market_key, line, probability, now)
                    stored += 1

            # Commit after each series rather than only once at the very
            # end, so a failure partway through (e.g. the next series'
            # event-list call raising) still keeps whatever already
            # succeeded instead of rolling it all back.
            db.commit()

        return {"events_checked": events_checked, "props_stored": stored, "unmatched": sorted(unmatched)}
    finally:
        if owns_session:
            db.close()
