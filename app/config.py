"""Central place to load settings from the .env file (see .env.example)."""
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


@dataclass(frozen=True)
class Settings:
    odds_api_key: str
    scoring_format: str
    db_path: str
    refresh_secret: str
    enable_scheduled_refresh: bool


def get_settings() -> Settings:
    return Settings(
        odds_api_key=os.getenv("ODDS_API_KEY", ""),
        scoring_format=os.getenv("SCORING_FORMAT", "half_ppr"),
        db_path=str(Path(__file__).resolve().parent.parent / "data" / "advisor.db"),
        refresh_secret=os.getenv("REFRESH_SECRET", ""),
        # Off by default so a local dev server never silently starts
        # spending real Odds API credits on a schedule. Set to "true" in
        # Render's env vars (not in a local .env) to turn on the daily
        # 9:30am Pacific auto-refresh - see _start_scheduler() in main.py.
        enable_scheduled_refresh=os.getenv("ENABLE_SCHEDULED_REFRESH", "").lower() == "true",
    )
