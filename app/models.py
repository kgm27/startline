"""Database tables. Each class below becomes one table in the SQLite file."""
from sqlalchemy import Column, Integer, String, Float, DateTime
from app.db import Base


class Player(Base):
    """Roster/injury info, sourced from the free Sleeper API."""
    __tablename__ = "players"

    id = Column(String, primary_key=True)  # Sleeper's player_id
    name = Column(String, nullable=False)
    team = Column(String)
    position = Column(String, index=True)  # QB/RB/WR/TE
    injury_status = Column(String)  # None, Questionable, Doubtful, Out, IR
    updated_at = Column(DateTime)


class DfsProjection(Base):
    """Underdog/PrizePicks projections, pulled automatically from The Odds
    API's us_dfs region (player_fantasy_points market)."""
    __tablename__ = "dfs_projections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    player_id = Column(String, index=True)
    source = Column(String)  # "underdog" or "prizepicks"
    week = Column(Integer, index=True)
    projected_points = Column(Float)
    updated_at = Column(DateTime)


class OddsProp(Base):
    """One sportsbook's prop line for one player/market, pulled from The Odds
    API. One row PER BOOKMAKER — betting_derived_points() averages across
    them — so the underlying per-book lines stay visible for transparency
    (e.g. "what did DraftKings vs FanDuel say")."""
    __tablename__ = "odds_props"

    id = Column(Integer, primary_key=True, autoincrement=True)
    player_id = Column(String, index=True)
    week = Column(Integer, index=True)
    market = Column(String)  # e.g. "rush_yds", "rec_yds", "pass_yds", "anytime_td"
    bookmaker = Column(String)  # e.g. "draftkings", "fanduel" — None for old pre-2026-07-28 rows
    line = Column(Float)  # the over/under number, e.g. 65.5
    implied_probability = Column(Float)  # for TD markets, vig-adjusted if possible
    odds = Column(Integer)  # raw American odds for the Over (or single) side, e.g. -140, +230
    under_odds = Column(Integer)  # American odds for the Under side, when the market has one
    updated_at = Column(DateTime)


class ExpertRank(Base):
    """Weekly consensus rank/tier from the FantasyPros ECR API."""
    __tablename__ = "expert_ranks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    player_id = Column(String, index=True)
    week = Column(Integer, index=True)
    position_rank = Column(Integer)  # e.g. 8 = 8th-ranked at his position
    tier = Column(Integer)  # FantasyPros tier grouping
    scoring_format = Column(String)  # std / half_ppr / ppr
    updated_at = Column(DateTime)
