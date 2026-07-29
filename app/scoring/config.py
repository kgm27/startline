"""League scoring rules, kept as data (not hardcoded logic) so standard/PPR
support in a later phase just means adding another entry here."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ScoringRules:
    points_per_pass_yard: float
    points_per_rush_yard: float
    points_per_reception_yard: float
    points_per_reception: float
    points_per_pass_td: float
    points_per_rush_or_rec_td: float
    points_per_interception: float  # negative; fumbles intentionally excluded per owner's call


SCORING_RULES = {
    "standard": ScoringRules(
        points_per_pass_yard=0.04,
        points_per_rush_yard=0.1,
        points_per_reception_yard=0.1,
        points_per_reception=0.0,
        points_per_pass_td=4,
        points_per_rush_or_rec_td=6,
        points_per_interception=-2,
    ),
    "half_ppr": ScoringRules(
        points_per_pass_yard=0.04,
        points_per_rush_yard=0.1,
        points_per_reception_yard=0.1,
        points_per_reception=0.5,
        points_per_pass_td=4,
        points_per_rush_or_rec_td=6,
        points_per_interception=-2,
    ),
    "full_ppr": ScoringRules(
        points_per_pass_yard=0.04,
        points_per_rush_yard=0.1,
        points_per_reception_yard=0.1,
        points_per_reception=1.0,
        points_per_pass_td=4,
        points_per_rush_or_rec_td=6,
        points_per_interception=-2,
    ),
}

# Rough weekly points needed to be a viable starter, per position (half-PPR).
# Starting point only — the brief flags this as something to tune with real
# results, not a final number.
REPLACEMENT_LEVEL = {
    "QB": 18.0,
    "RB": 12.0,
    "WR": 11.0,
    "TE": 8.0,
}
