"""Implements the methodology from the project brief, Section 5:
odds -> point estimate, blend with DFS projections, apply expert-agreement lens.
"""
from dataclasses import dataclass
from statistics import NormalDist
from typing import Optional

from app.models import OddsProp, DfsProjection
from app.scoring.config import ScoringRules, REPLACEMENT_LEVEL
from app.data_sources.odds_api import american_odds_to_implied_probability

# Roughly how many players at a position are considered "startable" by
# consensus — used to translate an expert position-rank into a plain-language
# tier. Starting point only, same caveat as REPLACEMENT_LEVEL.
EXPERT_STARTER_RANK_CUTOFF = {"QB": 12, "RB": 24, "WR": 30, "TE": 12}
EXPERT_FLEX_RANK_CUTOFF = {"QB": 18, "RB": 36, "WR": 42, "TE": 18}

# Maps every raw market key (main line AND its _alternate variant, where one
# exists) to one canonical stat name, so alternate-line data pools together
# with the main line, and anytime_td/tds_over pool into a single touchdown-
# count ladder instead of being treated as unrelated markets.
MARKET_TO_STAT = {
    "player_pass_yds": "pass_yds",
    "player_rush_yds": "rush_yds",
    "player_reception_yds": "reception_yds",
    "player_receptions": "receptions",
    "player_pass_tds": "pass_tds",
    "player_pass_interceptions": "interceptions",
    "player_anytime_td": "rush_rec_tds",
    "player_tds_over": "rush_rec_tds",
}

STAT_TO_RULE = {
    "pass_yds": "points_per_pass_yard",
    "rush_yds": "points_per_rush_yard",
    "reception_yds": "points_per_reception_yard",
    "receptions": "points_per_reception",
    "pass_tds": "points_per_pass_td",
    "interceptions": "points_per_interception",
    "rush_rec_tds": "points_per_rush_or_rec_td",
}

# Stats that are genuine non-negative INTEGER COUNTS: when we have threshold
# data spaced exactly 1 apart (0.5, 1.5, 2.5, ... from alternate-line
# markets), E[X] = sum of the survival probability at every observed
# threshold is an EXACT mathematical identity — no distributional
# assumption needed at all. Verified against real historical data
# 2026-07-29 (receptions/pass_tds/interceptions alternate markets all use
# 1-unit spacing). rush_rec_tds has no real sportsbook "line" to fall back
# to (anytime_td/tds_over are priced as pure probabilities, not a number
# players bet Over/Under on), so it always uses this exact formula
# regardless of how many thresholds are available — same tail-sum approach
# this codebase has used since before alternate-line data existed.
DISCRETE_COUNT_STATS = {"receptions", "pass_tds", "interceptions", "rush_rec_tds"}
NO_FALLBACK_STATS = {"rush_rec_tds"}

# Below this many distinct thresholds pooled across books, there isn't
# enough shape information to trust a numerical curve — fall back to the
# single (main) line, nudged by that book's own price skew. Rough, NOT
# empirically calibrated coefficients of variation (std-dev as a fraction
# of the line) used only for that fallback nudge — see
# _price_adjusted_line(). Industry rule-of-thumb magnitudes, not fitted to
# this project's own historical results — same "starting point, expect to
# refine" caveat as REPLACEMENT_LEVEL.
MIN_THRESHOLDS_FOR_CURVE = 3
LINE_MARKET_CV = {
    "pass_yds": 0.30,
    "rush_yds": 0.45,
    "reception_yds": 0.55,
    "receptions": 0.35,
    "pass_tds": 0.65,
    "interceptions": 0.85,
}


def _devig_over_probability(over_odds: Optional[int], under_odds: Optional[int]) -> Optional[float]:
    """De-vigs a two-sided Over/Under market: raw implied probabilities from
    American odds always sum to slightly more than 1.0 (the bookmaker's
    margin) — dividing each side by that sum removes it, leaving the
    market's actual view of P(actual value > line)."""
    if over_odds is None or under_odds is None:
        return None
    p_over_raw = american_odds_to_implied_probability(over_odds)
    p_under_raw = american_odds_to_implied_probability(under_odds)
    total = p_over_raw + p_under_raw
    if total <= 0:
        return None
    return p_over_raw / total


