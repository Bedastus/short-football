"""Price the SokaLigi (Kiron virtual) BTTS treble ladder and size its martingale.

Why this exists
---------------
The three bet slips in the SokaLigi screenshots are not three independent
guesses. They are three *overlapping* trebles on the same three BTTS markets:

    slip A   Leeds YES   Spurs YES   N.Forest YES
    slip B   Leeds NO    Spurs YES   N.Forest YES
    slip C   Leeds YES   Spurs YES   N.Forest NO

Every slip carries "Spurs YES". If Spurs fails to produce both-teams-to-score,
all three lose together, and the martingale advances a stage no matter how the
other two matches land. That single shared leg, not bad luck, is the dominant
failure mode of the structure, and no stake plan can hedge a leg that every
slip shares.

The other thing the eye misses: A, B and C are mutually exclusive. A needs
Leeds YES, B needs Leeds NO; A needs N.Forest YES, C needs N.Forest NO; B needs
Leeds NO while C needs Leeds YES. At most one slip can ever win. The round is a
single 41.8% shot wearing three tickets, not three 16% shots.

What is computed here
---------------------
Everything is exact enumeration, not simulation. Three binary matches give
eight joint outcomes; a six-stage ladder over four distinct round results gives
at most 4**6 paths. Both fit in memory, so the cycle distribution, the ruin
probability and the expected value are arithmetic rather than sampling.

    python sokaligi_math.py price
        Strip the margin out of each two-way BTTS market, price each slip, and
        show the round's expected value.

    python sokaligi_math.py ladder --stages 6 --base 300
        Solve for the smallest stage multiplier that still recovers the whole
        ladder on the *worst* winning slip, and print the stake table with the
        bankroll each stage demands.

    python sokaligi_math.py cycle --stages 6 --base 300
        Exact distribution of one martingale cycle: profit when it closes,
        loss when it busts, and how often each happens.

    python sokaligi_math.py ruin --bankroll 9785
        Risk of ruin and expected burn rate over a session of two-minute
        match weeks.

    python sokaligi_math.py breakeven
        What the book's margin would have to be for any of this to be neutral.

Modelling choices, stated so they can be argued with
----------------------------------------------------
* True probabilities are recovered from the book's own prices. That is the most
  generous assumption available: it credits the operator with pricing its own
  random number generator honestly and charging exactly the quoted overround.
  If the RNG is shaded relative to the price, every figure here is optimistic.
* `--feed shared` assumes all three bookmakers settle against the same Kiron
  match week (the screenshots show a global "Match Week #35624537", which is
  what a shared feed looks like). `--feed independent` assumes each operator
  draws its own result. The two give identical expected value - correlation
  never moves a mean - but materially different ruin, so both are offered.
* Legs within a match week are treated as independent across matches. Kiron
  draws fixtures independently; nothing in the published rules couples them.
"""

from __future__ import annotations

import argparse
import itertools
import math
from pathlib import Path

# The three two-way BTTS markets, read off the screenshots. Identical in all
# three images, so the prices are stable across the round.
MARKETS = {
    "Leeds/London Reds": (1.69, 2.17),
    "Spurs/Leicester": (1.84, 1.97),
    "N.Forest/London Blues": (1.69, 2.17),
}

# Slip -> the side taken in each market, in MARKETS order. YES is True.
SLIPS = {
    "A": (True, True, True),
    "B": (False, True, True),
    "C": (True, True, False),
}

SECONDS_PER_ROUND = 120  # match weeks start every two minutes in the screenshots


# ---------------------------------------------------------------- de-vigging


def devig_proportional(odds: tuple[float, float]) -> tuple[float, float, float]:
    """Split the overround across both legs in proportion to their prices.

    Returns (p_yes, p_no, booksum). The booksum is 1 + margin: a 1.0525 book
    hands back 1/1.0525 = 95.0 cents of every shilling staked, before any
    combination multiplies that loss.
    """
    implied = [1.0 / o for o in odds]
    booksum = sum(implied)
    return implied[0] / booksum, implied[1] / booksum, booksum


