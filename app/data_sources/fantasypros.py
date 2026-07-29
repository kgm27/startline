"""FantasyPros Expert Consensus Rankings (ECR) API client
(fantasypros.com/api-data — api.fantasypros.com).

NOT YET TESTED against a real key — written from documented endpoint shape.
Verify against the live docs once FANTASYPROS_API_KEY is set, then this
comment can be removed.
"""
import httpx

from app.config import get_settings

BASE_URL = "https://api.fantasypros.com/public/v2/json/nfl"

# FantasyPros scoring-format codes
SCORING_FORMAT_CODES = {
    "standard": "STD",
    "half_ppr": "HALF",
    "full_ppr": "PPR",
}


class FantasyProsNotConfigured(Exception):
    pass


def _require_key() -> str:
    key = get_settings().fantasypros_api_key
    if not key:
        raise FantasyProsNotConfigured(
            "FANTASYPROS_API_KEY is not set in .env — sign up at fantasypros.com/api-data and add your key."
        )
    return key


def fetch_consensus_rankings(week: int, position: str, scoring_format: str = "half_ppr") -> dict:
    """Weekly expert consensus rank/tier for one position (QB/RB/WR/TE)."""
    key = _require_key()
    scoring_code = SCORING_FORMAT_CODES.get(scoring_format, "HALF")
    resp = httpx.get(
        f"{BASE_URL}/{week}/consensus-rankings",
        params={"position": position, "scoring": scoring_code, "type": "weekly"},
        headers={"x-api-key": key},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()
