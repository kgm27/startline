"""Database tables. Each class below becomes one table in the SQLite file."""
from sqlalchemy import Column, Integer, String, Float, Date, DateTime
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


class ThresholdSnapshot(Base):
    """One day's "Chance of Going Over" reading for one player/stat/threshold,
    written each time a refresh pulls fresh odds, so the Player detail page
    can eventually chart how that probability moved over the week. One row
    per (player, week, stat, threshold, day): a same-day refresh updates the
    existing row rather than piling up duplicates."""
    __tablename__ = "threshold_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    player_id = Column(String, index=True)
    week = Column(Integer, index=True)
    stat = Column(String)  # e.g. "rush_yds", matches blend.py's MARKET_TO_STAT values
    threshold = Column(Float)
    probability = Column(Float)  # pooled "Chance of Going Over" at capture time, 0-1
    snapshot_date = Column(Date, index=True)  # calendar day this reading was captured
    updated_at = Column(DateTime)


class PredictionSnapshot(Base):
    """One day's headline numbers (DFS Projection, Sportsbook Projection,
    Blended score) for one player/week, written each time a refresh pulls
    fresh data, so the Dashboard and Player detail pages can chart how the
    top-level numbers moved leading up to kickoff. One row per (player,
    week, day): a same-day refresh updates the existing row rather than
    piling up duplicates, same pattern as ThresholdSnapshot."""
    __tablename__ = "prediction_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    player_id = Column(String, index=True)
    week = Column(Integer, index=True)
    dfs_pts = Column(Float)
    betting_pts = Column(Float)
    blended = Column(Float)
    snapshot_date = Column(Date, index=True)  # calendar day this reading was captured
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
