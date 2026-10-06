# Weekly Profit Strategy Update — 2026-10-06
### 🎲 Betting · SokaLigi (Kiron virtual) BTTS treble ladder across 3 bookmakers

**Hypothesis** — This makes money *if* three overlapping BTTS trebles cover enough of
the outcome space that a 6-stage martingale at 300/slip recovers every losing run before
the bankroll runs out.

Reproduce every number below with `sokaligi_math.py` (exact enumeration, no simulation).

---

## The Math

**1. The three slips are one bet, not three.**

```
slip A   Leeds YES   Spurs YES   N.Forest YES    @ 5.255
slip B   Leeds NO    Spurs YES   N.Forest YES    @ 6.748
slip C   Leeds YES   Spurs YES   N.Forest NO     @ 6.748
```

A needs Leeds YES, B needs Leeds NO → mutually exclusive. A needs N.Forest YES, C needs
N.Forest NO → mutually exclusive. B needs Leeds NO, C needs Leeds YES → mutually exclusive.
**At most one slip can ever win.** This is a single 41.8% shot wearing three tickets.

Worse, all three carry **Spurs YES**. P(Spurs BTTS = No) = 0.4829, and on that leg alone all
three die together:

```
P(round loses) = 0.5821,  of which Spurs-No alone = 0.4829  →  83.0% of all losing rounds
```

The shared leg is the structure's single point of failure, and no stake plan hedges a leg
every slip shares.

**2. The margin compounds across legs — it does not average out.**

| market | yes | no | book sum | margin | return per shilling |
|---|---|---|---|---|---|
| Leeds / London Reds | 1.69 | 2.17 | 1.0525 | 5.25% | 0.9501 |
| Spurs / Leicester | 1.84 | 1.97 | 1.0511 | 5.11% | 0.9514 |
| N.Forest / London Blues | 1.69 | 2.17 | 1.0525 | 5.25% | 0.9501 |

```
treble return = 0.9501 × 0.9514 × 0.9501 = 0.8588   →   −14.12% per shilling staked
```

Every slip has identical EV of 0.8588 — the hedge changes variance, never the mean. Round EV
is −14.12% whether the three books share one Kiron feed or draw independently (correlation
cannot move a mean).

| fold | return | edge |
|---|---|---|
| single | 0.9501 | −4.99% |
| double | 0.9039 | −9.61% |
| **treble (this plan)** | **0.8588** | **−14.12%** |
| 5-fold | 0.7741 | −22.59% |

**3. Kelly says the optimal stake is zero.**

```
f* = (p·b − 1)/(b − 1)       slip A: −0.0332     slips B, C: −0.0246
```

All negative. A fraction of a negative Kelly is still negative — ¼-Kelly of −3.3% is −0.83%.
No stake size makes a negative edge compound upward.

**4. The martingale multiplier is not 2 — it is 2.33.**

The cheapest winning slip (A @ 5.255) returns only `5.255/3 = 1.7517` per unit of *round*
stake, netting 0.7517. Recovery needs `0.7517·(m−1) ≥ 1`:

```
m ≥ 1 + 1/0.7517 = 2.3302        (2.3100 if you only ever need 6 stages)
```

A 2× double **never recovers** here.

But a fixed multiplier is the wrong tool once stakes are rounded to whole shillings.
Rounding stage 2 up from 232 to 300 inflates the cumulative, and the stage 3 the curve
prescribes no longer covers it — at base 100 the worst-case net goes *negative* from stage 4
on, meaning the ladder stops recovering even when it wins. Each stage is therefore sized
against the deficit actually carried:

```
stake_k = ceil( (cumulative_{k-1} + target) / 0.7517 / 3 )
```

**Stake table — base 100/slip, rounded up to 100 TZS:**

| stage | per slip | per round | cumulative | worst payout | worst net | ×prev |
|---|---|---|---|---|---|---|
| 1 | 100 | 300 | 300 | 526 | +226 | — |
| 2 | 200 | 600 | 900 | 1,051 | +151 | 2.00 |
| 3 | 400 | 1,200 | 2,100 | 2,102 | +2 | 2.00 |
| 4 | 1,000 | 3,000 | 5,100 | 5,255 | +155 | 2.50 |
| 5 | 2,300 | 6,900 | 12,000 | 12,087 | +87 | 2.30 |
| 6 | 5,400 | 16,200 | **28,200** | 28,378 | +178 | 2.35 |

**The 6-stage plan at base 100 needs 28,200 TZS, not 21,000.** (Deficit-driven sizing is
tighter than the geometric curve: at base 300 the true requirement is 66,000, not the 106,200
a fixed 2.34× table gives.)

**5. The plan on a 21,000 bankroll is a 5-stage ladder, not a 6-stage one.**

