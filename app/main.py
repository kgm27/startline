"""FastAPI app: the dashboard page plus a manual "refresh data" action."""
import json
import os
from datetime import date, datetime, timezone

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db import Base, engine, get_db
from app.models import Player, DfsProjection, OddsProp, ExpertRank, ThresholdSnapshot
from app.config import get_settings
from app.data_sources.sleeper import sync_players, fetch_current_week
from app.data_sources.odds_api import sync_odds, DFS_SOURCE_LABELS
from app.scoring.blend import (
    dfs_projection_points,
    betting_derived_points,
    blend_expected_points,
    expert_perspective,
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

# Cache-busts /static/style.css and /static/app.js so a code change is never
# masked by a stale cached copy (browser or intermediate proxy) — the query
# string changes whenever the file's contents change, forcing a fresh fetch.
templates.env.globals["style_version"] = str(int(os.path.getmtime("app/static/style.css")))
templates.env.globals["app_js_version"] = str(int(os.path.getmtime("app/static/app.js")))
templates.env.filters["tojson"] = json.dumps

STAT_LABELS = {
    "pass_yds": "Passing Yards",
    "rush_yds": "Rushing Yards",
    "reception_yds": "Receiving Yards",
    "receptions": "Receptions",
    "pass_tds": "Passing TDs",
    "interceptions": "Interceptions",
    "rush_rec_tds": "Rush/Receiving TDs",
}
# Fantasy-relevance order for the Sportsbook Markets section, not
# alphabetical: touchdowns first (the highest-value stat), then yardage
# roughly QB → RB → WR/TE, receptions, interceptions last (a penalty stat).
# A player only ever shows a subset of these (a QB won't have reception_yds,
# a WR won't have pass_tds), so this just governs the order of whichever
# markets that player actually has.
MARKET_ORDER = [
    "pass_tds",
    "rush_rec_tds",
    "pass_yds",
    "rush_yds",
    "reception_yds",
    "receptions",
    "interceptions",
]

STAT_UNITS = {
    "pass_yds": "yds",
    "rush_yds": "yds",
    "reception_yds": "yds",
    "receptions": "rec",
    "pass_tds": "TD",
    "interceptions": "INT",
    "rush_rec_tds": "TD",
}
# (visible label, hover-tooltip explanation) per calculation method — the
# tooltip carries the technical detail that used to sit in an always-visible
# paragraph under every market block.
METHOD_INFO = {
    "discrete": (
        "Exact count",
        "Every threshold's probability adds up directly to the expected count — "
        "no distribution assumed, just market-implied probabilities added together.",
    ),
    "trapezoidal": (
        "Estimated from odds",
        "A curve connecting these threshold probabilities, assuming a 100% chance of "
        "at least zero up through the highest line quoted. Anything beyond the highest "
        "threshold isn't counted — a small, one-directional underestimate.",
    ),
    "legacy_probability": (
        "Estimated (limited data)",
        "Older data — averaged the raw market probability directly, since no threshold "
        "detail was stored for this stat yet.",
    ),
    "fallback": (
        "Price-adjusted average",
        "Not enough threshold data to build a curve, so each book's line is nudged "
        "based on its price instead of averaged as-is.",
    ),
}


def _resolve_week(db, requested_week):
    """Picks which week to show. An explicit ?week= is always honored as-is.
    Otherwise: try the real current NFL week; if that week has no data yet
    (off-season, or before the first pull of a new season posts anything),
    fall back to the most recent week that actually has real data, so the
    site shows the Week 15 2025 backtest instead of a blank page. Returns
    (week, is_demo) — is_demo is True whenever the displayed week isn't
    genuinely the current live week, so callers can show a "demo data"
    banner rather than silently passing off stale data as current."""
    current_week = None
    try:
        current_week = fetch_current_week()
    except Exception:
        pass

    if requested_week is not None:
        return requested_week, requested_week != current_week

    def _has_data(w):
        return (
            db.query(DfsProjection).filter_by(week=w).first() is not None
            or db.query(OddsProp).filter_by(week=w).first() is not None
        )

    if current_week is not None and _has_data(current_week):
        return current_week, False

    fallback = db.query(OddsProp.week).order_by(OddsProp.week.desc()).first()
    if fallback is None:
        fallback = db.query(DfsProjection.week).order_by(DfsProjection.week.desc()).first()
    if fallback is not None:
        return fallback[0], True

    return current_week or 1, False


def _thin_thresholds(items, min_gap=5):
    """items: sorted [(threshold, probability), ...]. Display-only — picks a
    subset spaced >= min_gap apart so long lists (e.g. every alternate
    yardage line) don't overwhelm the page. Always keeps the first and last
    real threshold. Doesn't touch the expected-value math, which still uses
    every threshold in the full curve."""
    if not items:
        return items
    kept = [items[0]]
    for t, p in items[1:]:
        if t - kept[-1][0] >= min_gap:
            kept.append((t, p))
    if kept[-1][0] != items[-1][0]:
        kept.append(items[-1])
    return kept


def _sparkline_svg(history, width=220, height=64):
    """A threshold's "Chance of Going Over" trend line, sized for a hover
    tooltip (not an inline table cell) so it can carry real labels — the
    date range and percentage range printed right on the chart — instead of
    being a bare, unlabeled shape. `history` is [(date, probability), ...]
    oldest first. Returns "" when there isn't enough history yet (the
    caller shows a "not ready" message instead)."""
    if len(history) < 2:
        return ""
    dates = [d for d, _ in history]
    values = [p for _, p in history]
    lo, hi = min(values), max(values)
    span = hi - lo or 0.01
    n = len(values)

    pad_left, pad_right, pad_top, pad_bottom = 4, 4, 14, 16
    chart_w = width - pad_left - pad_right
    chart_h = height - pad_top - pad_bottom

    points = []
    for i, v in enumerate(values):
        x = pad_left + (i / (n - 1)) * chart_w
        y = pad_top + chart_h - ((v - lo) / span) * chart_h
        points.append(f"{x:.1f},{y:.1f}")
    path = " ".join(points)

    range_label = f"{lo * 100:.0f}–{hi * 100:.0f}%"
    first_label = dates[0].strftime("%b %-d")
    last_label = dates[-1].strftime("%b %-d")

    return (
        f'<svg class="sparkline" viewBox="0 0 {width} {height}" width="{width}" height="{height}">'
        f'<polyline points="{path}" fill="none" stroke="currentColor" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
        f'<text x="{width - pad_right}" y="10" text-anchor="end" class="spark-label">{range_label}</text>'
        f'<text x="{pad_left}" y="{height - 3}" class="spark-label">{first_label}</text>'
        f'<text x="{width - pad_right}" y="{height - 3}" text-anchor="end" class="spark-label">{last_label}</text>'
        f"</svg>"
    )


@app.get("/")
def landing(request: Request):
    return templates.TemplateResponse("landing.html", {"request": request, "active_page": "landing"})


def _player_rows(db, week, scoring):
    """Every player's headline numbers for a given week — the shared dataset
    behind both the Dashboard table and the Comparison picker, so the two
    pages can never show different numbers for the same player/week."""
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
        })

    rows.sort(key=lambda r: r["blended"], reverse=True)
    return rows


