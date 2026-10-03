"""Price every Short Football 2x2 market off the scraped history.

For each team pool, this prints the empirical probability of each market
outcome and the break-even ("fair") decimal odds that follow from it. Compare
those against the odds Helabet actually offers to find where its prices differ
from the historical distribution.

Run after scrape_shortfootball.py:

    python analyze_markets.py
    python analyze_markets.py --quote-1 2.064 --quote-x 8.96 --quote-2 2.064

Pools
-----
The main championship (champ 2055906) mixes two team sets that never meet:
names carrying a "(2x2)" suffix, and names without it. They have materially
different goal distributions, so every figure is reported per pool.
"""

from __future__ import annotations

import argparse
import collections
import csv
import math
import statistics
from pathlib import Path

MAIN_LEAGUE = "Short Football 2x2"
MIN_GAMES = 150  # per-team sample floor before a team's rate is worth quoting


def load(path: Path, league: str) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [row for row in csv.DictReader(handle) if row["league"] == league]


def pool_of(row: dict) -> str:
    return "suffix" if "(2x2)" in row["home"] else "plain"


def fair(probability: float) -> str:
    return f"{1 / probability:.3f}" if probability > 0 else "-"


def edge(probability: float, odds: float | None) -> str:
    """Expected value per unit staked at `odds`, or blank if no odds given."""
    if not odds:
        return ""
    return f"   offered {odds:.3f} -> EV {probability * odds - 1:+.4f}"


def report_pool(rows: list[dict], args: argparse.Namespace) -> None:
    n = len(rows)
    totals = [int(row["total_goals"]) for row in rows]
    outcomes = collections.Counter(row["result_1x2"] for row in rows)
    p1, px, p2 = (outcomes[k] / n for k in "1X2")

    print(f"  matches {n}")
    print(
        f"  total goals: mean {statistics.mean(totals):.3f} "
        f"sd {statistics.pstdev(totals):.3f} "
        f"var/mean {statistics.pvariance(totals) / statistics.mean(totals):.3f} "
        "(1.0 = Poisson)"
    )

    print("\n  1X2")
    for label, probability, quote in (
        ("1", p1, args.quote_1),
        ("X", px, args.quote_x),
        ("2", p2, args.quote_2),
    ):
        print(f"    {label:2s} {probability:.4f}  fair {fair(probability)}"
              f"{edge(probability, quote)}")

    print("\n  Double chance")
    for label, probability in (("1X", p1 + px), ("12", p1 + p2), ("X2", px + p2)):
        print(f"    {label:2s} {probability:.4f}  fair {fair(probability)}")

    print("\n  Totals, half-goal lines")
    for line in (12.5, 13.5, 14.5, 15.5, 16.5, 17.5):
        over = sum(1 for value in totals if value > line) / n
        print(
            f"    {line:5.1f}  over {over:.4f} fair {fair(over)}"
            f"   under {1 - over:.4f} fair {fair(1 - over)}"
        )

    print("\n  Totals, whole-goal lines (exact total voids the bet)")
    for line in (14, 15, 16):
        over = sum(1 for value in totals if value > line) / n
        push = sum(1 for value in totals if value == line) / n
        under = sum(1 for value in totals if value < line) / n
        live = over + under
        print(
            f"    {line:5d}  over {over:.4f} push {push:.4f} under {under:.4f}"
            f"   fair over {fair(over / live)} under {fair(under / live)}"
        )

    btts = sum(int(row["btts"]) for row in rows) / n
    print(f"\n  BTTS yes {btts:.4f}  fair {fair(btts)}")

    print("\n  Team strength (teams with "
          f"{MIN_GAMES}+ matches)")
    wins: collections.Counter = collections.Counter()
    played: collections.Counter = collections.Counter()
    scored: collections.Counter = collections.Counter()
    for row in rows:
        home_goals, away_goals = int(row["home_goals"]), int(row["away_goals"])
        home, away = row["home"], row["away"]
        played[home] += 1
        played[away] += 1
        scored[home] += home_goals
        scored[away] += away_goals
        if home_goals > away_goals:
            wins[home] += 1
        elif away_goals > home_goals:
            wins[away] += 1

    eligible = [t for t in played if played[t] >= MIN_GAMES]
    win_rates = sorted((wins[t] / played[t], t, played[t]) for t in eligible)
    goal_rates = sorted((scored[t] / played[t], t, played[t]) for t in eligible)

    # Spread across teams only means something next to the spread sampling noise
    # alone would produce. A ratio near 1.0 says the teams are interchangeable.
    for name, series in (("win rate", win_rates), ("goals/game", goal_rates)):
        spread = statistics.pstdev([v for v, _, _ in series])
        if name == "win rate":
            noise = statistics.mean(math.sqrt(v * (1 - v) / g) for v, _, g in series)
        else:
            noise = statistics.mean(math.sqrt(v / g) for v, _, g in series)
        print(
            f"    {name:10s} spread {spread:.4f} vs noise {noise:.4f} "
            f"= {spread / noise:.2f}x"
        )

    print(f"    weakest by win rate: "
          + ", ".join(f"{t} {v:.3f}" for v, t, _ in win_rates[:3]))
    print(f"    strongest by win rate: "
          + ", ".join(f"{t} {v:.3f}" for v, t, _ in win_rates[-3:]))

    if args.quote_1:
        best_rate, best_team, games = win_rates[-1]
        margin = 1.96 * math.sqrt(best_rate * (1 - best_rate) / games)
        print(
            f"    backing {best_team} at {args.quote_1:.3f}: "
            f"EV {best_rate * args.quote_1 - 1:+.4f}, but win rate is "
            f"{best_rate:.3f} +-{margin:.3f}, and this team is the best of "
            f"{len(win_rates)} - treat as noise until priced odds confirm it"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Price markets from scraped history.")
    parser.add_argument(
        "--csv",
        default=str(Path(__file__).with_name("data") / "shortfootball_2x2.csv"),
    )
    parser.add_argument("--league", default=MAIN_LEAGUE)
    parser.add_argument("--quote-1", type=float, help="offered odds for home win")
    parser.add_argument("--quote-x", type=float, help="offered odds for draw")
    parser.add_argument("--quote-2", type=float, help="offered odds for away win")
    args = parser.parse_args()

    rows = load(Path(args.csv), args.league)
    if not rows:
        print(f"No rows for league {args.league!r} in {args.csv}")
        return 1

    by_pool: dict[str, list[dict]] = collections.defaultdict(list)
    for row in rows:
        by_pool[pool_of(row)].append(row)

    for pool in sorted(by_pool):
        print(f"\n=== {pool} pool ===")
        report_pool(by_pool[pool], args)

    print("\n=== pool comparison ===")
    for pool, subset in sorted(by_pool.items()):
        totals = [int(row["total_goals"]) for row in subset]
        mean = statistics.mean(totals)
        stderr = statistics.pstdev(totals) / math.sqrt(len(totals))
        draws = sum(1 for row in subset if row["result_1x2"] == "X") / len(subset)
        print(
            f"  {pool:7s} mean total {mean:.3f} +-{1.96 * stderr:.3f}   "
            f"draw rate {draws:.4f}"
        )
    print(
        "  A single shared total line or draw price across both pools is a\n"
        "  mispricing against at least one of them."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