Feed layout matters here. Two accounts at SokaBet are settled by **one** match week, so slips
A and B stay mutually exclusive. A third account at a different operator draws separately —
unless Gwala carries the same Kiron feed.

| feed layout | P(round loses) | 5-stage bust | median survival |
|---|---|---|---|
| all three one feed | 0.5821 | 6.68% | 10.0 cycles ≈ **45 min** |
| **2 SokaBet + 1 Gwala** | **0.6190** | **9.09%** | **7.3 cycles ≈ 35 min** |
| three separate feeds | 0.6372 | 10.6% | 6.2 cycles ≈ 30 min |

Counter-intuitive but exact: **splitting the third slip onto another operator makes the round
lose *more* often** (61.9% vs 58.2%). Decorrelating removes the common Spurs failure for slip
C, but it also destroys the mutual exclusivity that stopped the three slips wasting coverage
on each other — and the second effect is larger.

**Survival table, your setup (2 SokaBet + 1 Gwala, base 100):**

| stages funded | needs | P(bust/cycle) | loss on bust | EV/cycle |
|---|---|---|---|---|
| 3 | 2,100 | 0.2372 | −2,100 | −160 |
| 4 | 5,100 | 0.1469 | −5,100 | −260 |
| **5** | **12,000** | **0.0909** | **−12,000** | **−403** |
| 6 | 28,200 | 0.0563 | −28,200 | −611 ← unfunded at 21,000 |

**6. The identity that ends the argument.**

```
EV per cycle = expected turnover × edge
             = 13,660 × (−14.12%)
             = −1,929 TZS            (exact, both sides computed independently)
```

The ladder redistributes money between the 96% of cycles that close (+2,459 each) and the
3.9% that bust (−110,400 each). It multiplies turnover, and the edge is charged **on
turnover** — so escalating stakes increases the expected loss, it does not reduce it.

**7. Time to ruin.**

```
5 funded stages → P(bust) 0.0909/cycle → median 7.3 cycles
match weeks run every 120s → 12.6 cycles/hour
median time to lose the 21,000 bankroll:  35 MINUTES
expected burn: −5,071 TZS/hour
```

If Gwala turns out to carry the same Kiron feed: 45 minutes, −4,629/hour. Reducing the stake
from 300 to 100 and tripling the bankroll bought roughly **three times longer before ruin**,
at the same −14.12% per shilling. It bought time, not edge.

**Robustness.** Re-run under Shin de-vig (loads margin onto the longshot) instead of
proportional: edge moves from −14.12% to −13.74%. The conclusion does not depend on the
de-vig method.

---

## Known vs Assumed

**Known** (read directly off the screenshots, checkable):
- All six BTTS prices, identical across all three images → margins 5.25% / 5.11% / 5.25%.
- Balance TZS 9,784.75. Match weeks every 2 minutes (22:28, 22:30, 22:32 …).
- The three slips as selected, including the shared Spurs YES leg.
- Mutual exclusivity, margin compounding, ladder multiplier, bankroll shortfall — all
  arithmetic from the above, reproducible with `sokaligi_math.py`.

**Assumed / NEED DATA:**
1. **True probabilities = de-vigged book prices.** This is the *most generous* assumption
   available — it credits SokaLigi with pricing its own RNG honestly. If the RNG is shaded
   against the price, every figure here is optimistic. *Does not change the verdict:* the
   result is already negative at the generous end.
2. **Does Gwala carry the same Kiron feed as SokaBet?** `gwalabet.co.tz` is blocked by this
   container's network policy, so it could not be checked from here — and the link given was
   the `/casino` page, which is not where virtual football lives. Two things to confirm by
   hand: that Gwala runs SokaLigi/Kiron virtual football at all, and whether its match-week
   number matches SokaBet's. *Break-even value: none* — EV is −14.12% either way — but the
   5-stage bust rate moves 6.68% → 9.09% and median survival 45 → 35 minutes.
3. **Two accounts at one operator.** Slips A and B both sit on SokaBet. Bookmaker terms
   generally prohibit multiple or linked accounts betting the same event, and shared device,
   IP or payment details are the usual trigger. This is not a probability input — it is a
   path where the ladder cannot complete at all: an account frozen at stage 5 strands 12,000
   TZS mid-recovery with no way to close the cycle, and the balance at risk includes your
   friend's. Worth reading SokaBet's terms before the first stake rather than after.
4. **Derived-market consistency** — the screenshots show `1X2 & BTTS`, `1X2 & OV/UN 1.5`
   alongside plain `BTTS`. If the operator prices combined markets independently of their
   components, BTTS YES can be synthesised from `{1&Yes, X&Yes, 2&Yes}`. *Break-even value:
   synthetic book sum < 1.000.* This is the only structurally sound edge available and it is
   directly checkable with this repo's existing `arb_scan.py` method. **NOT YET MEASURED.**
