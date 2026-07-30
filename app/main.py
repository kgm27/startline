"""FastAPI app: the dashboard page plus a manual "refresh data" action."""
import json
import logging
import os
import secrets
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Request, Depends, HTTPException, Header, UploadFile, File
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app.db import Base, engine, get_db
from app.models import Player, DfsProjection, OddsProp, ExpertRank, ThresholdSnapshot, PredictionSnapshot
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

# Basic per-IP rate limiting (Phase 5.2) so a stranger can't hammer the
# public pages. In-memory, fixed-window: this app runs as a single
# process, so no Redis/shared store is needed. Not meant to stop a
# determined distributed attacker, just casual abuse or a runaway script.
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_REQUESTS = 100
RATE_LIMIT_CLEANUP_INTERVAL_SECONDS = 300


def _client_ip(request):
    # Render (like most PaaS) sits the app behind a single proxy, so the
    # real visitor IP arrives via X-Forwarded-For, not request.client.host
    # (which would otherwise be the proxy's own address). Each hop
    # *appends* its own observed address, so with exactly one trusted
    # proxy in front, the LAST entry is the one Render itself recorded —
    # everything before it came from the client's own (spoofable) header
    # and can't be trusted for rate limiting. Falls back to
    # request.client.host for local dev, where that header isn't set.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._counts = {}  # ip -> [window_start_ts, count]
        self._last_cleanup = time.time()

    async def dispatch(self, request, call_next):
        now = time.time()
        if now - self._last_cleanup > RATE_LIMIT_CLEANUP_INTERVAL_SECONDS:
            self._counts = {
                ip: v for ip, v in self._counts.items()
                if now - v[0] < RATE_LIMIT_WINDOW_SECONDS
            }
            self._last_cleanup = now

        ip = _client_ip(request)
        window_start, count = self._counts.get(ip, (now, 0))
        if now - window_start >= RATE_LIMIT_WINDOW_SECONDS:
            window_start, count = now, 0
        count += 1
        self._counts[ip] = (window_start, count)
        if count > RATE_LIMIT_MAX_REQUESTS:
            return JSONResponse(
                {"detail": "Too many requests, please slow down and try again shortly."},
                status_code=429,
            )
        return await call_next(request)


