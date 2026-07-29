"""FastAPI app: the dashboard page plus a manual "refresh data" action."""
import json

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db import Base, engine, get_db
from app.models import Player, DfsProjection, OddsProp, ExpertRank
from app.config import get_settings
from app.data_sources.sleeper import sync_players, fetch_current_week
from app.data_sources.odds_api import sync_odds, DFS_SOURCE_LABELS
from app.scoring.blend import (
    dfs_projection_points,
    betting_derived_points,
    blend_expected_points,
    expert_perspective,
    start_sit_recommendation,
    MARKET_TO_STAT,
    STAT_TO_RULE,
    DISCRETE_COUNT_STATS,
    NO_FALLBACK_STATS,
    MIN_THRESHOLDS_FOR_CURVE,
    LINE_MARKET_CV,
    RECEPTIONS_FIRST_CATCH_ANCHOR,
    _pooled_survival_curve,
    _apply_stat_anchors,
    _discrete_tail_sum,
    _trapezoidal_expectation,
    _effective_line,
)
from app.scoring.config import SCORING_RULES

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Fantasy Football Start/Sit Advisor")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

STAT_LABELS = {
    "pass_yds": "Passing Yards",
    "rush_yds": "Rushing Yards",
    "reception_yds": "Receiving Yards",
    "receptions": "Receptions",
    "pass_tds": "Passing TDs",
    "interceptions": "Interceptions",
    "rush_rec_tds": "Rush/Receiving TDs",
}


@app.get("/")
def dashboard(request: Request, week: int = None, position: str = None, note: str = None, db: Session = Depends(get_db)):
    settings = get_settings()
    if week is None:
        try:
            week = fetch_current_week()
        except Exception:
            week = 1

    scoring = SCORING_RULES.get(settings.scoring_format, SCORING_RULES["half_ppr"])

    # Position filtering/search/sort all happen client-side (see dashboard.html)
    # for a snappy no-reload experience, so this always loads every position —
    # `position` is only used to seed which pill starts active.
    rows = []
    for player in db.query(Player).all():
        projections = db.query(DfsProjection).filter_by(player_id=player.id, week=week).all()
        props = db.query(OddsProp).filter_by(player_id=player.id, week=week).all()
        expert = db.query(ExpertRank).filter_by(player_id=player.id, week=week).first()

        dfs_pts = dfs_projection_points(projections)
        betting_pts = betting_derived_points(props, scoring)
        blended = blend_expected_points(dfs_pts, betting_pts)

        if blended is None:
            continue  # no data at all for this player yet — skip rather than show an empty row

        expert_persp = expert_perspective(player.position, expert.position_rank if expert else None)
        rec = start_sit_recommendation(blended, player.position, expert_persp)

        rows.append({
            "id": player.id,
            "name": player.name,
            "position": player.position,
            "team": player.team,
            "injury": player.injury_status,
            "dfs_pts": dfs_pts,
            "betting_pts": betting_pts,
            "blended": blended,
            "expert": expert_persp.label if expert_persp else None,
            "call": rec.call,
            "call_note": rec.note,
        })

    rows.sort(key=lambda r: r["blended"], reverse=True)

    summary = {
        "total": len(rows),
        "start": sum(1 for r in rows if r["call"] == "Start"),
        "sit": sum(1 for r in rows if r["call"] == "Sit"),
        "tossup": sum(1 for r in rows if r["call"] == "Toss-up"),
    }

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "rows": rows,
        "rows_json": json.dumps(rows),
        "initial_position_json": json.dumps(position.upper() if position else "All"),
        "summary": summary,
        "week": week,
        "position": position,
        "scoring_format": settings.scoring_format,
        "odds_configured": bool(settings.odds_api_key),
        "fantasypros_configured": bool(settings.fantasypros_api_key),
        "note": note,
    })