def devig_shin(odds: tuple[float, float], tol: float = 1e-12) -> tuple[float, float, float]:
    """Shin de-vig: attribute the margin to insider trading rather than pro rata.

    Shin's model loads more of the margin onto the longshot, so it is the
    standard robustness check on a proportional split. For a two-way book the
    difference is small, which is the point of running it.
    """
    implied = [1.0 / o for o in odds]
    booksum = sum(implied)

    def probs(z: float) -> list[float]:
        return [
            (math.sqrt(z * z + 4.0 * (1.0 - z) * pi * pi / booksum) - z)
            / (2.0 * (1.0 - z))
            for pi in implied
        ]

    low, high = 0.0, 0.99
    for _ in range(200):
        mid = 0.5 * (low + high)
        if sum(probs(mid)) > 1.0:
            low = mid
        else:
            high = mid
        if high - low < tol:
            break
    p = probs(0.5 * (low + high))
    total = sum(p)
    return p[0] / total, p[1] / total, booksum


DEVIGS = {"proportional": devig_proportional, "shin": devig_shin}


# ------------------------------------------------------------------ pricing


def leg_probabilities(method: str) -> dict[str, tuple[float, float, float]]:
    devig = DEVIGS[method]
    return {name: devig(odds) for name, odds in MARKETS.items()}


def slip_price(slip: tuple[bool, ...], probs: dict[str, tuple[float, float, float]]) -> tuple[float, float]:
    """(decimal odds, true probability) for one treble."""
    odds, probability = 1.0, 1.0
    for (name, market), yes in zip(MARKETS.items(), slip):
        odds *= market[0] if yes else market[1]
        p_yes, p_no, _ = probs[name]
        probability *= p_yes if yes else p_no
    return odds, probability


# -------------------------------------------------- one round, exactly priced


def round_outcomes(method: str, feed: str) -> list[tuple[float, float]]:
    """(probability, gross return per 1 unit of *total round stake*) per outcome.

    One unit of round stake means the three slips together, so each slip
    carries one third of it. A return above 1.0 is a winning round.
    """
    probs = leg_probabilities(method)
    priced = {name: slip_price(slip, probs) for name, slip in SLIPS.items()}

    if feed == "shared":
        # One Kiron draw settles all three books. Enumerate the eight ways the
        # three matches can land and see which slip, if any, survives.
        dist: list[tuple[float, float]] = []
        for draw in itertools.product([True, False], repeat=len(MARKETS)):
            probability = 1.0
            for (name, _), yes in zip(MARKETS.items(), draw):
                p_yes, p_no, _ = probs[name]
                probability *= p_yes if yes else p_no
            gross = sum(
                priced[key][0] / 3.0 for key, slip in SLIPS.items() if slip == draw
            )
            dist.append((probability, gross))
        return dist

    # Each operator draws its own match week, so the slips win or lose
    # independently and more than one can land.
    keys = list(SLIPS)
    dist = []
    for pattern in itertools.product([True, False], repeat=len(keys)):
        probability, gross = 1.0, 0.0
        for key, won in zip(keys, pattern):
            odds, p = priced[key]
            probability *= p if won else 1.0 - p
            if won:
                gross += odds / 3.0
        dist.append((probability, gross))
    return dist


def round_summary(method: str, feed: str) -> dict[str, float]:
    dist = round_outcomes(method, feed)
    expected = sum(p * g for p, g in dist)
    win = sum(p for p, g in dist if g > 1.0)
    worst_win = min((g for p, g in dist if g > 1.0), default=0.0)
    return {
        "ev_per_unit": expected,
        "edge": expected - 1.0,
        "p_round_win": win,
        "p_round_loss": 1.0 - win,
        "worst_win_return": worst_win,
    }


# ------------------------------------------------------------- ladder sizing


def min_multiplier(worst_win: float, stages: int, target: float) -> float:
    """Smallest geometric multiplier whose every stage still clears the ladder.

    `worst_win` is the gross return per unit round stake on the *cheapest*
    winning slip - the stage has to survive that one, not the average one.
    `target` is the profit demanded on close, as a multiple of the base round
    stake. Sizing off the average win is the classic way a martingale quietly
    stops recovering.
    """
    gain = worst_win - 1.0
    if gain <= 0.0:
        return math.inf

    def shortfall(m: float) -> float:
        worst = math.inf
        for k in range(1, stages + 1):
            stake = m ** (k - 1)
            spent = (stake - 1.0) / (m - 1.0) if m != 1.0 else float(k - 1)
            worst = min(worst, gain * stake - spent - target)
        return worst

    low, high = 1.0 + 1e-9, 50.0
    if shortfall(high) < 0.0:
        return math.inf
    for _ in range(300):
        mid = 0.5 * (low + high)
        if shortfall(mid) < 0.0:
            low = mid
        else:
            high = mid
    return high