app = FastAPI(title="StartLine", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(RateLimitMiddleware)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Cache-busts /static/style.css and /static/app.js so a code change is never
# masked by a stale cached copy (browser or intermediate proxy) — the query
# string changes whenever the file's contents change, forcing a fresh fetch.
templates.env.globals["style_version"] = str(int(os.path.getmtime("app/static/style.css")))
templates.env.globals["app_js_version"] = str(int(os.path.getmtime("app/static/app.js")))
templates.env.globals["favicon_version"] = str(int(os.path.getmtime("app/static/favicon.svg")))
templates.env.filters["tojson"] = json.dumps


def _script_safe_json(value):
    """JSON for direct embedding inside a <script> block (e.g. `const X =
    {{ rows_json | safe }}`). Escapes characters the HTML parser treats
    specially before JS ever sees them, so a value containing a literal
    "</script>" (or "<!--") can't prematurely close the block and let
    whatever follows run as unescaped markup. This is deliberately
    separate from the `tojson` filter above: that one feeds Alpine
    directive *attributes* (e.g. :style="...") and relies on Jinja's
    normal autoescaping of its plain, unmarked string output; this one is
    pre-escaped and always used with `| safe` for the different,
    script-tag context."""
    return (
        json.dumps(value)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("'", "\\u0027")
    )


def _error_page(request, status_code, heading, message):
    return templates.TemplateResponse(
        "error.html",
        {"request": request, "status_code": status_code, "heading": heading, "message": message},
        status_code=status_code,
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    # Only 404s (a bad URL/player id) get the branded page — every other
    # HTTPException (400 bad ?week=, 401 on /refresh, etc.) keeps the
    # plain JSON `{"detail": ...}` response FastAPI would normally send,
    # since those are meaningful, safe-to-show messages already, not a
    # leak to hide behind a generic page.
    if exc.status_code == 404:
        return _error_page(
            request, 404, "Page not found",
            "That page doesn't exist. It may have been moved, or the link might be out of date.",
        )
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # A genuine bug/crash: log the real error (with traceback) server-side
    # only, never show it to a visitor — matches the same principle as the
    # /refresh error-logging fix in Phase 5.4 (raw exception text can leak
    # internal details, so it never reaches an HTTP response body).
    logging.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return _error_page(
        request, 500, "Something went wrong",
        "An unexpected error occurred on our end. Try refreshing, or come back in a bit.",
    )

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


# Phase 3C: "boom potential", how much upside a player's main stat carries
# beyond what the market expects, read straight off the same alternate-line
# survival curve blend.py already builds for expected-value math. Margin is
# RELATIVE (not a fixed yardage number) so it means the same thing across
# very different stat scales (pass yards vs. reception yards). This never
# changes the blended score; it's a tiebreaker/context signal only, shown
# as a badge alongside the number.
MAIN_STAT_BY_POSITION = {
    "QB": "pass_yds",
    "RB": "rush_yds",
    "WR": "reception_yds",
    "TE": "reception_yds",
}
BOOM_MARGIN = 0.30  # "boom" = beating the market's own expectation by 30%+


def _interpolate_survival(curve, x):
    """Linear interpolation of a survival curve {threshold: P(X > threshold)}
    at an arbitrary point x, using the two nearest quoted thresholds.
    Returns None when x falls outside the curve's quoted range: there's no
    responsible way to extrapolate a probability past the highest line a
    book was willing to quote, so boom potential shows "n/a" rather than a
    guess in that case."""
    thresholds = sorted(curve.keys())
    if not thresholds or x < thresholds[0] or x > thresholds[-1]:
        return None
    if x in curve:
        return curve[x]
    for lo, hi in zip(thresholds, thresholds[1:]):
        if lo <= x <= hi:
            p_lo, p_hi = curve[lo], curve[hi]
            frac = (x - lo) / (hi - lo)
            return p_lo + (p_hi - p_lo) * frac
    return None


def _main_stat_curve(props, stat):
    """Pools and anchors the survival curve for one stat from a player's raw
    props, same gate (MIN_THRESHOLDS_FOR_CURVE) betting_derived_points()
    uses elsewhere, so boom potential is only ever computed from curves rich
    enough to trust. Returns (curve, expected) or (None, None)."""
    stat_props = [p for p in props if MARKET_TO_STAT.get(p.market) == stat]
    curve = _pooled_survival_curve(stat_props)
    if not curve or len(curve) < MIN_THRESHOLDS_FOR_CURVE:
        return None, None
    curve = _apply_stat_anchors(curve, stat)
    expected = _trapezoidal_expectation(curve)
    return curve, expected


def _boom_probability(curve, expected):
    """Given an already-anchored survival curve and its expected value, the
    probability of beating that expectation by BOOM_MARGIN or more. Returns
    None when there isn't enough range in the curve to responsibly answer
    (see _interpolate_survival), shown as "n/a", never a fake 0."""
    if not curve or not expected:
        return None
    return _interpolate_survival(curve, expected * (1 + BOOM_MARGIN))


def _resolve_week(db, requested_week):
    """Picks which week to show. An explicit ?week= is always honored as-is.
    Otherwise: try the real current NFL week; if that week has no data yet
    (off-season, or before the first pull of a new season posts anything),
    fall back to the most recent week that actually has real data, so the
    site shows the Week 15 2025 backtest instead of a blank page. Returns
    (week, is_demo) — is_demo is True whenever the displayed week isn't
    genuinely the current live week, so callers can show a "demo data"
    banner rather than silently passing off stale data as current."""
    if requested_week is not None and not (1 <= requested_week <= 30):
        # A regular season + playoffs never exceeds this range; anything
        # outside it is a malformed/abusive ?week= value (e.g. a huge
        # number that overflows SQLite's INTEGER column and crashes the
        # page) rather than a real week someone would legitimately request.
        raise HTTPException(status_code=400, detail="week must be between 1 and 30")

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


def _trend_chart_svg(points, width=280, height=132, css_class="sparkline", value_fmt=None, max_value=None):
    """Shared renderer for both the real trend chart (once real history
    exists) and the illustrative placeholder mockup (before it does), so a
    preview looks exactly like the real thing. `points` is
    [(date_label, value), ...], oldest first, at least 2 entries. The
    y-axis is always scaled tightly around the data's own range (with some
    headroom) rather than a fixed range — the same "let the real numbers
    set the scale" approach used throughout this app. `value_fmt` controls
    how a raw value is printed on the axis (defaults to a 0-1 probability
    as a percentage); `max_value` optionally caps the top of the range
    (e.g. 1.0 for a probability, left uncapped for a points total). X-axis
    tick labels are thinned to at most 5 so dates don't overlap once real
    history grows past a handful of days; the line and dots still plot
    every point regardless."""
    value_fmt = value_fmt or (lambda v: f"{v * 100:.0f}%")
    values = [v for _, v in points]
    labels = [l for l, _ in points]
    n = len(points)

    lo, hi = min(values), max(values)
    span = (hi - lo) or 0.02
    headroom = span * 0.25
    lo, hi = max(lo - headroom, 0.0), hi + headroom
    if max_value is not None:
        hi = min(hi, max_value)
    span = hi - lo or 0.02

    pad_left, pad_right, pad_top, pad_bottom = 34, 10, 10, 22
    chart_w = width - pad_left - pad_right
    chart_h = height - pad_top - pad_bottom

    def xy(i, v):
        x = pad_left + (i / (n - 1)) * chart_w if n > 1 else pad_left
        y = pad_top + chart_h - ((v - lo) / span) * chart_h
        return x, y

    coords = [xy(i, v) for i, v in enumerate(values)]
    path = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5"/>' for x, y in coords)

    y_ticks = sorted({hi, (lo + hi) / 2, lo}, reverse=True)
    y_axis = "".join(
        f'<text x="{pad_left - 6}" y="{pad_top + chart_h - ((v - lo) / span) * chart_h + 3:.1f}" '
        f'text-anchor="end" class="spark-axis-label">{value_fmt(v)}</text>'
        f'<line x1="{pad_left}" y1="{pad_top + chart_h - ((v - lo) / span) * chart_h:.1f}" '
        f'x2="{width - pad_right}" y2="{pad_top + chart_h - ((v - lo) / span) * chart_h:.1f}" '
        f'class="spark-gridline"/>'
        for v in y_ticks
    )

    max_labels = 5
    if n <= max_labels:
        label_idx = list(range(n))
    else:
        step = (n - 1) / (max_labels - 1)
        label_idx = sorted({round(i * step) for i in range(max_labels)})
    x_axis = "".join(
        f'<text x="{coords[i][0]:.1f}" y="{height - 5}" text-anchor="middle" class="spark-axis-label">'
        f"{labels[i]}</text>"
        for i in label_idx
    )

    return (
        f'<svg class="{css_class}" viewBox="0 0 {width} {height}" width="{width}" height="{height}">'
        f"{y_axis}"
        f'<line x1="{pad_left}" y1="{pad_top}" x2="{pad_left}" y2="{height - pad_bottom}" class="spark-axis-line"/>'
        f'<polyline points="{path}" fill="none" stroke="currentColor" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
        f'<g fill="currentColor">{dots}</g>'
        f"{x_axis}"
        f"</svg>"
    )


def _sparkline_svg(history):
    """A threshold's "Chance of Going Over" trend line, once there's real
    history to plot. `history` is [(date, probability), ...] oldest first.
    Returns "" when there isn't enough history yet (the caller shows the
    placeholder mockup instead)."""
    if len(history) < 2:
        return ""
    points = [(d.strftime("%b %-d"), p) for d, p in history]
    return _trend_chart_svg(points, css_class="sparkline", max_value=1.0)


def _placeholder_sparkline_svg(current_probability):
    """A mockup of the real trend chart, shown grayed out before there's
    enough history to plot one. Uses the real last-5-calendar-day dates on
    the x-axis and a y-axis scaled tightly around this threshold's actual
    current probability (the one real data point that already exists).
    The four earlier points are a plausible, deterministic wiggle around
    that real value, not real history: this is a preview of the shape, not
    a claim about what those days actually looked like, which is also why
    it's kept visually dimmed with the "not enough history yet" message
    layered on top rather than presented as if it were live data."""
    today = date.today()
    dates = [today - timedelta(days=i) for i in range(4, -1, -1)]
    # deterministic, illustrative offsets from the real value, oldest first;
    # the final offset is 0 so day 5 (today) always equals the real number
    offsets = [-0.05, 0.02, -0.035, 0.015, 0.0]
    values = [min(max(current_probability + o, 0.01), 0.99) for o in offsets]
    points = [(d.strftime("%b %-d"), v) for d, v in zip(dates, values)]
    return _trend_chart_svg(points, css_class="sparkline sparkline-placeholder", max_value=1.0)


def _prediction_trend_svg(history, width=560, height=170):
    """A headline number's (DFS/Sportsbook/Blended) trend line in fantasy
    points, once there's real history to plot. `history` is
    [(date, points), ...] oldest first. Returns "" when there isn't enough
    history yet (the caller shows the placeholder mockup instead). Sized
    larger than the per-threshold tooltip charts by default since this one
    renders inline on the page, not squeezed into a hover bubble."""
    if len(history) < 2:
        return ""
    points = [(d.strftime("%b %-d"), v) for d, v in history]
    return _trend_chart_svg(points, width=width, height=height, css_class="sparkline", value_fmt=lambda v: f"{v:.1f}")


def _placeholder_prediction_trend_svg(current_value, width=560, height=170):
    """A mockup of the headline-number trend chart, shown grayed out before
    there's enough history to plot one. Same approach as
    _placeholder_sparkline_svg() (real recent dates, real current value
    anchoring the last point, a deterministic illustrative wiggle for the
    rest) but for a fantasy-points total instead of a 0-1 probability, so
    the wiggle is a proportion of the real value rather than a fixed
    percentage-point offset."""
    today = date.today()
    dates = [today - timedelta(days=i) for i in range(4, -1, -1)]
    offset_pct = [-0.06, 0.03, -0.045, 0.02, 0.0]
    values = [max(current_value * (1 + o), 0.0) for o in offset_pct]
    points = [(d.strftime("%b %-d"), v) for d, v in zip(dates, values)]
    return _trend_chart_svg(
        points, width=width, height=height, css_class="sparkline sparkline-placeholder",
        value_fmt=lambda v: f"{v:.1f}",
    )


def _mini_sparkline_svg(history, width=64, height=22):
    """A tiny, axis-free line for inline use in a Dashboard table cell —
    the Player detail page's tooltip charts are too large to fit inline in
    a row, so this is a deliberately bare shape (no labels, no ticks) that
    just shows the direction of movement at a glance. `history` is
    [(date, points), ...] oldest first. Returns "" when there isn't enough
    history to plot (the caller shows a plain dash instead of an empty
    chart, unlike the Player detail page's larger hover mockups)."""
    if len(history) < 2:
        return ""
    values = [v for _, v in history]
    lo, hi = min(values), max(values)
    span = (hi - lo) or max(abs(hi), 1) * 0.05
    n = len(values)
    pad = 2
    chart_w, chart_h = width - pad * 2, height - pad * 2
    coords = [
        (pad + (i / (n - 1)) * chart_w, pad + chart_h - ((v - lo) / span) * chart_h)
        for i, v in enumerate(values)
    ]
    path = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    return (
        f'<svg class="mini-sparkline" viewBox="0 0 {width} {height}" width="{width}" height="{height}">'
        f'<polyline points="{path}" fill="none" stroke="currentColor" stroke-width="1.75" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
        f"</svg>"
    )


@app.get("/")
def landing(request: Request):
    return templates.TemplateResponse("landing.html", {"request": request, "active_page": "landing"})


_PLAYER_ROWS_CACHE = {}
_PLAYER_ROWS_CACHE_TTL_SECONDS = 30


def _player_rows(db, week, scoring):
    """Every player's headline numbers for a given week: the shared dataset
    behind both the Dashboard table and the Comparison picker, so the two
    pages can never show different numbers for the same player/week.
    Batch-fetches each table once for the whole week rather than once per
    player: looping ~370+ players with 3 queries each (an N+1 pattern) was
    measured taking ~800ms-1000ms per page load. Profiling after that fix
    showed the remaining ~400ms was mostly SQLAlchemy hydrating ~30,000
    OddsProp rows into ORM objects, not the query count itself, so this
    also caches the built rows briefly (_PLAYER_ROWS_CACHE_TTL_SECONDS):
    the underlying data only changes when /refresh runs, which is gated
    behind a secret token and happens at most a few times a day, not on
    every page view."""
    cache_key = (week, scoring)
    cached = _PLAYER_ROWS_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < _PLAYER_ROWS_CACHE_TTL_SECONDS:
        return cached[1]

    projections_by_player = {}
    for row in db.query(DfsProjection).filter_by(week=week).all():
        projections_by_player.setdefault(row.player_id, []).append(row)

    props_by_player = {}
    for row in db.query(OddsProp).filter_by(week=week).all():
        props_by_player.setdefault(row.player_id, []).append(row)

    # setdefault (not a plain dict comprehension) so the first ExpertRank
    # row per player wins, matching the old per-player .first() semantics,
    # in case more than one ever exists for the same player/week (e.g.
    # different scoring formats).
    expert_by_player = {}
    for row in db.query(ExpertRank).filter_by(week=week).all():
        expert_by_player.setdefault(row.player_id, row)

    rows = []
    for player in db.query(Player).all():
        projections = projections_by_player.get(player.id, [])
        props = props_by_player.get(player.id, [])
        expert = expert_by_player.get(player.id)

        dfs_pts = dfs_projection_points(projections)
        betting_pts = betting_derived_points(props, scoring)
        blended = blend_expected_points(dfs_pts, betting_pts)

        if blended is None:
            continue  # no data at all for this player yet — skip rather than show an empty row

        expert_persp = expert_perspective(player.position, expert.position_rank if expert else None)

        boom_stat = MAIN_STAT_BY_POSITION.get(player.position)
        boom_prob = None
        boom_points_upside = None
        if boom_stat:
            boom_curve, boom_expected = _main_stat_curve(props, boom_stat)
            if boom_expected:
                # what the 30% margin is worth in fantasy points, using the
                # same per-unit rate the blended score itself is built from,
                # so the boom flag speaks the site's usual "points" language
                # instead of leaving the reader to convert yards themselves
                boom_rate = getattr(scoring, STAT_TO_RULE[boom_stat])
                boom_points_upside = round(boom_expected * BOOM_MARGIN * boom_rate, 1)
                boom_prob = _boom_probability(boom_curve, boom_expected)

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
            "boom_stat": boom_stat,
            "boom_prob": boom_prob,
            "boom_points_upside": boom_points_upside,
        })

    # "High ceiling" flag: top quartile of boom_prob within each position,
    # not a fixed cutoff — what counts as unusual upside is relative to
    # that week's own market data, and a fixed number would drift in
    # meaning as the underlying odds/margin math gets refined later.
    # Skipped for a position entirely when too few players have a real
    # boom_prob to rank meaningfully (e.g. only one game has alternate
    # lines pulled so far).
    by_position = {}
    for r in rows:
        if r["boom_prob"] is not None:
            by_position.setdefault(r["position"], []).append(r["boom_prob"])
    boom_cutoff = {}
    for pos, vals in by_position.items():
        if len(vals) < 4:
            continue
        vals_sorted = sorted(vals)
        idx = min(len(vals_sorted) - 1, int(len(vals_sorted) * 0.75))
        boom_cutoff[pos] = vals_sorted[idx]

    for r in rows:
        cutoff = boom_cutoff.get(r["position"])
        r["boom_flag"] = r["boom_prob"] is not None and cutoff is not None and r["boom_prob"] >= cutoff
        r["boom_tooltip"] = None
        if r["boom_flag"]:
            stat_label = STAT_LABELS.get(r["boom_stat"], r["boom_stat"])
            # The percentage and points boost are the headline: large,
            # side by side, each labeled so neither number needs the
            # paragraph below to be understood on its own. The explanation
            # is real but secondary, kept small underneath.
            r["boom_tooltip"] = (
                '<div class="tooltip-title">High Ceiling</div>'
                '<div class="boom-tooltip-stats">'
                '<div class="boom-tooltip-stat">'
                f'<span class="boom-tooltip-value">{r["boom_prob"] * 100:.0f}%</span>'
                '<span class="boom-tooltip-label">chance</span>'
                "</div>"
                '<span class="boom-tooltip-arrow">&rarr;</span>'
                '<div class="boom-tooltip-stat">'
                f'<span class="boom-tooltip-value">+{r["boom_points_upside"]}</span>'
                '<span class="boom-tooltip-label">pts upside</span>'
                "</div>"
                "</div>"
                f'<div class="boom-tooltip-detail">Chance of beating the market\'s expected '
                f"{stat_label.lower()} by {BOOM_MARGIN * 100:.0f}% or more, worth about "
                f"+{r['boom_points_upside']} fantasy points if it happens.</div>"
            )

    rows.sort(key=lambda r: r["blended"], reverse=True)
    _PLAYER_ROWS_CACHE[cache_key] = (time.time(), rows)
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

    # Tiny inline Blended-score trend sparkline per row (Phase 3B.4). One
    # bulk query for the whole week rather than one per player/row.
    snapshots_by_player = {}
    for snap in (
        db.query(PredictionSnapshot)
        .filter_by(week=week)
        .order_by(PredictionSnapshot.snapshot_date)
        .all()
    ):
        if snap.blended is not None:
            snapshots_by_player.setdefault(snap.player_id, []).append((snap.snapshot_date, snap.blended))
    for row in rows:
        row["trend_svg"] = _mini_sparkline_svg(snapshots_by_player.get(row["id"], []))

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
        "rows_json": _script_safe_json(rows),
        "initial_position_json": _script_safe_json(position.upper() if position else "All"),
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
        "rows_json": _script_safe_json(rows),
        "initial_a_json": _script_safe_json(initial_a),
        "initial_b_json": _script_safe_json(initial_b),
        "week": week,
        "is_demo_week": is_demo_week,
        "active_page": "compare",
    })


