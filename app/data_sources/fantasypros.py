"""FantasyPros Expert Consensus Rankings (ECR) API client
(fantasypros.com/api-data — api.fantasypros.com).

Verified 2026-09-05 against a real premium-tier key: the endpoint shape
this file previously used was wrong (week as a PATH segment, e.g.
".../nfl/15/consensus-rankings", with no year at all). That silently
returned the same stale preseason data no matter what week was
requested — which looked at the time like a free-tier limitation (the
response even carried "tier": "free"), but was actually just an invalid
path. Confirmed by testing three different (year, week) combinations on
the now-upgraded premium key: the real shape is
".../nfl/{year}/consensus-rankings" with week as a query param, and it
correctly returns real, distinct data for the current week (2026 week
1), an empty result for a future week with no rankings published yet
(2026 week 3), and real historical data for a past week (2025 week 15,
last_updated "12/14", Christian McCaffrey #1 RB — matching this
project's own Week 15 2025 backtest)."""
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.config import get_settings
from app.db import SessionLocal
from app.models import ExpertRank
from app.name_utils import find_player_by_name

BASE_URL = "https://api.fantasypros.com/public/v2/json/nfl"

# Confirmed with FantasyPros support 2026-09-06: the premium plan is capped
# at 500 requests/day (and 1/second - see MIN_CALL_INTERVAL_SECONDS below).
# A day of debugging this exact rate limit - diagnostics, reproductions,
# local verification runs, several production attempts - burned well past
# what a normal refresh needs before that limit was even confirmed, which
# is what this guard exists to prevent from happening again. Tracked on
# disk (not just in memory) specifically so a fresh `python3 -c ...` test
# script - a new process, starting from zero - can't blow through this the
# same way: every caller on this machine, local debugging included, shares
# the same count. It can't coordinate with a separate deploy (Render and a
# laptop don't share a disk), so this protects each environment against
# itself, not both at once.
DAILY_CALL_BUDGET = 450  # the real cap is 500; this leaves headroom for a manual check
_CALL_LOG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "_cache" / "fantasypros_call_log.json"

# FantasyPros scoring-format codes
SCORING_FORMAT_CODES = {
    "standard": "STD",
    "half_ppr": "HALF",
    "full_ppr": "PPR",
}

POSITIONS = ("QB", "RB", "WR", "TE")

# Confirmed 2026-09-05: pulling all 3 scoring formats back-to-back (12
# calls total - 4 positions x 3 formats, one refresh) started returning
# 429 Too Many Requests partway through, after the first several calls
# succeeded. A fixed pause before every call keeps this well clear of
# whatever that limit actually is; a raised RateLimited on a call that's
# still throttled after one retry lets the caller decide whether to give
# up on the remaining positions/formats for this refresh rather than
# losing everything already fetched (each scoring format's rows are
# committed as their own unit, not all three at once).
MIN_CALL_INTERVAL_SECONDS = 2.0

_POS_RANK_NUMBER_RE = re.compile(r"\d+")


class RateLimited(Exception):
    pass


class DailyBudgetExceeded(Exception):
    pass


class FantasyProsNotConfigured(Exception):
    pass


def _load_call_log() -> tuple[str, int]:
    """(date, calls made that day). Only today's count is ever kept - a
    stale date's count is simply discarded, same one-key pattern main.py's
    _ASK_SPEND already uses for the Ask feature's own daily budget."""
    if not _CALL_LOG_PATH.exists():
        return "", 0
    try:
        data = json.loads(_CALL_LOG_PATH.read_text())
        return data.get("date", ""), data.get("count", 0)
    except (json.JSONDecodeError, OSError):
        return "", 0


def _record_call() -> int:
    """Increments (and persists) today's call count. Returns the new
    total. Called BEFORE every real request, not after, so a call that's
    about to blow the budget is refused instead of just counted."""
    today = datetime.now(timezone.utc).date().isoformat()
    logged_date, count = _load_call_log()
    count = count + 1 if logged_date == today else 1
    _CALL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CALL_LOG_PATH.write_text(json.dumps({"date": today, "count": count}))
    return count


def _require_key() -> str:
    key = get_settings().fantasypros_api_key
    if not key:
        raise FantasyProsNotConfigured(
            "FANTASYPROS_API_KEY is not set in .env — sign up at fantasypros.com/api-data and add your key."
        )
    return key


