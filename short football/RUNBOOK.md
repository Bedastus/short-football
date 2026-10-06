# SokaLigi runbook

Operating notes for the three-slip BTTS ladder. The arithmetic behind it, and the verdict on
whether it is worth running, are in [`STRATEGY.md`](STRATEGY.md).

## Configuration

| | |
|---|---|
| accounts | 3, all at SokaBet (`soka-1`, `soka-2`, `soka-3`) |
| feed | `shared` — one match week settles all three slips |
| base stake | 200 per slip (600 per round) |
| stages | 5, costing 19,800 cumulative |
| bankroll | 21,000 |
| stop-loss | 19,800 |

Base 200 is the largest stake whose whole 5-stage ladder fits a 20,000 budget. Re-solve it
any time the budget changes:

```bash
python3 sokaligi_math.py fit --feed shared --stages 5 --budget 20000 --step 100
```

## VS Code

Tasks live in `.vscode/tasks.json`. **Terminal → Run Task**, or bind `workbench.action.tasks.runTask`
to a key. They run in numbered order:

| task | what it does |
|---|---|
| 1. Open 3 account browsers | three isolated profiles, tiled left to right |
| 2. Init ladder | creates `data/sokaligi_state.json` — wipes any cycle in progress |
| 3. Next stage | prompts for the three live odds pairs, prints what to place |
| 4. Settle round | prompts for the Y/N results, advances or resets the ladder |
| 5. Status + ledger | bankroll, stage, realised rate vs model |

Plus `Fit stake to budget`, `Price the round`, `Survival / ruin table`, and
`Abandon cycle` off-cycle. `.vscode/launch.json` has debugger entry points for the same
scripts. Install the recommended extensions when VS Code offers them (`ms-python.python`,
`ms-python.debugpy`); no virtualenv is needed, everything is standard library.

## Per-round loop

Match weeks start every two minutes, so this has to be quick.

```bash
python3 open_books.py --accounts 3           # once per session
python3 sokaligi_bot.py next --odds 1.69,2.17 1.84,1.97 1.69,2.17
#   place the three tickets at the stakes it prints
python3 sokaligi_bot.py settle --results YNY  # results in match order
```

**Odds go in fresh every round.** Kiron re-prices each match week, and stage 4 sized off stage
1's prices does not recover. `next` solves the stake from the odds you give it.

**Results are one triple in match order** — Leeds, Spurs, N.Forest — `Y` where both teams
scored. One triple because one draw settles all three accounts.

## The three slips

| account | slip | Leeds | Spurs | N.Forest |
|---|---|---|---|---|
| soka-1 | A | YES | YES | YES |
| soka-2 | B | NO | YES | YES |
| soka-3 | C | YES | YES | NO |

All three carry **Spurs YES**, and all three lose together whenever that leg fails. At most
one can win per round — they are mutually exclusive by construction.

## Browser profiles

`open_books.py` gives each account its own Chromium profile directory, so each window keeps a
separate session cookie:

```bash
python3 open_books.py --accounts 3 --screen 1920x1080
python3 open_books.py --dry-run                      # print commands, launch nothing
python3 open_books.py --browser "/path/to/chrome"    # if auto-detect misses
```

Profiles live in `profiles/` (gitignored) and persist, so you sign in once. Windows tile left
to right in account order — window 1 is `soka-1`, which is what makes three tickets placeable
under a two-minute clock.

It opens labelled windows and nothing more: no user-agent or fingerprint masking, no proxy
rotation, no automated placement.

## What the bot refuses to do

- Place a stage the bankroll cannot settle — it names the shortfall instead.
- Place past `--stop-loss`, checked before the stake rather than after.
- Size a round where even the cheapest winning slip returns less than it costs.
- Continue past stage 5 — `reset` starts a new cycle, deliberately.

## Ledger

Every ticket lands in `data/sokaligi_ledger.csv`. After 150 tickets, `status` compares the
realised return per shilling against the model's −14.12%:

```bash
python3 sokaligi_bot.py status
```

If the two disagree by more than 5 points, the ledger is the one to believe.
