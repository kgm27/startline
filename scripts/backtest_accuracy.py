"""Backtest: are sportsbook-derived projections or DFS projections more
accurate at predicting actual fantasy points?

Joins three things for one past week:
  - the DFS projection    (dfs_projections, via blend.dfs_projection_points)
  - the sportsbook number (odds_props,      via blend.betting_derived_points)
  - what actually happened (free Sleeper stats endpoint, priced with the
    SAME ScoringRules the projections are priced with, so the comparison is
    apples-to-apples: no fumbles, no 2-pointers, no return yards — none of
    which either projection is trying to predict in the first place)

Run:  ./.venv/bin/python scripts/backtest_accuracy.py --week 15 --season 2025
"""
import argparse
import json
import random
import urllib.request
from collections import defaultdict
from math import comb, sqrt
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import SessionLocal
from app.models import DfsProjection, OddsProp, Player
from app.scoring.blend import betting_derived_points, dfs_projection_points
from app.scoring.config import SCORING_RULES
from app.config import get_settings

CACHE = Path(__file__).resolve().parent.parent / "data" / "_cache"

# Sleeper's raw stat keys -> the ScoringRules field that prices them. Only
# the stats the two projections actually forecast appear here; see module
# docstring for why fumbles/2PT are deliberately absent.
STAT_FIELDS = {
    "pass_yd": "points_per_pass_yard",
    "rush_yd": "points_per_rush_yard",
    "rec_yd": "points_per_reception_yard",
    "rec": "points_per_reception",
    "pass_td": "points_per_pass_td",
    "pass_int": "points_per_interception",
}
TD_FIELDS = ("rush_td", "rec_td")  # both priced at points_per_rush_or_rec_td


def fetch_actuals(season: int, week: int) -> dict:
    """Actual box-score stats, keyed by Sleeper player_id — the same id this
    project uses as its own primary key, so the join needs no name matching.
    Free endpoint, no API key. Cached: a finished week never changes."""
    path = CACHE / f"actuals_{season}_wk{week}.json"
    if path.exists():
        return json.loads(path.read_text())
    url = f"https://api.sleeper.app/v1/stats/nfl/regular/{season}/{week}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = json.load(resp)
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return data


def actual_points(stats: dict, rules) -> float:
    total = 0.0
    for field, rule in STAT_FIELDS.items():
        total += (stats.get(field) or 0.0) * getattr(rules, rule)
    for field in TD_FIELDS:
        total += (stats.get(field) or 0.0) * rules.points_per_rush_or_rec_td
    return total


def bootstrap_ci(pairs, stat_fn, n=10000, seed=0):
    """Percentile CI for a paired statistic, resampling PLAYERS (not errors)
    so the DFS/book pairing is preserved in every resample."""
    rng = random.Random(seed)
    k = len(pairs)
    out = []
    for _ in range(n):
        sample = [pairs[rng.randrange(k)] for _ in range(k)]
        out.append(stat_fn(sample))
    out.sort()
    return out[int(0.025 * n)], out[int(0.975 * n)]


def sign_test_p(wins: int, total: int) -> float:
    """Exact two-sided binomial test against a 50/50 coin."""
    if total == 0:
        return 1.0
    k = min(wins, total - wins)
    tail = sum(comb(total, i) for i in range(k + 1)) / (2 ** total)
    return min(1.0, 2 * tail)


def mae(rows, key):
    return sum(abs(r[key] - r["actual"]) for r in rows) / len(rows)


def rmse(rows, key):
    return sqrt(sum((r[key] - r["actual"]) ** 2 for r in rows) / len(rows))


def bias(rows, key):
    return sum(r[key] - r["actual"] for r in rows) / len(rows)


def correlation(rows, key):
    n = len(rows)
    mx = sum(r[key] for r in rows) / n
    my = sum(r["actual"] for r in rows) / n
    cov = sum((r[key] - mx) * (r["actual"] - my) for r in rows)
    vx = sum((r[key] - mx) ** 2 for r in rows)
    vy = sum((r["actual"] - my) ** 2 for r in rows)
    return cov / sqrt(vx * vy) if vx and vy else float("nan")