def fetch_consensus_rankings(year: int, week: int, position: str, scoring_format: str = "half_ppr") -> dict:
    """Weekly expert consensus rank for one position (QB/RB/WR/TE)."""
    key = _require_key()
    scoring_code = SCORING_FORMAT_CODES.get(scoring_format, "HALF")
    resp = httpx.get(
        f"{BASE_URL}/{year}/consensus-rankings",
        params={"position": position, "scoring": scoring_code, "type": "weekly", "week": week},
        headers={"x-api-key": key},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _budget_checked_call(year: int, week: int, position: str, scoring_format: str) -> dict:
    """The one place that actually spends a call against the daily budget -
    both the first attempt and the post-429 retry go through this, so
    neither one is invisible to the counter."""
    calls_today = _record_call()
    if calls_today > DAILY_CALL_BUDGET:
        raise DailyBudgetExceeded(
            f"{calls_today} FantasyPros calls already made today (budget {DAILY_CALL_BUDGET}, "
            f"real plan cap 500) - refusing to make more."
        )
    return fetch_consensus_rankings(year, week, position, scoring_format)


def _fetch_paced(year: int, week: int, position: str, scoring_format: str) -> dict:
    """fetch_consensus_rankings(), paced to stay clear of the rate limit,
    budget-checked to stay clear of the daily cap, and given one retry
    (with a longer pause) if it's still tripped."""
    time.sleep(MIN_CALL_INTERVAL_SECONDS)
    try:
        return _budget_checked_call(year, week, position, scoring_format)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 429:
            raise
        time.sleep(10)
        try:
            return _budget_checked_call(year, week, position, scoring_format)
        except httpx.HTTPStatusError as exc2:
            if exc2.response.status_code == 429:
                raise RateLimited(f"Still rate-limited fetching {position}/{scoring_format} after one retry") from exc2
            raise


def _short_error_summary(exc: Exception) -> str:
    """A safe-to-display-publicly summary of a fetch failure: the status
    code and a short, JSON-error-shaped snippet of the body where there is
    one, never the API key (the key travels as a header, never the URL,
    so httpx's own exception text doesn't carry it either) and never the
    full raw exception (this note is shown on the public dashboard URL,
    same rule the Odds API side already follows)."""
    if isinstance(exc, httpx.HTTPStatusError):
        snippet = exc.response.text[:120].replace("\n", " ").strip()
        return f"HTTP {exc.response.status_code}" + (f" - {snippet}" if snippet else "")
    return type(exc).__name__


def _parse_position_rank(pos_rank: str):
    """"RB1" -> 1. Returns None if the field is missing or unparseable
    (e.g. an unranked player) rather than raising."""
    if not pos_rank:
        return None
    match = _POS_RANK_NUMBER_RE.search(pos_rank)
    return int(match.group()) if match else None


def _upsert_expert_rank(db, player_id, week, position_rank, scoring_format, now):
    existing = (
        db.query(ExpertRank)
        .filter_by(player_id=player_id, week=week, scoring_format=scoring_format)
        .first()
    )
    if existing:
        existing.position_rank = position_rank
        existing.updated_at = now
    else:
        db.add(ExpertRank(
            player_id=player_id,
            week=week,
            position_rank=position_rank,
            tier=None,  # not exposed by this API response shape
            scoring_format=scoring_format,
            updated_at=now,
        ))


def sync_fantasypros(year: int, week: int, scoring_format: str, db: SessionLocal = None) -> dict:
    """Pulls consensus rankings for every skill position and stores them.
    There's no per-call dollar cost to protect here (unlike the Odds API)
    - it's a flat monthly fee - but there IS a real 500 calls/day cap on
    the plan (see DAILY_CALL_BUDGET), which a day of debugging this exact
    limit blew straight through before it was even confirmed."""
    owns_session = db is None
    db = db or SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        stored = 0
        unmatched = set()
        rate_limited_positions = []
        errors = []  # [(position, short safe-to-display error summary), ...]

        budget_exceeded = False
        for position in POSITIONS:
            try:
                data = _fetch_paced(year, week, position, scoring_format)
            except RateLimited:
                # Still rate-limited after a retry: skip just this one
                # position rather than losing whatever earlier positions
                # in this same call already succeeded.
                rate_limited_positions.append(position)
                continue
            except DailyBudgetExceeded:
                # Every remaining position/format this run would hit the
                # same wall - stop entirely rather than recording the same
                # failure once per remaining position.
                budget_exceeded = True
                break
            except Exception as exc:
                # Anything else (a non-429 HTTP error, a network blip) -
                # same reasoning: one position's failure shouldn't lose the
                # others, and recording *what* failed beats a generic
                # "FantasyPros refresh failed, check server logs" note when
                # there's no server-log access to actually check.
                errors.append((position, _short_error_summary(exc)))
                continue
            for player in data.get("players", []):
                position_rank = _parse_position_rank(player.get("pos_rank"))
                if position_rank is None:
                    continue
                name = player.get("player_name")
                matched = find_player_by_name(db, name)
                if not matched:
                    unmatched.add(name)
                    continue
                _upsert_expert_rank(db, matched.id, week, position_rank, scoring_format, now)
                stored += 1

        db.commit()
        return {
            "players_stored": stored,
            "unmatched": sorted(unmatched),
            "rate_limited_positions": rate_limited_positions,
            "errors": errors,
            "budget_exceeded": budget_exceeded,
        }
    finally:
        if owns_session:
            db.close()
