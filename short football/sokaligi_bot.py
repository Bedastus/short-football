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

# All three accounts are at the same operator, so one match week settles every
# slip and the three stay mutually exclusive: at most one can win per round.
# `--feed` still takes groups, for a layout that later spans operators.
DEFAULT_BOOKS = ["soka-1", "soka-2", "soka-3"]
DEFAULT_FEED = "shared"

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

    def place(self, tickets: list[dict], feed: str = "shared",
              hint: bool = True) -> None:
        # One card per person, each spelling the three BTTS picks against the
        # match names, so three people at three screens each read only theirs
        # and nobody has to decode "Y Y Y" under a two-minute clock.
        matches = list(M.MARKETS)
        print("\n  DISTRIBUTE - each person places ONE ticket on their own account:")
        for t in tickets:
            picks = t["legs"].split()
            print(f"\n  +-- {t['book']}  (slip {t['slip']}) "
                  + "-" * max(2, 34 - len(t['book'])))
            for match, pick in zip(matches, picks):
                word = "YES" if pick == "Y" else "NO "
                print(f"  |   BTTS {word}   {match}")
            print(f"  |   combined odds {t['odds']:.3f}   "
                  f"STAKE {t['stake']:,.0f}")
            print("  +" + "-" * 44)
        if not hint:
            return
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


class LadderBlocked(RuntimeError):
    """A gate refused this round: unfunded, past the stop-loss, or no recovery.

    Separate from SystemExit so the interactive loop can report the block, wait
    for the next match week and carry on, instead of the process dying with a
    deficit still carried.
    """