def startsit_accuracy(rows, key, min_gap=0.0):
    """The question the site actually answers: given two players at the same
    position, does this projection put the higher real scorer on top? Counts
    every same-position pair. min_gap ignores pairs whose actual scores were
    within a hair of each other, where 'getting it right' is a coin flip."""
    right = total = 0
    by_pos = defaultdict(list)
    for r in rows:
        by_pos[r["position"]].append(r)
    for players in by_pos.values():
        for i in range(len(players)):
            for j in range(i + 1, len(players)):
                a, b = players[i], players[j]
                if abs(a["actual"] - b["actual"]) <= min_gap:
                    continue
                if a[key] == b[key]:
                    continue
                total += 1
                picked_a = a[key] > b[key]
                truth_a = a["actual"] > b["actual"]
                right += picked_a == truth_a
    return right, total


def report(rows, label, out):
    out(f"\n{'=' * 74}\n{label}  (n = {len(rows)})\n{'=' * 74}")
    if len(rows) < 3:
        out("  too few players to say anything")
        return
    out(f"{'metric':<34}{'sportsbook':>13}{'DFS':>13}{'winner':>13}")
    out("-" * 74)
    for name, fn, lower_better in (
        ("Mean absolute error (pts)", mae, True),
        ("Root mean squared error", rmse, True),
        ("Bias (proj - actual)", bias, None),
        ("Correlation with actual", correlation, False),
    ):
        b, d = fn(rows, "book"), fn(rows, "dfs")
        if lower_better is None:
            win = "—"
        elif (b < d) == lower_better:
            win = "sportsbook"
        else:
            win = "DFS"
        if lower_better is None:
            win = "sportsbook" if abs(b) < abs(d) else "DFS"
        out(f"{name:<34}{b:>13.3f}{d:>13.3f}{win:>13}")

    diff = mae(rows, "book") - mae(rows, "dfs")
    lo, hi = bootstrap_ci(rows, lambda s: mae(s, "book") - mae(s, "dfs"))
    out(f"\nMAE gap (sportsbook - DFS): {diff:+.3f} pts   95% CI [{lo:+.3f}, {hi:+.3f}]")
    out("  negative = sportsbook closer. CI spanning 0 = not distinguishable.")

    book_wins = sum(
        abs(r["book"] - r["actual"]) < abs(r["dfs"] - r["actual"]) for r in rows
    )
    p = sign_test_p(book_wins, len(rows))
    out(
        f"\nPer-player head-to-head: sportsbook closer on {book_wins}/{len(rows)}"
        f" ({book_wins / len(rows):.1%})   sign-test p = {p:.3f}"
    )

    out("\nStart/sit calls — same-position pairs, higher real scorer on top:")
    for gap, note in ((0.0, "all pairs"), (3.0, "excluding near-ties < 3 pts apart")):
        br, bt = startsit_accuracy(rows, "book", gap)
        dr, dt = startsit_accuracy(rows, "dfs", gap)
        if not (bt and dt):
            continue
        # Pairs are NOT independent (each player appears in many of them), so
        # a naive test over 3,774 pairs would wildly overstate significance.
        # Resampling PLAYERS and rebuilding the pairs from each resample is
        # the honest way to size the uncertainty here.
        def gap_stat(sample, _g=gap):
            r1, t1 = startsit_accuracy(sample, "book", _g)
            r2, t2 = startsit_accuracy(sample, "dfs", _g)
            return (r1 / t1 - r2 / t2) if t1 and t2 else 0.0

        lo, hi = bootstrap_ci(rows, gap_stat, n=2000)
        out(
            f"  {note:<38} sportsbook {br / bt:.1%}   DFS {dr / dt:.1%}"
            f"   ({bt} pairs)"
        )
        out(
            f"  {'':<38} edge {br / bt - dr / dt:+.1%}"
            f"   95% CI [{lo:+.1%}, {hi:+.1%}]"
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, default=15)
    ap.add_argument("--season", type=int, default=2025)
    ap.add_argument(
        "--include-dnp",
        action="store_true",
        help="also count players who never took the field (actual = 0)",
    )
    ap.add_argument(
        "--db",
        help="path to an alternate SQLite file (e.g. a scratch DB holding a "
             "backfilled past season, kept apart from the live one because "
             "the schema keys on week with no season column)",
    )
    args = ap.parse_args()

    settings = get_settings()
    rules = SCORING_RULES[settings.scoring_format]
    actuals = fetch_actuals(args.season, args.week)
    if args.db:
        engine = create_engine(f"sqlite:///{args.db}",
                               connect_args={"check_same_thread": False})
        db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    else:
        db = SessionLocal()
    lines = []
    out = lambda s: (print(s), lines.append(s))

    dfs_by_player = defaultdict(list)
    for p in db.query(DfsProjection).filter(DfsProjection.week == args.week):
        dfs_by_player[p.player_id].append(p)
    props_by_player = defaultdict(list)
    for p in db.query(OddsProp).filter(OddsProp.week == args.week):
        props_by_player[p.player_id].append(p)

    rows, skipped = [], defaultdict(int)
    for pid in set(dfs_by_player) & set(props_by_player):
        player = db.query(Player).filter(Player.id == pid).first()
        stats = actuals.get(pid)
        if player is None or stats is None:
            skipped["no player row / no stat line at all"] += 1
            continue
        played = (stats.get("gp") or stats.get("gms_active") or 0) >= 1
        if not played and not args.include_dnp:
            skipped["did not play (see --include-dnp)"] += 1
            continue
        d = dfs_projection_points(dfs_by_player[pid])
        b = betting_derived_points(props_by_player[pid], rules)
        if d is None or b is None:
            skipped["no usable projection from one side"] += 1
            continue
        rows.append(
            {
                "name": player.name,
                "position": player.position,
                "dfs": d,
                "book": b,
                "actual": actual_points(stats, rules) if played else 0.0,
            }
        )

    out(
        f"Week {args.week}, {args.season} season | scoring: {settings.scoring_format}"
        f" | players compared: {len(rows)}"
    )
    for reason, n in sorted(skipped.items(), key=lambda kv: -kv[1]):
        out(f"  skipped {n:>3}  {reason}")

    report(rows, "ALL POSITIONS", out)
    for pos in ("QB", "RB", "WR", "TE"):
        subset = [r for r in rows if r["position"] == pos]
        if len(subset) >= 8:
            report(subset, pos, out)

    out("\n" + "=" * 74)
    out("Biggest misses (by how far the two projections disagreed)")
    out("=" * 74)
    out(f"{'player':<24}{'pos':>4}{'book':>9}{'DFS':>9}{'actual':>9}{'closer':>12}")
    rows.sort(key=lambda r: -abs(r["book"] - r["dfs"]))
    for r in rows[:15]:
        closer = (
            "sportsbook"
            if abs(r["book"] - r["actual"]) < abs(r["dfs"] - r["actual"])
            else "DFS"
        )
        out(
            f"{r['name'][:23]:<24}{r['position']:>4}{r['book']:>9.1f}"
            f"{r['dfs']:>9.1f}{r['actual']:>9.1f}{closer:>12}"
        )

    # Written into the gitignored cache dir: a report is a run artifact, not
    # source, and shouldn't land in the repo root waiting to be committed.
    CACHE.mkdir(parents=True, exist_ok=True)
    report_path = CACHE / f"backtest_{args.season}_wk{args.week}.txt"
    report_path.write_text("\n".join(lines))
    print(f"\nreport written to {report_path}")
    db.close()


if __name__ == "__main__":
    main()
