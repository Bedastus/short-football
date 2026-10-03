"""Scan logged odds snapshots for arbitrage, middles, and pricing structure.

Reads data/odds_snapshots.csv (written by collect_odds.py) and, for every
snapshot of every match, asks three questions:

1. Overround per two-way market - how much the book charges on each line.
2. Arbitrage - is there a set of stakes across the selections offered in that
   one snapshot that returns more than it costs in *every* possible outcome?
3. Middles - pairs that both win on a narrow band of totals. A middle is not
   arbitrage: it loses outside the band. Reported separately with the band's
   historical probability so the trade can be priced honestly.

Outcome space
-------------
A snapshot is evaluated over joint outcomes (result, total goals). The two are
linked: a draw requires an even total, which is enforced, so no impossible
outcome is ever used to "prove" an arb away.

Whole-number lines (Total 15, Handicap 0) void the stake when the result lands
exactly on the line; that is modelled as a return of 1.0, not a loss.
"""

from __future__ import annotations

import argparse
import collections
import csv
import itertools
import math
import statistics
from pathlib import Path

MAX_TOTAL = 40


def payoff(market: str, line: float | None, odds: float, result: str, total: int) -> float:
    """Return per 1 unit staked on `market` given the realised outcome."""
    if market == "W1":
        return odds if result == "1" else 0.0
    if market == "X":
        return odds if result == "X" else 0.0
    if market == "W2":
        return odds if result == "2" else 0.0
    if market == "DC 1X":
        return odds if result in ("1", "X") else 0.0
    if market == "DC 12":
        return odds if result in ("1", "2") else 0.0
    if market == "DC X2":
        return odds if result in ("X", "2") else 0.0

    if line is None:
        return 0.0

    if market in ("Total Over", "Total Under"):
        if abs(line - round(line)) < 1e-9:  # whole line: exact total voids
            if total == round(line):
                return 1.0
        if market == "Total Over":
            return odds if total > line else 0.0
        return odds if total < line else 0.0

    if market in ("Asian Total Over", "Asian Total Under"):
        # A quarter line splits the stake over the two neighbouring half-lines.
        lower, upper = line - 0.25, line + 0.25
        legs = []
        for half in (lower, upper):
            legs.append(payoff(market.replace("Asian ", ""), half, odds, result, total))
        return 0.5 * (legs[0] + legs[1])

    return 0.0


def outcomes() -> list[tuple[str, int]]:
    """Every joint outcome. A draw needs an even total, so odd totals exclude X."""
    space = []
    for total in range(MAX_TOTAL + 1):
        space.append(("1", total))
        space.append(("2", total))
        if total % 2 == 0:
            space.append(("X", total))
    return space


SPACE = outcomes()


def guaranteed_return(legs: list[tuple], weights: tuple[float, ...]) -> float:
    """Worst-case return per 1 unit total stake for these legs at these weights."""
    worst = math.inf
    for result, total in SPACE:
        gross = 0.0
        for (market, line, odds), weight in zip(legs, weights):
            gross += weight * payoff(market, line, odds, result, total)
        worst = min(worst, gross)
        if worst <= 0.0:
            break
    return worst


def simplex_grid(n: int, step: int) -> list[tuple[float, ...]]:
    """Stake weight vectors summing to 1, on a grid of `step` divisions."""
    grids = []
    for cut in itertools.combinations_with_replacement(range(step + 1), n - 1):
        parts = []
        previous = 0
        for value in cut:
            parts.append(value - previous)
            previous = value
        parts.append(step - previous)
        if all(p >= 0 for p in parts) and sum(parts) == step:
            for perm in set(itertools.permutations(parts)):
                grids.append(tuple(p / step for p in perm))
    return list(set(grids))


