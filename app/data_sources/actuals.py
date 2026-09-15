"""Real, final box-score stats for a played week — free Sleeper endpoint, no
key required. Used to compare our DFS/Sportsbook/Blended projections against
what a player actually did, once the game is in the books.

Mirrors scripts/backtest_accuracy.py's actuals fetch + pricer (kept
deliberately in sync with it): same free endpoint, same stat fields, same
ScoringRules-based pricing, so a live "Projected vs. Actual" number on the
player page always means the same thing as the offline backtest number.
"""
import time
from datetime import date

import httpx

from app.scoring.config import ScoringRules

STATS_URL = "https://api.sleeper.app/v1/stats/nfl/regular/{season}/{week}"

# Sleeper's raw stat keys -> the ScoringRules field that prices them. Only
# the stats our own projections are trying to forecast appear here (no
# fumbles/2PT/return yards, matching blend.py's scope), so "Actual" is
# apples-to-apples with "Projected", not a bigger number for unrelated
# reasons.
STAT_FIELDS = {
    "pass_yd": "points_per_pass_yard",
    "rush_yd": "points_per_rush_yard",
    "rec_yd": "points_per_reception_yard",
    "rec": "points_per_reception",
    "pass_td": "points_per_pass_td",
    "pass_int": "points_per_interception",
}
TD_FIELDS = ("rush_td", "rec_td")  # both priced at points_per_rush_or_rec_td

# (season, week) -> (fetched_at, stats_dict). A short TTL rather than a
# forever-cache: a week's stats are final once every game's played, but
# while a game is still live (e.g. tonight's MNF) they update in real time,
# and this cache is shared by every player-detail page view.
_STATS_CACHE: dict[tuple[int, int], tuple[float, dict]] = {}
_STATS_CACHE_TTL_SECONDS = 600


def current_season() -> int:
    """The NFL season a given calendar date belongs to — January/February
    games still belong to the season that kicked off the previous fall."""
    today = date.today()
    return today.year - 1 if today.month <= 2 else today.year


def fetch_week_stats(season: int, week: int) -> dict:
    """Every player's real box-score stats for one week, keyed by Sleeper
    player_id — the same id this project already uses as its own primary
    key, so no name matching is needed. Free, no API key required."""
    cache_key = (season, week)
    cached = _STATS_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < _STATS_CACHE_TTL_SECONDS:
        return cached[1]

    resp = httpx.get(STATS_URL.format(season=season, week=week), timeout=30)
    resp.raise_for_status()
    data = resp.json()
    _STATS_CACHE[cache_key] = (time.time(), data)
    return data


def actual_points(player_stats: dict, rules: ScoringRules) -> float:
    """Prices one player's real stat line with the same ScoringRules the
    projections are priced with."""
    total = 0.0
    for field, rule in STAT_FIELDS.items():
        total += (player_stats.get(field) or 0.0) * getattr(rules, rule)
    for field in TD_FIELDS:
        total += (player_stats.get(field) or 0.0) * rules.points_per_rush_or_rec_td
    return total


def played(player_stats: dict) -> bool:
    """Whether Sleeper's stat line shows this player actually took the
    field, as opposed to merely having a roster entry that week (inactive,
    bye, or a game that hasn't kicked off yet). Same "gp"/"gms_active"
    check scripts/backtest_accuracy.py uses, kept in sync deliberately."""
    return (player_stats.get("gp") or player_stats.get("gms_active") or 0) >= 1