def _price_adjusted_line(line: float, over_odds: Optional[int], under_odds: Optional[int], cv: float) -> float:
    """A stated line (e.g. "65.5 rush yards") is only ever a threshold, not
    a direct expected value — but if the Over/Under pricing on it is skewed
    rather than a plain 50/50 split, that skew is the market telling us the
    true expected value sits away from the line without bothering to move
    the number itself. This assumes the underlying stat is roughly Normal
    around some true mean with a rule-of-thumb std-dev (see LINE_MARKET_CV),
    then solves for the mean implied by the de-vigged Over probability.
    Falls back to the raw line if we don't have both sides' prices (e.g.
    older rows pulled before under_odds was captured)."""
    p_over = _devig_over_probability(over_odds, under_odds)
    if p_over is None:
        return line
    p_over = min(max(p_over, 0.001), 0.999)  # keep inv_cdf finite at the extremes
    z = NormalDist().inv_cdf(p_over)
    sigma = cv * line
    return line + z * sigma


def _effective_line(prop: OddsProp, cv: float) -> float:
    return _price_adjusted_line(prop.line, prop.odds, prop.under_odds, cv)


def _pooled_survival_curve(props: list[OddsProp]) -> dict:
    """Pools every book's threshold data for one stat into a single curve:
    for each distinct threshold value, the average raw Over-implied
    probability across whichever books quoted it. Alternate-line markets
    are Over-only, so most thresholds have no Under side to de-vig
    against — using raw implied probabilities uniformly at every point
    keeps the curve internally consistent, at the cost of each point
    running slightly high due to un-removed vig (same caveat the TD
    markets always had)."""
    by_threshold = {}
    for prop in props:
        if prop.line is None or prop.odds is None:
            continue
        p = american_odds_to_implied_probability(prop.odds)
        by_threshold.setdefault(prop.line, []).append(p)
    return {threshold: sum(ps) / len(ps) for threshold, ps in by_threshold.items()}


# Sportsbooks never post an "Over 0.5 receptions" (at least 1 catch)
# market — it's too close to a certainty for any player who gets a
# receptions market posted at all to be worth pricing. That leaves a real
# gap at the very first term of the tail-sum, which otherwise silently
# undercounts every receiving-relevant player by roughly a catch. Assumed
# anchor: P(receptions >= 1) = 1.0 — the same spirit as the trapezoidal
# method's P(yardage > 0) = 1.0 assumption at the low end. This is NOT
# measured from a real market; it's a deliberate, disclosed simplification
# specific to this one known gap (added 2026-07-29 at the owner's request).
RECEPTIONS_FIRST_CATCH_ANCHOR = 1.0


def _apply_stat_anchors(curve: dict, stat: str) -> dict:
    """Fills in market gaps we've specifically identified and chosen to
    assume rather than leave silently missing — currently just the
    receptions 0.5 threshold above. Deliberately narrow: do NOT extend this
    pattern to other discrete stats (e.g. "assume P(>=1 TD)=1") without the
    same real-world justification — most players do NOT score/turn the
    ball over every game, so that assumption would be false for them."""
    if stat == "receptions" and curve and 0.5 not in curve:
        return {**curve, 0.5: RECEPTIONS_FIRST_CATCH_ANCHOR}
    return curve


def _discrete_tail_sum(curve: dict) -> float:
    """E[X] = sum of P(X > k) at every observed half-integer threshold — an
    EXACT identity for a non-negative integer count with 1-unit threshold
    spacing, not an approximation."""
    return sum(curve.values())


def _trapezoidal_expectation(curve: dict) -> float:
    """E[X] = integral of P(X > x) dx from 0 to infinity, approximated by
    trapezoidal interpolation between the thresholds we have data for and
    truncated beyond the highest one. That truncation is a small,
    one-directional (conservative) underestimate — same tradeoff as the
    discrete tail-sum's truncation, just for a continuous stat."""
    thresholds = sorted(curve.keys())
    if not thresholds:
        return 0.0
    total = 0.0
    prev_x, prev_p = 0.0, 1.0  # P(X > 0) = 1 is a safe floor for yardage/receptions
    for x in thresholds:
        p = curve[x]
        total += (x - prev_x) * (prev_p + p) / 2
        prev_x, prev_p = x, p
    return total