def load_snapshots(path: Path) -> dict[tuple, list[dict]]:
    with path.open(encoding="utf-8") as handle:
        rows = [r for r in csv.DictReader(handle) if r["scope"] == "match"]
    groups: dict[tuple, list[dict]] = collections.defaultdict(list)
    for row in rows:
        if not row["market"] or row["market_confidence"] != "verified":
            continue
        try:
            row["_odds"] = float(row["odds"])
        except (TypeError, ValueError):
            continue
        row["_line"] = float(row["parameter"]) if row["parameter"] else None
        groups[(row["match_id"], row["timer_sec"], row["score"])].append(row)
    return groups


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshots",
        default=str(Path(__file__).with_name("data") / "odds_snapshots.csv"),
    )
    parser.add_argument(
        "--results",
        default=str(Path(__file__).with_name("data") / "shortfootball_2x2.csv"),
        help="history, used to price middles",
    )
    parser.add_argument("--step", type=int, default=20, help="stake grid divisions")
    args = parser.parse_args()

    snaps = load_snapshots(Path(args.snapshots))
    print(f"{len(snaps)} snapshots with verified markets\n")

    # --- 1. overround by market and by whether the line is the central one ---
    central, offset, other = [], [], []
    for legs in snaps.values():
        totals: dict[float, dict[str, float]] = collections.defaultdict(dict)
        for row in legs:
            if row["market"] in ("Total Over", "Total Under") and row["_line"] is not None:
                totals[row["_line"]][row["market"]] = row["_odds"]
        pairs = {
            line: 1 / d["Total Over"] + 1 / d["Total Under"]
            for line, d in totals.items()
            if "Total Over" in d and "Total Under" in d
        }
        if pairs:
            best = min(pairs.values())
            for value in pairs.values():
                (central if value == best else offset).append(value)

        book = {r["market"]: r["_odds"] for r in legs if r["market"] in ("W1", "X", "W2")}
        if len(book) == 3:
            other.append(sum(1 / v for v in book.values()))

    def summarise(name: str, values: list[float]) -> None:
        if not values:
            return
        print(
            f"  {name:34s} n={len(values):4d}  "
            f"median {100 * (statistics.median(values) - 1):+.2f}%  "
            f"range {100 * (min(values) - 1):+.2f}% .. {100 * (max(values) - 1):+.2f}%"
        )

    print("Overround")
    summarise("Total, cheapest line in snapshot", central)
    summarise("Total, every other line", offset)
    summarise("1X2", other)

    # --- 2. arbitrage search ---
    print("\nArbitrage search (guaranteed return > 1.0 in every outcome)")
    best_overall = (0.0, None)
    grids = {n: simplex_grid(n, args.step) for n in (2, 3)}
    for key, legs in snaps.items():
        selections = [(r["market"], r["_line"], r["_odds"]) for r in legs]
        for size in (2, 3):
            for combo in itertools.combinations(selections, size):
                for weights in grids[size]:
                    value = guaranteed_return(list(combo), weights)
                    if value > best_overall[0]:
                        best_overall = (value, (key, combo, weights))
    value, detail = best_overall
    print(f"  best guaranteed return found: {value:.4f} per 1 staked")
    if value > 1.0:
        print(f"  ARBITRAGE: {detail}")
    else:
        print("  no arbitrage - every combination loses in at least one outcome")

    # --- 3. middles ---
    print("\nMiddles (both legs win on a band of totals; loses outside it)")
    history = []
    results_path = Path(args.results)
    if results_path.exists():
        with results_path.open(encoding="utf-8") as handle:
            history = [
                int(r["total_goals"])
                for r in csv.DictReader(handle)
                if r["league"] == "Short Football 2x2"
            ]

    found = []
    for key, legs in snaps.items():
        overs = [r for r in legs if r["market"] == "Total Over" and r["_line"] is not None]
        unders = [r for r in legs if r["market"] == "Total Under" and r["_line"] is not None]
        for over in overs:
            for under in unders:
                if under["_line"] <= over["_line"]:
                    continue
                band = [
                    t for t in range(MAX_TOTAL + 1)
                    if t > over["_line"] and t < under["_line"]
                ]
                if not band:
                    continue
                stake = 2.0
                win_both = (over["_odds"] + under["_odds"]) / stake
                one_leg = min(over["_odds"], under["_odds"]) / stake
                probability = (
                    sum(1 for t in history if t in band) / len(history) if history else 0.0
                )
                expected = probability * win_both + (1 - probability) * one_leg
                found.append(
                    (expected, key, over["_line"], under["_line"], band,
                     win_both, one_leg, probability)
                )

    found.sort(reverse=True)
    if not found:
        print("  none offered in these snapshots")
    for expected, key, lo, hi, band, both, one, probability in found[:5]:
        print(
            f"  O{lo}/U{hi}  band {band}  P(band)={probability:.4f}  "
            f"both win {both:.3f}x  one leg {one:.3f}x  -> EV {expected - 1:+.4f}"
        )
    print(
        "\n  Note: middle EV uses the unconditional historical total. A snapshot\n"
        "  taken mid-match must be priced against the remaining goals instead,\n"
        "  so only kickoff snapshots (timer 0, score 0-0) are safe to read here."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