@app.get("/dashboard")
def dashboard(request: Request, week: int = None, position: str = None, note: str = None, db: Session = Depends(get_db)):
    settings = get_settings()
    week, is_demo_week = _resolve_week(db, week)

    scoring = SCORING_RULES.get(settings.scoring_format, SCORING_RULES["half_ppr"])

    # Position filtering/search/sort all happen client-side (see dashboard.html)
    # for a snappy no-reload experience, so this always loads every position —
    # `position` is only used to seed which pill starts active.
    rows = _player_rows(db, week, scoring)

    summary = {
        "total": len(rows),
        "qb": sum(1 for r in rows if r["position"] == "QB"),
        "rb": sum(1 for r in rows if r["position"] == "RB"),
        "wr": sum(1 for r in rows if r["position"] == "WR"),
        "te": sum(1 for r in rows if r["position"] == "TE"),
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
        "active_page": "dashboard",
        "is_demo_week": is_demo_week,
    })


@app.get("/compare")
def compare(request: Request, week: int = None, a: str = None, b: str = None, db: Session = Depends(get_db)):
    settings = get_settings()
    week, is_demo_week = _resolve_week(db, week)
    scoring = SCORING_RULES.get(settings.scoring_format, SCORING_RULES["half_ppr"])
    rows = _player_rows(db, week, scoring)

    # ?a=&b= (player IDs) preselect the two pickers so a comparison can be
    # bookmarked/shared, same convention as the Dashboard/Player pages' ?week=.
    # Ignored (left null) if the ID isn't in this week's row set.
    row_ids = {str(r["id"]) for r in rows}
    initial_a = a if a in row_ids else None
    initial_b = b if b in row_ids else None

    return templates.TemplateResponse("compare.html", {
        "request": request,
        "rows_json": json.dumps(rows),
        "initial_a_json": json.dumps(initial_a),
        "initial_b_json": json.dumps(initial_b),
        "week": week,
        "is_demo_week": is_demo_week,
        "active_page": "compare",
    })


