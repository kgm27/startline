"""Central place to load settings from the .env file (see .env.example)."""
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


@dataclass(frozen=True)
class Settings:
    odds_api_key: str
    fantasypros_api_key: str
    scoring_format: str
    db_path: str


def get_settings() -> Settings:
    return Settings(
        odds_api_key=os.getenv("ODDS_API_KEY", ""),
        fantasypros_api_key=os.getenv("FANTASYPROS_API_KEY", ""),
        scoring_format=os.getenv("SCORING_FORMAT", "half_ppr"),
        db_path=str(Path(__file__).resolve().parent.parent / "data" / "advisor.db"),
    )