def betting_derived_points(props: list[OddsProp], scoring: ScoringRules) -> Optional[float]:
    """Sums up all prop data for a player into one fantasy-point estimate.
    For each stat, pools every threshold any bookmaker quoted (main line +
    alternate lines, where available) into one curve, then computes an
    expected value from it directly: an EXACT formula for count stats
    (receptions, TDs, interceptions), a trapezoidal approximation for
    yardage. Falls back to the older single-line, price-skew-nudged
    estimate when there isn't enough threshold data pooled to trust a
    curve (e.g. weeks/games where alternate-line markets haven't been
    pulled yet) — except rush_rec_tds, which has no real sportsbook "line"
    to fall back to and always uses the exact formula.
    Returns None if there are no props to work from (e.g. keys not set up yet)."""
    if not props:
        return None

    by_stat = {}
    for prop in props:
        stat = MARKET_TO_STAT.get(prop.market)
        if stat is None:
            continue
        by_stat.setdefault(stat, []).append(prop)

    total = 0.0
    for stat, stat_props in by_stat.items():
        rate = getattr(scoring, STAT_TO_RULE[stat])
        curve = _pooled_survival_curve(stat_props)

        if curve and (stat in NO_FALLBACK_STATS or len(curve) >= MIN_THRESHOLDS_FOR_CURVE):
            # decide richness from real market data only, THEN anchor —
            # the assumed point shouldn't count toward "is this rich enough"
            curve = _apply_stat_anchors(curve, stat)
            expected_count = (
                _discrete_tail_sum(curve) if stat in DISCRETE_COUNT_STATS
                else _trapezoidal_expectation(curve)
            )
            total += expected_count * rate
        elif stat in NO_FALLBACK_STATS:
            # Older pre-2026-07-28 rows for rush_rec_tds never recorded a
            # "line" at all (anytime_td/tds_over used to be stored with
            # line=None) — those rows are invisible to
            # _pooled_survival_curve, which requires one. Rather than
            # silently contributing 0 (a real bug found 2026-07-29 that
            # dragged whole players' blended scores toward zero), fall back
            # to directly averaging whatever raw implied_probability values
            # exist — the same calculation this codebase used before
            # threshold-pooling existed.
            probs = [p.implied_probability for p in stat_props if p.implied_probability is not None]
            if not probs:
                continue
            total += (sum(probs) / len(probs)) * rate
        else:
            cv = LINE_MARKET_CV.get(stat, 0.5)
            line_props = [p for p in stat_props if p.line is not None]
            if not line_props:
                continue
            avg_estimate = sum(_effective_line(p, cv) for p in line_props) / len(line_props)
            total += avg_estimate * rate

    return round(total, 2)


def dfs_projection_points(projections: list[DfsProjection]) -> Optional[float]:
    """Averages Underdog/PrizePicks projections when both are available."""
    if not projections:
        return None
    return round(sum(p.projected_points for p in projections) / len(projections), 2)


def blend_expected_points(
    dfs_points: Optional[float],
    betting_points: Optional[float],
    dfs_weight: float = 0.5,
) -> Optional[float]:
    """Weighted average of the two quantitative sources. Falls back to
    whichever single source is available if the other is missing (e.g.
    betting odds not pulled yet), rather than returning nothing."""
    if dfs_points is None and betting_points is None:
        return None
    if dfs_points is None:
        return betting_points
    if betting_points is None:
        return dfs_points
    return round(dfs_points * dfs_weight + betting_points * (1 - dfs_weight), 2)


@dataclass
class ExpertPerspective:
    label: str  # e.g. "Top 12 at position", "Flex-worthy", "Bench"
    considers_startable: bool


def expert_perspective(position: str, position_rank: Optional[int]) -> Optional[ExpertPerspective]:
    if position_rank is None:
        return None
    starter_cutoff = EXPERT_STARTER_RANK_CUTOFF.get(position, 12)
    flex_cutoff = EXPERT_FLEX_RANK_CUTOFF.get(position, 24)
    if position_rank <= starter_cutoff:
        return ExpertPerspective(f"Top {starter_cutoff} at position", considers_startable=True)
    if position_rank <= flex_cutoff:
        return ExpertPerspective("Flex-worthy", considers_startable=True)
    return ExpertPerspective("Bench", considers_startable=False)


@dataclass
class Recommendation:
    call: str  # "Start", "Sit", "Toss-up"
    note: str


def start_sit_recommendation(
    blended_points: Optional[float],
    position: str,
    expert: Optional[ExpertPerspective],
) -> Recommendation:
    """Section 5, step 4-5: compare blended points to a replacement-level
    threshold for a base call, then layer the expert lens on top — surfacing
    disagreement instead of silently overriding either signal."""
    if blended_points is None:
        return Recommendation("Unknown", "No data yet — add odds/projections for this player.")

    threshold = REPLACEMENT_LEVEL.get(position, 10.0)
    margin = blended_points - threshold

    if margin > 1.5:
        quant_call = "Start"
    elif margin < -1.5:
        quant_call = "Sit"
    else:
        quant_call = "Toss-up"

    if expert is None:
        return Recommendation(quant_call, "No expert rank available yet.")

    quant_says_start = quant_call in ("Start", "Toss-up")
    if quant_says_start == expert.considers_startable:
        return Recommendation(quant_call, f"Confirmed by experts ({expert.label}).")

    return Recommendation(
        quant_call,
        f"Conflict: quant says {quant_call}, expert consensus has him as {expert.label} — worth a second look.",
    )
