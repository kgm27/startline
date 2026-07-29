"""Sleeper API client — free, public, no key required (docs.sleeper.com).

Sleeper asks that the full player list endpoint be called sparingly (their
docs suggest at most once per day), since it returns every NFL player in one
large payload. We fetch once per refresh run and upsert into our own table.
"""
from datetime import datetime, timezone

import httpx

from app.db import SessionLocal
from app.models import Player

SLEEPER_PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl"
SLEEPER_STATE_URL = "https://api.sleeper.app/v1/state/nfl"
SKILL_POSITIONS = {"QB", "RB", "WR", "TE"}


def fetch_current_week() -> int:
    """Current NFL week per Sleeper, so we don't have to hardcode/ask for it.
    Falls back to week 1 (e.g. during the offseason) if the field is missing."""
    response = httpx.get(SLEEPER_STATE_URL, timeout=15)
    response.raise_for_status()
    return response.json().get("week") or 1


def fetch_players() -> dict:
    """Returns Sleeper's raw {player_id: player_data} dict."""
    response = httpx.get(SLEEPER_PLAYERS_URL, timeout=30)
    response.raise_for_status()
    return response.json()


def sync_players(db: SessionLocal = None) -> int:
    """Pulls players from Sleeper and upserts skill-position players into our DB.
    Returns the number of players stored."""
    owns_session = db is None
    db = db or SessionLocal()
    try:
        raw_players = fetch_players()
        now = datetime.now(timezone.utc)
        count = 0
        for player_id, data in raw_players.items():
            position = data.get("position")
            if position not in SKILL_POSITIONS:
                continue
            if not data.get("team"):
                continue  # skip free agents / retired players

            existing = db.get(Player, player_id)
            full_name = data.get("full_name") or f"{data.get('first_name', '')} {data.get('last_name', '')}".strip()

            if existing:
                existing.name = full_name
                existing.team = data.get("team")
                existing.position = position
                existing.injury_status = data.get("injury_status")
                existing.updated_at = now
            else:
                db.add(Player(
                    id=player_id,
                    name=full_name,
                    team=data.get("team"),
                    position=position,
                    injury_status=data.get("injury_status"),
                    updated_at=now,
                ))
            count += 1
        db.commit()
        return count
    finally:
        if owns_session:
            db.close()