@app.get("/about")
def about(request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    week, is_demo_week = _resolve_week(db, None)
    scoring = SCORING_RULES.get(settings.scoring_format, SCORING_RULES["half_ppr"])

    # A real, live worked example beats a made-up one — this week's #1
    # blended score, whoever that happens to be, so the walkthrough below
    # always points at genuine (not fabricated) numbers a reader can click
    # into and verify on that player's own page.
    rows = _player_rows(db, week, scoring)
    example = rows[0] if rows else None

    return templates.TemplateResponse("about.html", {
        "request": request,
        "week": week,
        "is_demo_week": is_demo_week,
        "example": example,
        "scoring": scoring,
        "active_page": "about",
    })


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

    # Boom potential (Phase 3C): computed inline in this same loop, reusing
    # the curve/expected_count already built for the player's main stat
    # rather than pooling the props a second time.
    main_stat = MAIN_STAT_BY_POSITION.get(player.position)
    boom = None

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
            if stat == main_stat:
                boom = {
                    "stat": stat,
                    "label": STAT_LABELS.get(stat, stat),
                    "unit": STAT_UNITS.get(stat, ""),
                    "expected": round(expected_count, 1),
                    "target": round(expected_count * (1 + BOOM_MARGIN), 1),
                    "margin_pct": round(BOOM_MARGIN * 100),
                    "points_upside": round(expected_count * BOOM_MARGIN * rate, 1),
                    "probability": _boom_probability(curve, expected_count),
                }
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
                # every threshold's percentage is hoverable: either the real
                # date-by-date table once there's history, or a plain-language
                # explanation of when that history will start existing
                svg = _sparkline_svg(history)
                if svg:
                    trend_tooltip = f'<div class="tooltip-title">Chance of Going Over: Trend</div>{svg}'
                else:
                    # Not enough history yet: show the same chart frame, grayed
                    # out, with the explanation overlaid on top rather than as
                    # bare text, so the "coming soon" state previews the shape
                    # of the real thing.
                    placeholder_svg = _placeholder_sparkline_svg(p)
                    trend_tooltip = (
                        '<div class="tooltip-title">Chance of Going Over: Trend</div>'
                        f'<div class="sparkline-pending">{placeholder_svg}'
                        '<div class="sparkline-pending-message">Trend data starts updating about a week '
                        "before kickoff, once lines are posted for this week's games. Check back closer "
                        "to game time.</div></div>"
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

    # Headline-score trend chart (Phase 3B): DFS/Sportsbook/Blended over the
    # days leading up to kickoff, toggleable in the template. Falls back to
    # a placeholder mockup (anchored to today's real number) for whichever
    # metric doesn't have 2+ real days of PredictionSnapshot history yet.
    # Metrics with no current value at all (e.g. no DFS projections this
    # week) are left out of the toggle entirely rather than showing an
    # empty chart for a number that doesn't exist.
    prediction_snapshots = (
        db.query(PredictionSnapshot)
        .filter_by(player_id=player.id, week=week)
        .order_by(PredictionSnapshot.snapshot_date)
        .all()
    )
    headline_trend = {}
    for key, label, current_value in (
        ("blended", "Blended", blended),
        ("dfs_pts", "DFS Projection", dfs_pts),
        ("betting_pts", "Sportsbook Projection", betting_pts),
    ):
        if current_value is None:
            continue
        history = [
            (snap.snapshot_date, getattr(snap, key))
            for snap in prediction_snapshots
            if getattr(snap, key) is not None
        ]
        svg = _prediction_trend_svg(history)
        headline_trend[key] = {
            "label": label,
            "svg": svg or _placeholder_prediction_trend_svg(current_value),
            "is_placeholder": not svg,
        }

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
        "headline_trend": headline_trend,
        "headline_trend_json": _script_safe_json(headline_trend),
        "boom": boom,
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


def capture_prediction_snapshots(db: Session, week: int) -> int:
    """Writes one PredictionSnapshot row per player with any data for
    `week`, recording that day's DFS Projection, Sportsbook Projection, and
    Blended score so the Dashboard and Player detail pages can chart how
    the headline numbers moved leading up to kickoff. A same-day refresh
    updates today's row rather than piling up duplicates, same pattern as
    capture_threshold_snapshots(). Returns rows written/updated."""
    settings = get_settings()
    scoring = SCORING_RULES.get(settings.scoring_format, SCORING_RULES["half_ppr"])
    today = date.today()
    now = datetime.now(timezone.utc)

    written = 0
    for player in db.query(Player).all():
        projections = db.query(DfsProjection).filter_by(player_id=player.id, week=week).all()
        props = db.query(OddsProp).filter_by(player_id=player.id, week=week).all()

        dfs_pts = dfs_projection_points(projections)
        betting_pts = betting_derived_points(props, scoring)
        blended = blend_expected_points(dfs_pts, betting_pts)

        if blended is None:
            continue  # nothing to snapshot yet for this player/week

        existing = (
            db.query(PredictionSnapshot)
            .filter_by(player_id=player.id, week=week, snapshot_date=today)
            .first()
        )
        if existing:
            existing.dfs_pts = dfs_pts
            existing.betting_pts = betting_pts
            existing.blended = blended
            existing.updated_at = now
        else:
            db.add(PredictionSnapshot(
                player_id=player.id,
                week=week,
                dfs_pts=dfs_pts,
                betting_pts=betting_pts,
                blended=blended,
                snapshot_date=today,
                updated_at=now,
            ))
        written += 1

    db.commit()
    return written


@app.get("/admin/debug-info")
def debug_info(x_refresh_token: str = Header(None)):
    """TEMPORARY diagnostic for Phase 6.5: the production database went
    empty after a redeploy, meaning the persistent disk likely isn't
    mounted where the app expects. Reports the exact path/cwd/disk state
    so the mismatch can be found instead of guessed at. Remove after."""
    settings = get_settings()
    if not settings.refresh_secret or not secrets.compare_digest(x_refresh_token or "", settings.refresh_secret):
        raise HTTPException(status_code=401, detail="Missing or invalid X-Refresh-Token header")
    db_path = Path(settings.db_path)
    data_dir = db_path.parent
    return {
        "cwd": os.getcwd(),
        "__file___resolved": str(Path(__file__).resolve()),
        "db_path": str(db_path),
        "db_exists": db_path.exists(),
        "db_size_bytes": db_path.stat().st_size if db_path.exists() else None,
        "data_dir": str(data_dir),
        "data_dir_exists": data_dir.exists(),
        "data_dir_contents": sorted(p.name for p in data_dir.iterdir()) if data_dir.exists() else None,
        "data_dir_is_mount": os.path.ismount(str(data_dir)),
        "project_root_contents": sorted(p.name for p in Path(__file__).resolve().parent.parent.iterdir()),
        "suspect_dirs": {
            repr(p.name): {
                "is_mount": os.path.ismount(str(p)),
                "contents": sorted(x.name for x in p.iterdir()) if p.is_dir() else None,
            }
            for p in Path(__file__).resolve().parent.parent.iterdir()
            if p.name.strip() == "data" and p.name != "data"
        },
    }


@app.post("/admin/upload-db")
async def upload_db(file: UploadFile = File(...), x_refresh_token: str = Header(None)):
    """TEMPORARY, Phase 6.5 (re-added): the first disk mount had a stray
    trailing space in its path, so this seeds the corrected disk. Same
    auth pattern as /refresh. Remove once persistence is verified."""
    settings = get_settings()
    if not settings.refresh_secret or not secrets.compare_digest(x_refresh_token or "", settings.refresh_secret):
        raise HTTPException(status_code=401, detail="Missing or invalid X-Refresh-Token header")
    contents = await file.read()
    tmp_path = settings.db_path + ".upload_tmp"
    with open(tmp_path, "wb") as f:
        f.write(contents)
    os.replace(tmp_path, settings.db_path)
    engine.dispose()
    _PLAYER_ROWS_CACHE.clear()
    return {"status": "ok", "bytes_written": len(contents)}


@app.post("/refresh")
def refresh(db: Session = Depends(get_db), x_refresh_token: str = Header(None)):
    """Pulls fresh data from every source that's currently set up. Requires
    a matching X-Refresh-Token header (see REFRESH_SECRET in .env) so a
    stranger who finds this URL can't spend real Odds API credits. Fails
    closed: if REFRESH_SECRET isn't configured at all, every request is
    rejected rather than silently allowed through.
    FantasyPros pulls get wired in here once a key is added."""
    settings = get_settings()
    if not settings.refresh_secret or not secrets.compare_digest(x_refresh_token or "", settings.refresh_secret):
        raise HTTPException(status_code=401, detail="Missing or invalid X-Refresh-Token header")
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
            prediction_count = capture_prediction_snapshots(db, week)
            notes.append(f"Captured {prediction_count} headline-score snapshot(s) for the trend charts")
            _PLAYER_ROWS_CACHE.clear()  # so the new data shows immediately, not after the cache TTL
        except Exception:
            # Never surface the raw exception text on the public dashboard
            # or in the redirect URL: httpx includes the request URL in its
            # error messages, and the Odds API key travels as a query
            # param, so a raw failure could print the real key on a public
            # page and in access logs. Log server-side only.
            logging.exception("Odds refresh failed")
            notes.append("Odds refresh failed, check server logs for details")

    query = ""
    if notes:
        from urllib.parse import quote
        query = f"?note={quote(' | '.join(notes))}"
    return RedirectResponse(url=f"/dashboard{query}", status_code=303)