def parse_odds(values: list[str]) -> list[tuple[float, float]]:
    if len(values) != 3:
        raise ValueError("Need exactly three yes,no odds pairs - one per match.")
    out = []
    for value in values:
        try:
            yes, no = (float(x) for x in value.split(","))
        except ValueError:
            raise ValueError(f"Bad odds pair {value!r}; expected e.g. 1.69,2.17")
        if yes <= 1.0 or no <= 1.0:
            raise ValueError(f"Odds must be above 1.0; got {value!r}")
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
        raise LadderBlocked(
            f"At these odds the cheapest winning slip returns {worst:.4f} per unit "
            "of round stake, so a winning round still loses money. No stake "
            "recovers this; sit the round out."
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
        "rotate": args.rotate,
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
    print(f"\n  Next: python {Path(__file__).name} run")
    if args.feed != "shared":
        print(f"  Feed groups {args.feed}: slips sharing a group settle on one "
              "match week.")
        print("  Confirm the match-week number matches across operators before "
              "trusting that split.")
    return 0


def plan_round(state: dict, odds: list[tuple[float, float]]) -> dict:
    """Size the next stage and check every gate. Does not place anything.

    Gates are checked here rather than after placing so a round that cannot be
    settled is never put on in the first place.
    """
    if state["pending"]:
        raise LadderBlocked("A round is already placed and unsettled; settle it first.")

    stage = state["stage"] + 1
    if stage > state["max_stages"]:
        raise LadderBlocked(
            f"Ladder exhausted at stage {state['max_stages']}. The cycle has lost "
            f"{state['cycle_staked'] - state['cycle_returned']:,.0f}. "
            "Reset to start a new cycle, deliberately."
        )

    per_slip, worst = stage_stake(state, odds)
    per_round = 3.0 * per_slip

    if per_round > state["bankroll"]:
        raise LadderBlocked(
            f"Stage {stage} needs {per_round:,.0f} but the bankroll is "
            f"{state['bankroll']:,.0f}. The ladder is unfunded from here; "
            "placing it cannot recover the cycle."
        )
    drawdown = state["opening_bankroll"] - state["bankroll"] + per_round
    if drawdown > state["stop_loss"]:
        raise LadderBlocked(
            f"Stage {stage} would put session drawdown at {drawdown:,.0f}, past the "
            f"{state['stop_loss']:,.0f} stop-loss. Stopping."
        )

    # People are assigned to slips in a fixed order, rotated by cycle when
    # `rotate` is on so each person spends an equal share of rounds on slip A.
    people = list(state["books"])
    if state.get("rotate"):
        shift = (state["cycle"] - 1) % len(people)
        people = people[shift:] + people[:shift]
    tickets = [
        {
            "book": person,
            "slip": key,
            "legs": " ".join("Y" if yes else "N" for yes in slip),
            "odds": slip_odds(slip, odds),
            "stake": per_slip,
        }
        for person, (key, slip) in zip(people, SLIPS.items())
    ]
    return {
        "stage": stage,
        "per_slip": per_slip,
        "per_round": per_round,
        "worst": worst,
        "odds": odds,
        "tickets": tickets,
    }


def commit_round(state: dict, plan: dict, adapter: str = "manual",
                 hint: bool = True) -> None:
    """Print the sized round, hand it to the adapter, and record it as pending."""
    committed = state["cycle_staked"] + plan["per_round"]
    print(f"=== cycle {state['cycle']}, stage {plan['stage']} ===")
    print(f"  deficit carried   {state['cycle_staked'] - state['cycle_returned']:,.0f}")
    print(f"  stake per slip    {plan['per_slip']:,.0f}   "
          f"round total {plan['per_round']:,.0f}")
    print(f"  worst winning slip returns {plan['worst']:.4f}x the round stake -> "
          f"net {plan['worst'] * plan['per_round'] - committed:,.0f} if this stage "
          "closes the cycle")
    print(f"  bankroll after placing     "
          f"{state['bankroll'] - plan['per_round']:,.0f}")

    ADAPTERS[adapter]().place(plan["tickets"], state.get("feed", "shared"), hint)

    state["pending"] = {
        "stage": plan["stage"],
        "per_slip": plan["per_slip"],
        "odds": [list(pair) for pair in plan["odds"]],
        "tickets": plan["tickets"],
        "placed_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    state["stage"] = plan["stage"]
    state["cycle_staked"] += plan["per_round"]
    state["bankroll"] -= plan["per_round"]
    save_state(state)


def settle_round(state: dict, results: dict[str, tuple[bool, ...]]) -> dict:
    """Settle the pending round, write the ledger, advance or reset the ladder."""
    pending = state["pending"]
    if not pending:
        raise LadderBlocked("Nothing pending to settle.")

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

    target = state["target"] * 3.0 * state["base"]
    if net >= target:
        outcome = "closed"
    elif pending["stage"] >= state["max_stages"]:
        outcome = "busted"
    else:
        outcome = "carried"

    if outcome in ("closed", "busted"):
        state["cycle"] += 1
        state["stage"] = 0
        state["cycle_staked"] = 0.0
        state["cycle_returned"] = 0.0
    state["pending"] = None
    save_state(state)
    return {"rows": rows, "net": net, "outcome": outcome, "stage": pending["stage"]}


def report_settlement(state: dict, result: dict) -> None:
    for row in result["rows"]:
        mark = "WON " if row["won"] else "lost"
        print(f"  {row['book']} slip {row['slip']} {row['legs']} vs "
              f"{row['result']}  {mark} {float(row['returned']):,.0f}")
    print(f"  cycle net {result['net']:+,.0f}   bankroll {state['bankroll']:,.0f}")
    if result["outcome"] == "closed":
        print(f"  cycle closed in profit after {result['stage']} stage(s). "
              "Ladder resets.")
    elif result["outcome"] == "busted":
        print(f"  LADDER BUSTED at stage {result['stage']}: {result['net']:+,.0f}.")
    else:
        print(f"  deficit {-result['net']:,.0f} carried to stage "
              f"{result['stage'] + 1}.")


def cmd_next(args: argparse.Namespace) -> int:
    state = load_state()
    try:
        plan = plan_round(state, parse_odds(args.odds))
    except (LadderBlocked, ValueError) as error:
        raise SystemExit(str(error))
    commit_round(state, plan, args.adapter)
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
            raise ValueError(f"Bad result {value!r}; expected three Y/N, e.g. YNY")
        return tuple(c == "Y" for c in value)

    if "/" in text:
        # One triple per feed group, in group order: "YYY/YNY" means the
        # first operator's draw landed YYY and the second's landed YNY.
        groups = M.parse_feed(feed or "shared", len(SLIPS))
        drawn = [triple(part) for part in text.split("/")]
        if len(drawn) != len(set(groups)):
            raise ValueError(
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
        raise ValueError(f"No result given for slip(s) {sorted(missing)}")
    return out


def cmd_settle(args: argparse.Namespace) -> int:
    state = load_state()
    try:
        results = parse_results(args.results, state.get("feed", "shared"))
        result = settle_round(state, results)
    except (LadderBlocked, ValueError) as error:
        raise SystemExit(str(error))
    print(f"=== settled cycle {state['cycle'] if result['outcome'] == 'carried' else state['cycle'] - 1}"
          f" stage {result['stage']} ===")
    report_settlement(state, result)
    return 0


# ------------------------------------------------------------- interactive run


def ask(prompt: str, default: str = "") -> str:
    """One line of input, with Ctrl-C and end-of-input treated as 'stop'."""
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"{prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit("Stopped. State is saved; `run` again to pick up where you left off.")
    return value or default


def ask_odds(default: list[str]) -> list[str] | None:
    """Three yes,no pairs for this match week, or None to sit the round out.

    Odds are asked every round because Kiron re-prices every match week, and a
    stage sized off the previous round's prices does not recover. Enter alone
    reuses the last set, which is the common case when a price has not moved.
    """
    print("  odds for this match week  (Enter reuses, 's' skip, 'q' quit, '?' help)")
    while True:
        values = []
        for index in range(3):
            answer = ask(f"    match {index + 1} yes,no", default[index])
            lowered = answer.lower()
            if lowered in ("q", "quit", "exit"):
                return None
            if lowered in ("s", "skip"):
                return []
            if lowered in ("?", "h", "help"):
                print("      Type the two BTTS prices separated by a comma, e.g."
                      " 1.69,2.17")
                print("      Enter alone keeps the value shown in brackets.")
                break
            values.append(answer)
        if len(values) != 3:
            continue
        try:
            parse_odds(values)
        except ValueError as error:
            print(f"      {error}")
            continue
        return values


def cmd_run(args: argparse.Namespace) -> int:
    """Interactive loop: odds in, stakes out, results in, ladder advances.

    This is the mode the two-minute match week actually allows. Typing flags per
    round costs more time than the round gives you, and it is where stages get
    mis-sized by reusing an old command out of the shell history.
    """
    state = load_state()
    last = ["1.69,2.17", "1.84,1.97", "1.69,2.17"]
    if state.get("last_odds"):
        last = [f"{pair[0]:g},{pair[1]:g}" for pair in state["last_odds"]]

    print(f"SokaLigi ladder - {', '.join(state['books'])}, feed {state.get('feed')}")
    print(f"base {state['base']:,.0f} per slip, max {state['max_stages']} stages, "
          f"stop-loss {state['stop_loss']:,.0f}")
    print("Ctrl-C or 'q' at any prompt stops; state is saved after every round.\n")

    while True:
        deficit = state["cycle_staked"] - state["cycle_returned"]
        print("-" * 64)
        print(f"cycle {state['cycle']}  stage {state['stage'] + 1}/"
              f"{state['max_stages']}  bankroll {state['bankroll']:,.0f}"
              + (f"  deficit {deficit:,.0f}" if deficit else ""))

        if state["pending"]:
            print("  a placed round is still unsettled")
        else:
            answer = ask_odds(last)
            if answer is None:
                print("Stopped.")
                return 0
            if not answer:
                print("  round skipped; ladder unchanged")
                continue
            last = answer
            try:
                plan = plan_round(state, parse_odds(answer))
            except LadderBlocked as error:
                print(f"\n  BLOCKED: {error}")
                if ask("  reset the cycle and carry on? (y/N)", "n").lower() != "y":
                    return 1
                cmd_reset(args)
                state = load_state()
                continue
            state["last_odds"] = [list(pair) for pair in plan["odds"]]
            commit_round(state, plan, args.adapter, hint=False)

        while True:
            answer = ask("\n  results for this match week (e.g. YNY, or 'q')")
            if answer.lower() in ("q", "quit", "exit"):
                print("Stopped with a round still pending; "
                      "settle it next time you run.")
                return 0
            try:
                results = parse_results(answer, state.get("feed", "shared"))
            except ValueError as error:
                print(f"      {error}")
                continue
            break

        result = settle_round(state, results)
        report_settlement(state, result)
        if result["outcome"] == "busted" and args.stop_on_bust:
            print("\n  --stop-on-bust set; stopping here.")
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

    # Per-person tally, so three people can see what each account has placed
    # and returned - the number to settle up on if the bankroll is not pooled.
    by_person: dict[str, list[float]] = {}
    for row in rows:
        s, b, w = by_person.setdefault(row["book"], [0.0, 0.0, 0])
        by_person[row["book"]] = [s + float(row["stake"]),
                                  b + float(row["returned"]), w + int(row["won"])]
    if len(by_person) > 1:
        print("\n=== per person ===")
        name_w = max(len(name) for name in by_person)
        for name, (s, b, w) in by_person.items():
            tickets = sum(1 for r in rows if r["book"] == name)
            print(f"  {name:>{name_w}s}  staked {s:>9,.0f}  returned {b:>9,.0f}  "
                  f"net {b - s:>+9,.0f}  ({w}/{tickets} won)")
        if state.get("rotate"):
            print("  (slips rotate each cycle, so these even out over time)")
        else:
            print("  (fixed slips; slip A sits on one person - pass --rotate to share)")
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
    i.add_argument("--rotate", action="store_true",
                   help="rotate who holds slip A/B/C each cycle, for fair sharing")

    n = sub.add_parser("next", help="size and place the next stage")
    n.add_argument("--odds", nargs=3, required=True,
                   metavar="YES,NO", help="live BTTS odds for the three matches")
    n.add_argument("--adapter", choices=sorted(ADAPTERS), default="manual")

    s = sub.add_parser("settle", help="record the match week's results")
    s.add_argument("--results", required=True,
                   help="YNY, or YYY/YNY per feed group, or A:YYY,B:YYY,C:YNY")

    r = sub.add_parser("run", help="interactive loop: odds in, stakes out")
    r.add_argument("--adapter", choices=sorted(ADAPTERS), default="manual")
    r.add_argument("--stop-on-bust", action="store_true",
                   help="stop after a cycle busts instead of starting the next")

    sub.add_parser("status", help="state plus realised-vs-model ledger")
    sub.add_parser("reset", help="abandon the current cycle")

    args = parser.parse_args()
    return {
        "init": cmd_init, "next": cmd_next, "settle": cmd_settle,
        "run": cmd_run,
        "status": cmd_status, "reset": cmd_reset,
    }[args.mode](args)


if __name__ == "__main__":
    raise SystemExit(main())