def ladder(base: float, stages: int, multiplier: float, step: float) -> list[dict]:
    """Stake table. Stakes round *up* to `step`: rounding down breaks recovery."""
    rows, cumulative = [], 0.0
    for k in range(1, stages + 1):
        raw = base * multiplier ** (k - 1)
        per_slip = math.ceil(raw / step) * step if step > 0 else raw
        per_round = 3.0 * per_slip
        cumulative += per_round
        rows.append(
            {
                "stage": k,
                "per_slip": per_slip,
                "per_round": per_round,
                "cumulative": cumulative,
            }
        )
    return rows


# ---------------------------------------------- one cycle, exactly enumerated


def cycle_distribution(
    dist: list[tuple[float, float]], stakes: list[float], target: float
) -> list[tuple[float, float, int, bool]]:
    """(probability, net profit, stages used, busted) over every ladder path.

    The ladder advances while the cycle is still behind its target and resets
    the moment it is clear, which is the only definition of "martingale" that
    survives rounds with partial returns.
    """
    out: list[tuple[float, float, int, bool]] = []

    def walk(k: int, staked: float, returned: float, probability: float) -> None:
        if probability == 0.0:
            return
        if k == len(stakes):
            out.append((probability, returned - staked, k, True))
            return
        stake = stakes[k]
        for p, gross in dist:
            spent = staked + stake
            back = returned + gross * stake
            if back - spent >= target:
                out.append((probability * p, back - spent, k + 1, False))
            else:
                walk(k + 1, spent, back, probability * p)

    walk(0, 0.0, 0.0, 1.0)
    return out


def cycle_summary(dist, stakes, target) -> dict[str, float]:
    paths = cycle_distribution(dist, stakes, target)
    p_bust = sum(p for p, _, _, busted in paths if busted)
    ev = sum(p * net for p, net, _, _ in paths)
    bust_loss = (
        sum(p * net for p, net, _, busted in paths if busted) / p_bust if p_bust else 0.0
    )
    win_profit = (
        sum(p * net for p, net, _, busted in paths if not busted) / (1.0 - p_bust)
        if p_bust < 1.0
        else 0.0
    )
    rounds = sum(p * used for p, _, used, _ in paths)
    return {
        "p_bust": p_bust,
        "ev_per_cycle": ev,
        "mean_bust_loss": bust_loss,
        "mean_close_profit": win_profit,
        "mean_rounds": rounds,
        "cycles_to_bust": 1.0 / p_bust if p_bust else math.inf,
    }


# ----------------------------------------------------------------- reporting


def money(value: float) -> str:
    return f"{value:,.0f}"


def cmd_price(args: argparse.Namespace) -> int:
    probs = leg_probabilities(args.devig)
    print(f"=== BTTS legs, {args.devig} de-vig ===")
    print(f"  {'match':24s} {'yes':>6s} {'no':>6s} {'book':>7s} {'margin':>7s} "
          f"{'p(yes)':>7s} {'p(no)':>7s}")
    for name, odds in MARKETS.items():
        p_yes, p_no, booksum = probs[name]
        print(f"  {name:24s} {odds[0]:6.2f} {odds[1]:6.2f} {booksum:7.4f} "
              f"{booksum - 1.0:6.2%} {p_yes:7.4f} {p_no:7.4f}")

    print("\n=== slips ===")
    print(f"  {'slip':5s} {'legs':22s} {'odds':>8s} {'p(win)':>8s} {'EV/unit':>9s} "
          f"{'Kelly f*':>9s}")
    for key, slip in SLIPS.items():
        odds, p = slip_price(slip, probs)
        legs = " ".join("Y" if yes else "N" for yes in slip)
        kelly = (p * odds - 1.0) / (odds - 1.0)
        print(f"  {key:5s} {legs:22s} {odds:8.3f} {p:8.4f} {p * odds:9.4f} "
              f"{kelly:9.4f}")
    print("  Kelly is negative on all three, so the growth-optimal stake is zero.\n"
          "  A fraction of a negative Kelly is still negative: there is no stake\n"
          "  size, and no stake plan, that makes a negative edge compound upward.")

    print("\n  A treble's expected value is the product of its legs' book "
          "returns:\n  the margin does not average out, it compounds.")
    product = 1.0
    for name in MARKETS:
        product *= 1.0 / probs[name][2]
    print(f"  per-leg returns {' x '.join(f'{1 / probs[n][2]:.4f}' for n in MARKETS)}"
          f" = {product:.4f}  ->  {product - 1:+.2%} per shilling on any treble")

    for feed in ("shared", "independent"):
        s = round_summary(args.devig, feed)
        print(f"\n=== round of 3 slips, {feed} feed ===")
        print(f"  P(at least one slip wins) {s['p_round_win']:.4f}")
        print(f"  P(round loses outright)   {s['p_round_loss']:.4f}")
        print(f"  gross return per unit     {s['ev_per_unit']:.4f}  "
              f"({s['edge']:+.2%})")
        print(f"  worst winning return      {s['worst_win_return']:.4f} "
              "per unit of round stake")
        if feed == "shared":
            spurs = probs["Spurs/Leicester"][1]
            print(f"  P(Spurs BTTS = No) = {spurs:.4f}  -> all three slips dead "
                  f"on that leg alone,\n  which is "
                  f"{spurs / s['p_round_loss']:.1%} of every losing round.")
    return 0


