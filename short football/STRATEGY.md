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

A 2× double **never recovers** here. At m = 2.34, base 300/slip:

| stage | per slip | per round | cumulative | worst payout | worst net |
|---|---|---|---|---|---|
| 1 | 300 | 900 | 900 | 1,577 | +677 |
| 2 | 700 | 2,100 | 3,000 | 3,679 | +679 |
| 3 | 1,700 | 5,100 | 8,100 | 8,934 | +834 |
| 4 | 3,800 | 11,400 | 19,500 | 19,970 | +470 |
| 5 | 8,700 | 26,100 | 45,600 | 45,720 | +120 |
| 6 | 20,200 | 60,600 | **106,200** | 106,156 | −44 |

**The 6-stage plan needs 106,200 TZS. The screenshot balance is 9,784.75 — 9.2% of it.**

**5. The plan on this bankroll is a 3-stage ladder, not a 6-stage one.**

| stages funded | needs | P(bust per cycle) | loss on bust | EV per cycle |
|---|---|---|---|---|
| 1 | 900 | 0.5821 | −900 | −127 |
| 2 | 3,000 | 0.3388 | −3,000 | −300 |
| **3** | **8,100** | **0.1972** | **−8,100** | **−544** |
| 4 | 19,500 | 0.1148 | −19,500 | −861 ← unfunded |
| 5 | 45,600 | 0.0668 | −45,600 | −1,284 ← unfunded |
| 6 | 106,200 | 0.0389 | −110,400 | −1,929 ← unfunded |

The plan assumes a 3.9% bust rate. The bankroll delivers **19.7%** — five times higher.

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
3 funded stages → P(bust) 0.1972/cycle → median 3.2 cycles
match weeks run every 120s → 15.6 cycles/hour
median time to lose the 9,785 bankroll:  12 MINUTES
expected burn: −8,492 TZS/hour (−25,167/hour if the full ladder were funded)
```

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
2. **Shared vs independent Kiron feed across the three bookmakers.** "Match Week #35624537"
   is a global ID, which looks like a shared feed. *Break-even value: none.* EV is −14.12%
   either way; only ruin moves (3.9% vs 6.7% per cycle at full funding). Verify by comparing
   the match-week number on all three books before the first stake — **if the feeds are
   independent, the overlapping-slip design has no purpose at all**, since the hedge only
   means anything when one draw settles all three tickets.
3. **Derived-market consistency** — the screenshots show `1X2 & BTTS`, `1X2 & OV/UN 1.5`
   alongside plain `BTTS`. If the operator prices combined markets independently of their
   components, BTTS YES can be synthesised from `{1&Yes, X&Yes, 2&Yes}`. *Break-even value:
   synthetic book sum < 1.000.* This is the only structurally sound edge available and it is
   directly checkable with this repo's existing `arb_scan.py` method. **NOT YET MEASURED.**
4. **The Promos tab** (badge visible in all three screenshots). A bonus B at rollover R costs
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
stake plan can move. On a 9,785 bankroll the median time to ruin is 12 minutes.**

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

**Next step, sized by the risk rule:** stake **0**. Spend the next session measuring, not
betting:
1. Read the Promos terms. If rollover < 20× and clearable on singles, that is a positive
   number — price it with `sokaligi_math.py promo --bonus B --rollover R`.
2. Compare the match-week number across all three books (one minute, zero cost, settles
   NEED DATA #2).
3. Log a round of `1X2 & BTTS` prices and test them against plain `BTTS` for a synthetic
   book sum below 1.000. That is the only edge here that could survive contact with the math.

If you want to run the plan anyway on money you are willing to lose, `sokaligi_bot.py`
enforces the ladder correctly and refuses to place a stage the bankroll cannot settle —
which is where the hand-run version fails. Set `--stages 3`, since that is what 9,785 funds,
and `--stop-loss` to the amount you accept losing. It will not make the system profitable.

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