@app.get("/about")
def about(request: Request):
    return templates.TemplateResponse("about.html", {"request": request, "active_page": "about"})


@app.get("/player/{player_id}")
def player_detail(request: Request, player_id: str, week: int = None, db: Session = Depends(get_db)):
    """Shows exactly what fed into a player's blended score: each DFS site's
    number separately, and every sportsbook's line for every market —
    not just the single averaged numbers shown on the dashboard."""
    settings = get_settings()
    week, is_demo_week = _resolve_week(db, week)

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

    # one query for every threshold's snapshot history (3B.10), grouped so
    # the per-threshold loop below can just look up its own trend by key
    history_by_stat_threshold = {}
    snapshots = (
        db.query(ThresholdSnapshot)
        .filter_by(player_id=player.id, week=week)
        .order_by(ThresholdSnapshot.snapshot_date)
        .all()
    )
    for snap in snapshots:
        history_by_stat_threshold.setdefault((snap.stat, snap.threshold), []).append(
            (snap.snapshot_date, snap.probability)
        )

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
            # for display: each threshold, its pooled probability, and which
            # books quoted it (0 + "assumed" for the receptions first-catch
            # anchor, which isn't from any real book)
            books_by_threshold = {}
            for prop in stat_props:
                if prop.line is None or prop.odds is None:
                    continue
                books_by_threshold.setdefault(prop.line, []).append({
                    "bookmaker": prop.bookmaker or "unknown",
                    "odds": prop.odds,
                    "under_odds": prop.under_odds,
                })
            for book_list in books_by_threshold.values():
                book_list.sort(key=lambda b: b["bookmaker"])

            # long lists (every alternate yardage line) get thinned to every
            # ~5 units apart for display; discrete low-count stats (receptions,
            # TDs) keep every threshold since each unit matters there
            display_items = sorted(curve.items())
            if method != "discrete":
                display_items = _thin_thresholds(display_items)
            # the receptions "first catch" threshold is a deliberate
            # assumption (RECEPTIONS_FIRST_CATCH_ANCHOR), not a real market
            # quote — expected_count above already used it, so the math is
            # unaffected by leaving it out of what's actually displayed
            if stat == "receptions":
                display_items = [
                    (t, p) for t, p in display_items
                    if not (t == 0.5 and t not in books_by_threshold)
                ]

            thresholds = []
            for t, p in display_items:
                history = history_by_stat_threshold.get((stat, t), [])
                # every threshold's percentage is hoverable — either the real
                # date-by-date table once there's history, or a plain-language
                # explanation of when that history will start existing
                svg = _sparkline_svg(history)
                trend_tooltip = (
                    f'<div class="tooltip-title">Chance of Going Over — Trend</div>{svg}'
                    if svg else
                    "Trend data starts updating about a week before kickoff, once lines are posted "
                    "for this week's games — check back closer to game time."
                )
                thresholds.append({
                    "threshold": t,
                    "probability": round(p, 4),
                    "book_count": len(books_by_threshold.get(t, [])),
                    "books": books_by_threshold.get(t, []),
                    "assumed": stat == "receptions" and t == 0.5 and t not in books_by_threshold,
                    "trend_tooltip": trend_tooltip,
                })
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

        method_label, method_tooltip = METHOD_INFO[method]
        stats.append({
            "key": stat,
            "label": STAT_LABELS.get(stat, stat),
            "method": method,
            "method_label": method_label,
            "method_tooltip": method_tooltip,
            "unit": STAT_UNITS.get(stat, ""),
            "thresholds": thresholds,
            "books": books,
            "average": round(expected_count, 2),
            "rate": rate,
            "points": round(expected_count * rate, 2),
        })
    stats.sort(key=lambda m: MARKET_ORDER.index(m["key"]) if m["key"] in MARKET_ORDER else len(MARKET_ORDER))
    markets = stats

    dfs_pts = dfs_projection_points(dfs_rows)
    betting_pts = betting_derived_points(props, scoring)
    blended = blend_expected_points(dfs_pts, betting_pts)
    expert_persp = expert_perspective(player.position, expert.position_rank if expert else None)

    # feeds the summary-box hover breakdowns: what the DFS Projection /
    # Sportsbook Projection / Blended numbers are actually built from, in
    # the same order and using the same rounded numbers already shown in
    # each section
    dfs_breakdown = [
        {"label": DFS_SOURCE_LABELS.get(row.source, row.source), "points": row.projected_points}
        for row in dfs_rows
    ]
    betting_breakdown = [{"label": m["label"], "points": m["points"]} for m in markets]
    blended_breakdown = None
    if dfs_pts is not None and betting_pts is not None:
        blended_breakdown = [
            {"label": "DFS Projection", "points": dfs_pts},
            {"label": "Sportsbook Projection", "points": betting_pts},
        ]

    return templates.TemplateResponse("player_detail.html", {
        "request": request,
        "player": player,
        "week": week,
        "dfs_rows": dfs_rows,
        "dfs_source_labels": DFS_SOURCE_LABELS,
        "dfs_pts": dfs_pts,
        "dfs_breakdown": dfs_breakdown,
        "markets": markets,
        "betting_pts": betting_pts,
        "betting_breakdown": betting_breakdown,
        "blended_breakdown": blended_breakdown,
        "blended": blended,
        "expert": expert_persp,
        "is_demo_week": is_demo_week,
    })