def cmd_ladder(args: argparse.Namespace) -> int:
    s = round_summary(args.devig, args.feed)
    worst = s["worst_win_return"]
    m = min_multiplier(worst, args.stages, args.target)
    m_inf = 1.0 + 1.0 / (worst - 1.0)
    print(f"=== ladder sizing, {args.feed} feed ===")
    print(f"  worst winning round returns {worst:.4f} per unit staked, "
          f"so a win nets {worst - 1:.4f}")
    print(f"  minimum multiplier for {args.stages} stages : {m:.4f}")
    print(f"  minimum multiplier for any horizon  : {m_inf:.4f}")
    print("  (a plain 2x double never recovers here: a treble ladder needs the\n"
          "   multiplier the *cheapest* winning slip can pay back, not 2.)")

    use = args.multiplier or math.ceil(m * 100) / 100
    print(f"\n=== stake table, base {money(args.base)} per slip, "
          f"multiplier {use:.2f}, rounded up to {money(args.step)} ===")
    rows = ladder(args.base, args.stages, use, args.step)
    print(f"  {'stage':>5s} {'per slip':>11s} {'per round':>11s} "
          f"{'cumulative':>12s} {'worst payout':>13s} {'worst net':>11s}")
    for row in rows:
        payout = worst * row["per_round"]
        print(f"  {row['stage']:5d} {money(row['per_slip']):>11s} "
              f"{money(row['per_round']):>11s} {money(row['cumulative']):>12s} "
              f"{money(payout):>13s} "
              f"{money(payout - row['cumulative']):>11s}")
    need = rows[-1]["cumulative"]
    print(f"\n  bankroll to run all {args.stages} stages: {money(need)}")
    if args.bankroll:
        fundable = [r for r in rows if r["cumulative"] <= args.bankroll]
        k = len(fundable)
        print(f"  bankroll on hand: {money(args.bankroll)} -> funds "
              f"{k} of {args.stages} stages "
              f"({args.bankroll / need:.1%} of what the plan needs)")
        if k < args.stages:
            q = s["p_round_loss"]
            print(f"  the ladder therefore busts at stage {k + 1}, which happens "
                  f"with probability {q ** k:.4f}\n  ({1 / q ** k:.1f} cycles "
                  f"between busts), not the {s['p_round_loss'] ** args.stages:.4f} "
                  "the 6-stage plan assumes")
    return 0


def cmd_cycle(args: argparse.Namespace) -> int:
    s = round_summary(args.devig, args.feed)
    worst = s["worst_win_return"]
    m = args.multiplier or math.ceil(min_multiplier(worst, args.stages, args.target) * 100) / 100
    rows = ladder(args.base, args.stages, m, args.step)
    stakes = [r["per_round"] for r in rows]
    dist = round_outcomes(args.devig, args.feed)
    target = args.target * 3.0 * args.base
    c = cycle_summary(dist, stakes, target)

    print(f"=== one martingale cycle, {args.stages} stages, {args.feed} feed, "
          f"multiplier {m:.2f} ===")
    print(f"  P(cycle closes in profit) {1 - c['p_bust']:.4f}")
    print(f"  P(cycle busts)            {c['p_bust']:.4f}  "
          f"= 1 in {c['cycles_to_bust']:.1f} cycles")
    print(f"  mean profit when it closes {money(c['mean_close_profit'])}")
    print(f"  mean loss when it busts    {money(c['mean_bust_loss'])}")
    print(f"  mean rounds per cycle      {c['mean_rounds']:.3f}")
    print(f"  expected value per cycle   {money(c['ev_per_cycle'])}")
    print("\n  The ladder moves money between the 96% of cycles that close and\n"
          "  the 4% that do not. It cannot move the mean, which is fixed by the\n"
          "  margin: a stake plan multiplies turnover, and the edge is charged\n"
          "  on turnover.")

    turnover = c["ev_per_cycle"] / s["edge"]
    print(f"\n  expected turnover per cycle {money(turnover)} "
          f"x edge {s['edge']:+.2%} = {money(c['ev_per_cycle'])}  (identity check)")
    per_hour = 3600.0 / SECONDS_PER_ROUND / c["mean_rounds"]
    print(f"  at {SECONDS_PER_ROUND}s match weeks that is {per_hour:.1f} cycles/hour "
          f"-> {money(per_hour * c['ev_per_cycle'])} per hour expected")
    return 0