@app.get("/player/{player_id}")
def player_detail(request: Request, player_id: str, week: int = None, db: Session = Depends(get_db)):
    """Shows exactly what fed into a player's blended score: each DFS site's
    number separately, and every sportsbook's line for every market —
    not just the single averaged numbers shown on the dashboard."""
    settings = get_settings()
    if week is None:
        try:
            week = fetch_current_week()
        except Exception:
            week = 1

    player = db.query(Player).get(player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    scoring = SCORING_RULES.get(settings.scoring_format, SCORING_RULES["half_ppr"])

    dfs_rows = db.query(DfsProjection).filter_by(player_id=player.id, week=week).all()
    props = (
        db.query(OddsProp)
        .filter_by(player_id=player.id, week=week)
        .order_by(OddsProp.market, OddsProp.bookmaker)
        .all()
    )
    expert = db.query(ExpertRank).filter_by(player_id=player.id, week=week).first()

    props_by_stat = {}
    for prop in props:
        stat = MARKET_TO_STAT.get(prop.market)
        if stat is None:
            continue
        props_by_stat.setdefault(stat, []).append(prop)

    stats = []
    for stat, stat_props in props_by_stat.items():
        rate = getattr(scoring, STAT_TO_RULE[stat])
        curve = _pooled_survival_curve(stat_props)
        books = None
        thresholds = None

        if curve and (stat in NO_FALLBACK_STATS or len(curve) >= MIN_THRESHOLDS_FOR_CURVE):
            method = "discrete" if stat in DISCRETE_COUNT_STATS else "trapezoidal"
            # decide richness from real market data only, THEN anchor —
            # matches betting_derived_points() exactly, so what's displayed
            # is always what was actually used to compute the score
            curve = _apply_stat_anchors(curve, stat)
            expected_count = (
                _discrete_tail_sum(curve) if stat in DISCRETE_COUNT_STATS
                else _trapezoidal_expectation(curve)
            )
            # for display: each threshold, its pooled probability, and how
            # many books contributed to that average (0 + "assumed" for the
            # receptions first-catch anchor, which isn't from any real book)
            counts = {}
            for prop in stat_props:
                if prop.line is None or prop.odds is None:
                    continue
                counts[prop.line] = counts.get(prop.line, 0) + 1
            thresholds = [
                {
                    "threshold": t,
                    "probability": round(p, 4),
                    "book_count": counts.get(t, 0),
                    "assumed": stat == "receptions" and t == 0.5 and t not in counts,
                }
                for t, p in sorted(curve.items())
            ]
        elif stat in NO_FALLBACK_STATS:
            # Older rows (pre-2026-07-28) never recorded a "line" for
            # rush_rec_tds, so there's no threshold curve to build — fall
            # back to directly averaging the raw implied_probability values,
            # same as betting_derived_points()'s legacy path.
            method = "legacy_probability"
            probs = [p.implied_probability for p in stat_props if p.implied_probability is not None]
            if not probs:
                continue
            expected_count = sum(probs) / len(probs)
        else:
            method = "fallback"
            cv = LINE_MARKET_CV.get(stat, 0.5)
            books = sorted([p for p in stat_props if p.line is not None], key=lambda p: p.bookmaker or "")
            if not books:
                continue
            for book in books:
                book.effective_line = round(_effective_line(book, cv), 2)
            expected_count = sum(book.effective_line for book in books) / len(books)

        stats.append({
            "key": stat,
            "label": STAT_LABELS.get(stat, stat),
            "method": method,
            "thresholds": thresholds,
            "books": books,
            "average": round(expected_count, 4 if stat in ("interceptions",) else 2),
            "rate": rate,
            "points": round(expected_count * rate, 2),
        })
    stats.sort(key=lambda m: m["label"])
    markets = stats

    dfs_pts = dfs_projection_points(dfs_rows)
    betting_pts = betting_derived_points(props, scoring)
    blended = blend_expected_points(dfs_pts, betting_pts)
    expert_persp = expert_perspective(player.position, expert.position_rank if expert else None)
    rec = start_sit_recommendation(blended, player.position, expert_persp) if blended is not None else None

    return templates.TemplateResponse("player_detail.html", {
        "request": request,
        "player": player,
        "week": week,
        "dfs_rows": dfs_rows,
        "dfs_source_labels": DFS_SOURCE_LABELS,
        "dfs_pts": dfs_pts,
        "markets": markets,
        "betting_pts": betting_pts,
        "blended": blended,
        "rec": rec,
    })


@app.post("/refresh")
def refresh(db: Session = Depends(get_db)):
    """Pulls fresh data from every source that's currently set up.
    FantasyPros pulls get wired in here once a key is added."""
    settings = get_settings()
    sync_players(db)

    notes = []
    if settings.odds_api_key:
        try:
            result = sync_odds(db)
            notes.append(
                f"Odds: checked {result['events_checked']} near-term game(s), "
                f"stored {result['props_stored']} sportsbook prop(s), "
                f"{result['dfs_stored']} DFS projection(s)"
            )
            if result["unmatched"]:
                notes.append(f"{len(result['unmatched'])} player name(s) didn't match our roster")
        except Exception as exc:
            notes.append(f"Odds refresh failed: {exc}")

    query = ""
    if notes:
        from urllib.parse import quote
        query = f"?note={quote(' | '.join(notes))}"
    return RedirectResponse(url=f"/{query}", status_code=303)
