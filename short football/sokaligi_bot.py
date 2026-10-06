"""Run the SokaLigi three-slip martingale as a state machine, with hard gates.

Why this exists
---------------
The strategy is one ticket per bookmaker per match week, so three accounts
carry slips A, B and C of the same round. Doing that by hand at two-minute
intervals, while also tracking a geometric ladder across three balances, is
where the plan actually fails: a stage gets mis-sized, or a stage gets placed
that the bankroll cannot cover, and the recovery arithmetic silently stops
working. This keeps the ladder honest.

It does three jobs:

1. Sizes the next round from the *live* odds, not the odds from the plan.
   Kiron re-prices every match week; a ladder sized off yesterday's 1.69 stops
   recovering the moment the price moves. Stakes are solved from the cheapest
   winning slip in the current round and rounded up, never down.

2. Refuses to place what the bankroll cannot settle. `sokaligi_math.py ruin`
   shows a 9,785 bankroll funds three stages of a six-stage plan, so the plan
   is really a three-stage plan with a 19.7% bust rate, not a six-stage plan
   with a 3.9% one. The bot will not let that gap be discovered at stage four.

3. Keeps the ledger that settles the argument. Every round records stakes,
   odds, result, return and running profit, so the realised rate can be
   compared against the -14.12% the model predicts. A model and a ledger that
   disagree mean the model is wrong; without the ledger neither can be known.

Placement
---------
Placement is deliberately a seam, not an implementation. The default adapter
prints exactly what to put on each account and waits to be told the result:
automated stake placement against a bookmaker is a term-of-service matter
between the user and the operator, and shipping a credentialed auto-placer
would also mean a losing system running unattended. Anyone who wants that can
implement `PlacementAdapter.place` and register it in ADAPTERS.

Usage
-----
    python sokaligi_bot.py init --bankroll 9785 --base 300
    python sokaligi_bot.py next --odds 1.69,2.17 1.84,1.97 1.69,2.17
    python sokaligi_bot.py settle --results YNY
    python sokaligi_bot.py status
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
from pathlib import Path

import sokaligi_math as M

DATA = Path(__file__).with_name("data")
STATE = DATA / "sokaligi_state.json"
LEDGER = DATA / "sokaligi_ledger.csv"

# Tickets of history before the realised rate is worth comparing to the model.
# At a 16% strike rate, fewer than this and the ledger is noise.
MIN_LEDGER_TICKETS = 150

# Which side each book's slip takes in each of the three markets. The shared
# "Spurs YES" leg is the structure's single point of failure; it is spelled out
# here rather than buried so that changing it is a deliberate act.
SLIPS = {"A": (True, True, True), "B": (False, True, True), "C": (True, True, False)}

# Two accounts at the same operator are settled by one match week, so slips A
# and B see identical results however many people hold the accounts. A third
# account elsewhere is only in the same group if that operator carries the same
# Kiron feed - check the match-week number on both before trusting it.
DEFAULT_BOOKS = ["soka-mine", "soka-friend", "gwala"]
DEFAULT_FEED = "0,0,1"

LEDGER_FIELDS = [
    "placed_utc",
    "cycle",
    "stage",
    "book",
    "slip",
    "legs",
    "odds",
    "stake",
    "result",
    "won",
    "returned",
    "cycle_staked",
    "cycle_returned",
    "bankroll_after",
]


class PlacementAdapter:
    """Hand a sized round to the outside world and get back a result."""

    name = "manual"

    def place(self, tickets: list[dict], feed: str = "shared") -> None:
        width = max(len(t["book"]) for t in tickets)
        print("\n  PLACE NOW - one ticket per account, same match week:")
        for t in tickets:
            print(f"    {t['book']:>{width}s}  slip {t['slip']}  {t['legs']:9s} "
                  f"@ {t['odds']:.3f}  stake {t['stake']:,.0f}")
        draws = len(set(M.parse_feed(feed, len(tickets))))
        example = "/".join(["YNY"] * draws)
        print("\n  Then record the results, one triple per draw"
              f"{' (' + str(draws) + ' operators)' if draws > 1 else ''}:")
        print(f"    python sokaligi_bot.py settle --results {example}")


ADAPTERS = {"manual": PlacementAdapter}


# --------------------------------------------------------------------- state


def load_state() -> dict:
    if not STATE.exists():
        raise SystemExit("No state file. Run `sokaligi_bot.py init` first.")
    with STATE.open(encoding="utf-8") as handle:
        return json.load(handle)


def save_state(state: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    with STATE.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)


def append_ledger(rows: list[dict]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    new = not LEDGER.exists()
    with LEDGER.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEDGER_FIELDS)
        if new:
            writer.writeheader()
        writer.writerows(rows)


# ------------------------------------------------------------------- sizing


def parse_odds(values: list[str]) -> list[tuple[float, float]]:
    if len(values) != 3:
        raise SystemExit("Need exactly three yes,no odds pairs - one per match.")
    out = []
    for value in values:
        try:
            yes, no = (float(x) for x in value.split(","))
        except ValueError:
            raise SystemExit(f"Bad odds pair {value!r}; expected e.g. 1.69,2.17")
        out.append((yes, no))
    return out


def slip_odds(slip: tuple[bool, ...], odds: list[tuple[float, float]]) -> float:
    product = 1.0
    for yes, pair in zip(slip, odds):
        product *= pair[0] if yes else pair[1]
    return product


def stage_stake(state: dict, odds: list[tuple[float, float]]) -> tuple[float, float]:
    """(stake per slip, worst-case gross return per unit of round stake).

    The stake has to clear the deficit on the *cheapest* winning slip, so the
    recovery is solved against that slip rather than the average one. Any
    rounding goes up: rounding a martingale stake down is how a ladder quietly
    stops being a ladder.
    """
    worst = min(slip_odds(slip, odds) for slip in SLIPS.values()) / 3.0
    gain = worst - 1.0
    if gain <= 0.0:
        raise SystemExit(
            f"At these odds the cheapest winning slip returns {worst:.4f} per unit "
            "of round stake, so a winning round still loses money. No stake "
            "recovers this; skip the round."
        )
    deficit = state["cycle_staked"] - state["cycle_returned"]
    target = state["target"] * 3.0 * state["base"]
    if state["stage"] == 0:
        per_round = 3.0 * state["base"]
    else:
        per_round = (deficit + target) / gain
    step = state["step"]
    per_slip = math.ceil(per_round / 3.0 / step) * step if step > 0 else per_round / 3.0
    return per_slip, worst


# ------------------------------------------------------------------ commands


def cmd_init(args: argparse.Namespace) -> int:
    state = {
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "bankroll": args.bankroll,
        "opening_bankroll": args.bankroll,
        "base": args.base,
        "step": args.step,
        "target": args.target,
        "max_stages": args.stages,
        "stop_loss": args.stop_loss if args.stop_loss > 0 else args.bankroll,
        "books": args.books,
        "feed": args.feed,
        "cycle": 1,
        "stage": 0,
        "cycle_staked": 0.0,
        "cycle_returned": 0.0,
        "pending": None,
    }
    if len(args.books) != 3:
        raise SystemExit("Need exactly three book names, one per slip.")
    save_state(state)
    print(f"Initialised. Bankroll {args.bankroll:,.0f}, base {args.base:,.0f} per slip, "
          f"{args.stages} stages max.")

    # Tell the truth about the ladder up front rather than at stage four.
    worst = min(slip_odds(s, list(M.MARKETS.values())) for s in SLIPS.values()) / 3.0
    rows = M.ladder(args.base, args.stages, args.step, worst, args.target * 3 * args.base)
    need = rows[-1]["cumulative"]
    funded = sum(1 for r in rows if r["cumulative"] <= args.bankroll)
    q = M.round_summary("proportional", args.feed)["p_round_loss"]
    print(f"At screenshot odds the {args.stages}-stage ladder needs {need:,.0f} "
          f"to complete; this bankroll funds {funded}.")
    if funded < args.stages:
        print(f"  -> the real plan is {funded} stages with a {q ** funded:.1%} bust "
              f"rate, not {args.stages} with {q ** args.stages:.1%}.")
        print(f"  -> {need:,.0f} is the bankroll that buys the {args.stages}-stage "
              "plan as written.")
    if args.feed != "shared":
        print(f"  Feed groups {args.feed}: slips sharing a group settle on one "
              "match week.")
        print("  Confirm the match-week number matches across operators before "
              "trusting that split.")
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    state = load_state()
    if state["pending"]:
        raise SystemExit("A round is already placed and unsettled. Run `settle` first.")

    stage = state["stage"] + 1
    if stage > state["max_stages"]:
        raise SystemExit(
            f"Ladder exhausted at stage {state['max_stages']}. The cycle has lost "
            f"{state['cycle_staked'] - state['cycle_returned']:,.0f}. "
            "Run `reset` to start a new cycle, deliberately."
        )

    odds = parse_odds(args.odds)
    per_slip, worst = stage_stake(state, odds)
    per_round = 3.0 * per_slip
    committed = state["cycle_staked"] + per_round

    # Gate 1: the round has to be settleable out of the bankroll on hand.
    if per_round > state["bankroll"]:
        raise SystemExit(
            f"Stage {stage} needs {per_round:,.0f} but the bankroll is "
            f"{state['bankroll']:,.0f}. The ladder is unfunded from here; "
            "placing it cannot recover the cycle."
        )
    # Gate 2: a session stop-loss, checked before the stake, not after.
    drawdown = state["opening_bankroll"] - state["bankroll"] + per_round
    if drawdown > state["stop_loss"]:
        raise SystemExit(
            f"Stage {stage} would put session drawdown at {drawdown:,.0f}, past the "
            f"{state['stop_loss']:,.0f} stop-loss. Stopping."
        )

    tickets = []
    for book, (key, slip) in zip(state["books"], SLIPS.items()):
        tickets.append(
            {
                "book": book,
                "slip": key,
                "legs": " ".join("Y" if yes else "N" for yes in slip),
                "odds": slip_odds(slip, odds),
                "stake": per_slip,
            }
        )

    print(f"=== cycle {state['cycle']}, stage {stage} ===")
    print(f"  deficit carried   {state['cycle_staked'] - state['cycle_returned']:,.0f}")
    print(f"  stake per slip    {per_slip:,.0f}   round total {per_round:,.0f}")
    print(f"  worst winning slip returns {worst:.4f}x the round stake -> "
          f"net {worst * per_round - committed:,.0f} if this stage closes the cycle")
    print(f"  bankroll after placing     {state['bankroll'] - per_round:,.0f}")

    ADAPTERS[args.adapter]().place(tickets, state.get("feed", "shared"))

    state["pending"] = {
        "stage": stage,
        "per_slip": per_slip,
        "odds": [list(pair) for pair in odds],
        "tickets": tickets,
        "placed_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    state["stage"] = stage
    state["cycle_staked"] += per_round
    state["bankroll"] -= per_round
    save_state(state)
    return 0


def parse_results(text: str, feed: str = "shared") -> dict[str, tuple[bool, ...]]:
    """Three forms, cheapest first.

    `YNY`              one draw settles every slip
    `YYY/YNY`          one triple per feed group, in group order
    `A:YYY,B:YYY,C:YNY`  explicit per slip, always available
    """
    def triple(value: str) -> tuple[bool, ...]:
        value = value.strip().upper()
        if len(value) != 3 or set(value) - {"Y", "N"}:
            raise SystemExit(f"Bad result {value!r}; expected three Y/N, e.g. YNY")
        return tuple(c == "Y" for c in value)

    if "/" in text:
        # One triple per feed group, in group order: "YYY/YNY" means the
        # SokaBet draw landed YYY and the Gwala draw landed YNY.
        groups = M.parse_feed(feed or "shared", len(SLIPS))
        drawn = [triple(part) for part in text.split("/")]
        if len(drawn) != len(set(groups)):
            raise SystemExit(
                f"Feed {feed!r} has {len(set(groups))} draw(s); got {len(drawn)}"
            )
        order = sorted(set(groups))
        return {key: drawn[order.index(g)] for key, g in zip(SLIPS, groups)}
    if ":" not in text:
        shared = triple(text)
        return {key: shared for key in SLIPS}
    out = {}
    for part in text.split(","):
        key, _, value = part.partition(":")
        out[key.strip().upper()] = triple(value)
    missing = set(SLIPS) - set(out)
    if missing:
        raise SystemExit(f"No result given for slip(s) {sorted(missing)}")
    return out


def cmd_settle(args: argparse.Namespace) -> int:
    state = load_state()
    pending = state["pending"]
    if not pending:
        raise SystemExit("Nothing pending. Run `next` first.")

    results = parse_results(args.results, state.get("feed", "shared"))
    odds = [tuple(pair) for pair in pending["odds"]]
    rows, returned = [], 0.0
    for ticket in pending["tickets"]:
        slip = SLIPS[ticket["slip"]]
        drawn = results[ticket["slip"]]
        won = slip == drawn
        payout = ticket["stake"] * ticket["odds"] if won else 0.0
        returned += payout
        rows.append(
            {
                "placed_utc": pending["placed_utc"],
                "cycle": state["cycle"],
                "stage": pending["stage"],
                "book": ticket["book"],
                "slip": ticket["slip"],
                "legs": ticket["legs"],
                "odds": f"{ticket['odds']:.4f}",
                "stake": f"{ticket['stake']:.2f}",
                "result": "".join("Y" if y else "N" for y in drawn),
                "won": int(won),
                "returned": f"{payout:.2f}",
            }
        )

    state["cycle_returned"] += returned
    state["bankroll"] += returned
    net = state["cycle_returned"] - state["cycle_staked"]
    for row in rows:
        row |= {
            "cycle_staked": f"{state['cycle_staked']:.2f}",
            "cycle_returned": f"{state['cycle_returned']:.2f}",
            "bankroll_after": f"{state['bankroll']:.2f}",
        }
    append_ledger(rows)

    print(f"=== settled cycle {state['cycle']} stage {pending['stage']} ===")
    for row in rows:
        mark = "WON " if row["won"] else "lost"
        print(f"  {row['book']:>8s} slip {row['slip']} {row['legs']} vs "
              f"{row['result']}  {mark} {float(row['returned']):,.0f}")
    print(f"  cycle net {net:+,.0f}   bankroll {state['bankroll']:,.0f}")

    target = state["target"] * 3.0 * state["base"]
    if net >= target:
        print(f"  cycle closed in profit after {pending['stage']} stage(s). "
              "Ladder resets.")
        state["cycle"] += 1
        state["stage"] = 0
        state["cycle_staked"] = 0.0
        state["cycle_returned"] = 0.0
    elif pending["stage"] >= state["max_stages"]:
        print(f"  LADDER BUSTED at stage {state['max_stages']}: {net:+,.0f}.")
        state["cycle"] += 1
        state["stage"] = 0
        state["cycle_staked"] = 0.0
        state["cycle_returned"] = 0.0
    else:
        print(f"  deficit {-net:,.0f} carried to stage {pending['stage'] + 1}.")

    state["pending"] = None
    save_state(state)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    state = load_state()
    print("=== state ===")
    print(f"  bankroll {state['bankroll']:,.2f} of opening "
          f"{state['opening_bankroll']:,.2f} "
          f"({state['bankroll'] - state['opening_bankroll']:+,.2f})")
    print(f"  cycle {state['cycle']}, stage {state['stage']} of "
          f"{state['max_stages']}")
    print(f"  deficit in play {state['cycle_staked'] - state['cycle_returned']:,.2f}")
    print(f"  pending: {'yes' if state['pending'] else 'no'}")

    if not LEDGER.exists():
        print("\n  No ledger yet - nothing to compare the model against.")
        return 0

    with LEDGER.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    staked = sum(float(r["stake"]) for r in rows)
    back = sum(float(r["returned"]) for r in rows)
    wins = sum(int(r["won"]) for r in rows)
    print(f"\n=== ledger: {len(rows)} tickets over "
          f"{len({(r['cycle'], r['stage']) for r in rows})} rounds ===")
    print(f"  staked {staked:,.0f}  returned {back:,.0f}  net {back - staked:+,.0f}")
    if staked:
        realised = back / staked - 1.0
        model = M.round_summary("proportional", state.get("feed", "shared"))["edge"]
        print(f"  realised {realised:+.2%} of turnover vs model {model:+.2%}")
        print(f"  ticket strike rate {wins / len(rows):.4f}")
        # A treble ladder swings +75% or -100% on a single round, so a short
        # ledger disagrees with the model for free. Only flag divergence once
        # the sample can carry it.
        if len(rows) < MIN_LEDGER_TICKETS:
            print(f"  sample too short to test the model "
                  f"({len(rows)}/{MIN_LEDGER_TICKETS} tickets); no verdict yet")
        elif abs(realised - model) > 0.05:
            print("  Ledger and model disagree by more than 5 points. The ledger "
                  "wins:\n  re-check the de-vig assumption before trusting any "
                  "figure above.")
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    state = load_state()
    deficit = state["cycle_staked"] - state["cycle_returned"]
    state |= {"cycle": state["cycle"] + 1, "stage": 0, "cycle_staked": 0.0,
              "cycle_returned": 0.0, "pending": None}
    save_state(state)
    print(f"Cycle abandoned with {deficit:,.0f} unrecovered. New cycle "
          f"{state['cycle']} at stage 0.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)

    i = sub.add_parser("init", help="create the state file")
    i.add_argument("--bankroll", type=float, required=True)
    i.add_argument("--base", type=float, default=100.0)
    i.add_argument("--stages", type=int, default=6)
    i.add_argument("--step", type=float, default=100.0)
    i.add_argument("--target", type=float, default=0.0,
                   help="profit on close, in base round stakes")
    i.add_argument("--stop-loss", type=float, default=0.0,
                   help="max session drawdown; defaults to the whole bankroll")
    i.add_argument("--books", nargs=3, default=DEFAULT_BOOKS)
    i.add_argument("--feed", default=DEFAULT_FEED,
                   help="which draw settles each slip; shared, independent, or 0,0,1")

    n = sub.add_parser("next", help="size and place the next stage")
    n.add_argument("--odds", nargs=3, required=True,
                   metavar="YES,NO", help="live BTTS odds for the three matches")
    n.add_argument("--adapter", choices=sorted(ADAPTERS), default="manual")

    s = sub.add_parser("settle", help="record the match week's results")
    s.add_argument("--results", required=True,
                   help="YNY, or YYY/YNY per feed group, or A:YYY,B:YYY,C:YNY")

    sub.add_parser("status", help="state plus realised-vs-model ledger")
    sub.add_parser("reset", help="abandon the current cycle")

    args = parser.parse_args()
    return {
        "init": cmd_init, "next": cmd_next, "settle": cmd_settle,
        "status": cmd_status, "reset": cmd_reset,
    }[args.mode](args)


if __name__ == "__main__":
    raise SystemExit(main())