def cmd_ruin(args: argparse.Namespace) -> int:
    s = round_summary(args.devig, args.feed)
    worst = s["worst_win_return"]
    m = args.multiplier or math.ceil(min_multiplier(worst, args.stages, args.target) * 100) / 100
    rows = ladder(args.base, args.stages, m, args.step)
    dist = round_outcomes(args.devig, args.feed)
    target = args.target * 3.0 * args.base

    print(f"=== survival on a {money(args.bankroll)} bankroll, {args.feed} feed ===")
    print(f"  {'stages funded':>13s} {'needs':>12s} {'P(bust/cycle)':>14s} "
          f"{'bust loss':>12s} {'EV/cycle':>11s}")
    affordable = 0
    for k in range(1, args.stages + 1):
        stakes = [r["per_round"] for r in rows[:k]]
        c = cycle_summary(dist, stakes, target)
        need = rows[k - 1]["cumulative"]
        if need <= args.bankroll:
            affordable = k
        flag = "" if need <= args.bankroll else "  <- unfunded"
        print(f"  {k:13d} {money(need):>12s} {c['p_bust']:14.4f} "
              f"{money(c['mean_bust_loss']):>12s} "
              f"{money(c['ev_per_cycle']):>11s}{flag}")

    if affordable == 0:
        print("\n  The bankroll cannot fund even stage 1 of this plan.")
        return 0

    stakes = [r["per_round"] for r in rows[:affordable]]
    c = cycle_summary(dist, stakes, target)
    print(f"\n  Real ladder on this bankroll: {affordable} stages, not {args.stages}.")
    print(f"  P(bust) {c['p_bust']:.4f} per cycle -> median "
          f"{math.log(0.5) / math.log(1 - c['p_bust']):.1f} cycles before the "
          "bankroll is gone")
    per_hour = 3600.0 / SECONDS_PER_ROUND / c["mean_rounds"]
    print(f"  {per_hour:.1f} cycles/hour -> median "
          f"{math.log(0.5) / math.log(1 - c['p_bust']) / per_hour * 60:.0f} minutes "
          "of play before ruin")
    print(f"  expected loss {money(-c['ev_per_cycle'] * per_hour)} per hour "
          f"against a {money(args.bankroll)} bankroll")
    return 0


def cmd_breakeven(args: argparse.Namespace) -> int:
    probs = leg_probabilities(args.devig)
    print("=== what would have to be true ===")
    print("  A treble returns p1*p2*p3 * o1*o2*o3. With the book's own prices")
    print("  that is exactly 1/(B1*B2*B3), where Bi is each market's book sum.")
    print("  It equals 1.000 only when every Bi equals 1.000 - a zero-margin book.\n")
    print(f"  {'match':24s} {'book':>8s} {'margin':>8s} "
          f"{'margin to break even':>21s}")
    for name in MARKETS:
        booksum = probs[name][2]
        print(f"  {name:24s} {booksum:8.4f} {booksum - 1:8.2%} {0.0:20.2%}")

    for n in (1, 2, 3, 4, 5):
        product = 1.0
        for name in list(MARKETS)[: min(n, 3)]:
            product *= 1.0 / probs[name][2]
        if n > 3:
            product = (1.0 / probs["Leeds/London Reds"][2]) ** n
        print(f"  {n}-fold at this margin returns {product:.4f} "
              f"({product - 1:+.2%})")

    s = round_summary(args.devig, "shared")
    probs_spurs = probs["Spurs/Leicester"][0]
    needed = probs_spurs / s["ev_per_unit"]
    print(f"\n  To drag the round to break-even on the shared leg alone, Spurs")
    print(f"  BTTS-YES would have to be a {needed:.4f} chance instead of "
          f"{probs_spurs:.4f}")
    print(f"  - a {needed - probs_spurs:+.4f} absolute error in the operator's")
    print("  pricing of its own random number generator, every single round.")
    print("\n  Singles are the cheapest way to lose: one leg costs "
          f"{1 - 1 / probs['Spurs/Leicester'][2]:.2%}, three cost "
          f"{-s['edge']:.2%}.")
    return 0