5. **The Promos tab** (badge visible in all three screenshots). A bonus B at rollover R costs
   `R·B·margin` to clear, so it is +EV iff `R < 1/margin`:

   | cleared with | margin | max rollover |
   |---|---|---|
   | singles | 4.99% | **20.0×** |
   | doubles | 9.74% | 10.3× |
   | trebles (this plan) | 14.12% | 7.1× |

   *Break-even value: the actual rollover multiple and what it may be cleared with.* Not yet
   read. This is the one lever on that screen that can carry a positive number.

---

## Verdict → 🔴 DROP

**The one number: −14.12% of every shilling staked, fixed by the book's own prices, which no
stake plan can move. On a 21,000 bankroll at base 100 the median time to ruin is 35 minutes.**

Gate-by-gate, per the risk rules:

| gate | result |
|---|---|
| 1. No verdict without a number | ✅ passed — every figure computed |
| 2. Known vs Assumed labelled | ✅ passed |
| 3. Backtest vs live | ⚠️ no ledger exists yet; `sokaligi_bot.py status` builds one |
| 4. Execution & liquidity | ❌ **FAILED** — verified negative edge, nothing to fill |
| 5. Assumption concentration | ✅ passed — conclusion holds at the generous end of every assumption |
| 6. Risk-first sizing | ❌ **FAILED** — Kelly negative; bankroll funds 3 of 6 stages |

Two hard gates fail. The verdict cannot rise above DROP, and the failures are structural
rather than parameter choices: there is no base stake, multiplier, stage count or slip
combination that makes a −14.12% edge positive.

**Why it feels like it works.** The cycle closes in profit 96.1% of the time. Ninety-six
wins out of a hundred is an extremely convincing experience, and the 3.9% that pays for all
of them arrives as a single −110,400 loss. The strategy is not a way to win; it is a way to
convert many small wins into one large loss while paying 14.12% for the conversion.

**Next step, sized by the risk rule:** stake **0**. Three measurements cost nothing and settle
the open questions:
1. Read the Promos terms. If rollover < 20× and clearable on singles, that is a positive
   number — price it with `sokaligi_math.py promo --bonus B --rollover R`.
2. Confirm Gwala carries Kiron virtual football, and compare its match-week number to
   SokaBet's.
3. Log one round of `1X2 & BTTS` prices and test them against plain `BTTS` for a synthetic
   book sum below 1.000. That is the only edge here that could survive contact with the math.

---

## Operating parameters (strategy retained by the operator's decision)

The verdict above is unchanged — the math does not move. These are the settings the plan is
being run under anyway, and `sokaligi_bot.py` enforces them:

```
python sokaligi_bot.py init --bankroll 21000 --base 100 --stages 5 \
    --books soka-mine soka-friend gwala --feed 0,0,1 --stop-loss 12000

python sokaligi_bot.py next   --odds 1.69,2.17 1.84,1.97 1.69,2.17
python sokaligi_bot.py settle --results NNY/YYN      # soka draw / gwala draw
python sokaligi_bot.py status
```

- **`--stages 5`, not 6.** 21,000 funds five stages (12,000). Setting 6 does not create a
  sixth stage; it only means the bot blocks at stage 6 with 12,000 already committed. To run
  the 6-stage plan as written the bankroll is **28,200**.
- **`--feed 0,0,1`** — slips A and B settle on one SokaBet match week, slip C on Gwala's.
  Change to `shared` if the match-week numbers turn out to match.
- **`--stop-loss`** caps session drawdown and is checked *before* each stake, not after.
- The bot refuses to place a stage the bankroll cannot settle, which is the failure mode of
  running this by hand.
- Every round is logged to `data/sokaligi_ledger.csv`. After 150 tickets `status` compares the
  realised rate against the model's −14.12%. **That ledger is the EV check** — if the two
  disagree by more than 5 points, the ledger wins and the model gets re-examined.

---

## Changes since last time

First update for this strategy — no prior baseline. Carried over from the existing repo:
the `analyze_markets.py` / `arb_scan.py` approach of pricing a virtual league off its own
distribution rather than off intuition is what produced the finding here.

---

## 🗑️ Kill List

- **Martingale as a recovery mechanism.** EV is linear in stake; escalation multiplies
  turnover and the edge is charged on turnover. Dead on arithmetic, not on luck.
- **The 6-stage / 300-base plan on a 9,785 bankroll.** It is a 3-stage plan with a 19.7%
  bust rate pretending to be a 6-stage plan with a 3.9% one.
- **Trebles as a format.** Three legs triple the margin to −14.12%. If any bet is placed on
  this product, singles at −4.99% cost a third as much.
- **The overlapping-slip hedge.** Mutually exclusive slips sharing one leg: it cannot win
  more than one ticket, and loses all three 83% of the time it loses at all.
- **"Doubling up."** The multiplier this structure needs is 2.33. A 2× ladder does not
  recover even when it wins.