def capture_threshold_snapshots(db: Session, week: int) -> int:
    """Writes one ThresholdSnapshot row per (player, stat, threshold) that
    has real curve data for `week`, so the Player detail page can eventually
    chart how each threshold's "Chance of Going Over" moved across pulls.
    A same-day refresh updates today's row rather than piling up duplicates
    — one reading per day, matching the plan's daily-snapshot cadence.
    Skips stats without enough threshold data for a curve (the same gate
    betting_derived_points() uses) since there's no per-threshold
    probability to snapshot in that case. Returns rows written/updated."""
    today = date.today()
    now = datetime.now(timezone.utc)

    player_ids = [pid for (pid,) in db.query(OddsProp.player_id).filter_by(week=week).distinct()]
    written = 0

    for player_id in player_ids:
        props = db.query(OddsProp).filter_by(player_id=player_id, week=week).all()
        props_by_stat = {}
        for prop in props:
            stat = MARKET_TO_STAT.get(prop.market)
            if stat is None:
                continue
            props_by_stat.setdefault(stat, []).append(prop)

        for stat, stat_props in props_by_stat.items():
            curve = _pooled_survival_curve(stat_props)
            if not curve or (stat not in NO_FALLBACK_STATS and len(curve) < MIN_THRESHOLDS_FOR_CURVE):
                continue
            curve = _apply_stat_anchors(curve, stat)

            for threshold, probability in curve.items():
                existing = (
                    db.query(ThresholdSnapshot)
                    .filter_by(player_id=player_id, week=week, stat=stat, threshold=threshold, snapshot_date=today)
                    .first()
                )
                if existing:
                    existing.probability = probability
                    existing.updated_at = now
                else:
                    db.add(ThresholdSnapshot(
                        player_id=player_id,
                        week=week,
                        stat=stat,
                        threshold=threshold,
                        probability=probability,
                        snapshot_date=today,
                        updated_at=now,
                    ))
                written += 1

    db.commit()
    return written


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

            week = fetch_current_week()
            snapshot_count = capture_threshold_snapshots(db, week)
            notes.append(f"Captured {snapshot_count} threshold snapshot(s) for the historical % chance charts")
        except Exception as exc:
            notes.append(f"Odds refresh failed: {exc}")

    query = ""
    if notes:
        from urllib.parse import quote
        query = f"?note={quote(' | '.join(notes))}"
    return RedirectResponse(url=f"/dashboard{query}", status_code=303)