def cmd_promo(args: argparse.Namespace) -> int:
    """A bonus is the only thing on this screen that can carry a positive edge.

    Clearing a bonus of value B at rollover R costs R*B*m in expected loss,
    where m is the margin per unit of turnover. So the bonus is worth taking
    exactly when R*m < 1, i.e. R < 1/m. That threshold is the whole decision,
    and it depends sharply on what the rollover is allowed to be cleared with.
    """
    probs = leg_probabilities(args.devig)
    singles = 1.0 - 1.0 / max(probs[n][2] for n in MARKETS)
    treble = -round_summary(args.devig, "shared")["edge"]

    print("=== promotions: break-even rollover ===")
    print("  Expected cost of clearing = rollover x bonus x margin.")
    print("  Worth taking iff rollover < 1 / margin.\n")
    print(f"  {'cleared with':20s} {'margin':>8s} {'max rollover':>13s}")
    for label, margin in (
        ("singles", singles),
        ("doubles", 1.0 - (1.0 - singles) ** 2),
        ("trebles (this plan)", treble),
    ):
        print(f"  {label:20s} {margin:8.2%} {1.0 / margin:12.1f}x")

    if args.bonus and args.rollover:
        margin = {"single": singles, "treble": treble}[args.leg_type]
        cost = args.rollover * args.bonus * margin
        print(f"\n  bonus {money(args.bonus)} at {args.rollover:g}x rollover, "
              f"cleared on {args.leg_type}s:")
        print(f"    turnover required {money(args.rollover * args.bonus)}")
        print(f"    expected cost     {money(cost)}  (margin {margin:.2%})")
        print(f"    expected value    {money(args.bonus - cost)}  "
              f"-> {'TAKE IT' if cost < args.bonus else 'not worth clearing'}")
        print(f"    break-even rollover {1.0 / margin:.1f}x")
    else:
        print("\n  Pass --bonus and --rollover to price a specific offer.")
    print("\n  Note the asymmetry: clearing on singles tolerates a rollover "
          f"{1.0 / singles / (1.0 / treble):.1f}x\n  higher than clearing on "
          "trebles. If a bonus must be taken, take it in singles.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--devig", choices=sorted(DEVIGS), default="proportional")
    sub = parser.add_subparsers(dest="mode", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--feed", choices=("shared", "independent"), default="shared")
        p.add_argument("--stages", type=int, default=6)
        p.add_argument("--base", type=float, default=300.0)
        p.add_argument("--multiplier", type=float, help="override the solved one")
        p.add_argument("--step", type=float, default=100.0, help="stake rounding")
        p.add_argument("--target", type=float, default=0.0,
                       help="profit on close, in base round stakes")

    sub.add_parser("price", help="de-vig the legs and price the three slips")

    ladder_p = sub.add_parser("ladder", help="solve and print the stake table")
    common(ladder_p)
    ladder_p.add_argument("--bankroll", type=float, default=9784.75)

    cycle_p = sub.add_parser("cycle", help="exact one-cycle distribution")
    common(cycle_p)

    ruin_p = sub.add_parser("ruin", help="risk of ruin on a real bankroll")
    common(ruin_p)
    ruin_p.add_argument("--bankroll", type=float, default=9784.75)

    sub.add_parser("breakeven", help="what the margin would have to be")

    promo_p = sub.add_parser("promo", help="break-even rollover on a bonus")
    promo_p.add_argument("--bonus", type=float, default=0.0)
    promo_p.add_argument("--rollover", type=float, default=0.0, help="e.g. 5 for 5x")
    promo_p.add_argument("--leg-type", choices=("single", "treble"), default="single")

    args = parser.parse_args()
    return {
        "price": cmd_price,
        "ladder": cmd_ladder,
        "cycle": cmd_cycle,
        "ruin": cmd_ruin,
        "breakeven": cmd_breakeven,
        "promo": cmd_promo,
    }[args.mode](args)


if __name__ == "__main__":
    raise SystemExit(main())
