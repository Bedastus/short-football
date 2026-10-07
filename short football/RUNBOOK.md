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

Every `sokaligi_math.py` subcommand also takes `--odds`, to price the round in front of you
rather than the screenshot it was written against:

```bash
python3 sokaligi_math.py price --odds 1.75,2.05 1.90,1.92 1.62,2.30
python3 sokaligi_math.py fit   --odds 1.75,2.05 1.90,1.92 1.62,2.30 --stages 5 --budget 20000
```

## Windows — start here

Double-click **`start.bat`**, or from PowerShell:

```powershell
cd "C:\Users\Anonymous\Desktop\Projects\kiron Allan"
.\start.bat
```

It sets the ladder up the first time and goes straight into the round loop every time after.
Change the bankroll, base stake, stages or stop-loss by editing the four lines at the top of
the file. `start.ps1` does the same job if you prefer PowerShell.

Using the launcher avoids the one trap that catches everyone here: **PowerShell has no `\`
line continuation.** That is a bash convention. Paste a wrapped bash-style command and
PowerShell reads the `--` at the start of the second line as a unary operator:

```
Missing expression after unary operator '--'.
Unexpected token 'books' in expression or statement.
```

If you do type commands by hand, keep each one on a **single line**, and use `python` or
`py -3` rather than `python3`:

```powershell
python sokaligi_bot.py init --bankroll 21000 --base 200 --stages 5 --step 100 --books soka-1 soka-2 soka-3 --feed shared --stop-loss 19800
python sokaligi_bot.py run
```

`init` runs once per session. After that `run` is the only command you need.

## If the prompt will not accept typing

A prompt that sits there ignoring the keyboard means the script is running in a
**read-only output pane** rather than a terminal. The giveaway is a header like:

```
[Running] cmd /c "...\start.bat"
```

That is the Code Runner extension, which prints to the Output panel. The panel cannot
receive keystrokes, so `run` waits forever for odds you have no way to type.

Fix it once, either way:

- **Settings** — `Ctrl+,`, search `code-runner.runInTerminal`, tick it. (Already set in this
  project's `.vscode/settings.json`, so reopening the folder is usually enough.)
- **Or skip Code Runner** — open a terminal with ``Ctrl+` `` and run `.\start.bat` there, or
  use **Terminal → Run Task → 0. START**.

Anything that gives you a real terminal works; the Run button in the editor corner does not.

## VS Code

Tasks live in `.vscode/tasks.json`. **Terminal → Run Task**, numbered in running order:

| task | what it does |
|---|---|
| 1. Open 3 account browsers | three isolated profiles, tiled left to right |
| 2. Init ladder | creates `data/sokaligi_state.json` — wipes any cycle in progress |
| **3. RUN interactive loop** | **the per-round loop; the only one you need while playing** |
| 4. Status + ledger | bankroll, stage, realised rate vs model |

Off-cycle: `Fit stake to budget`, `Price the round`, `Survival / ruin table`, `Abandon cycle`,
and one-shot `size next stage` / `settle round` for a single round by hand.
`.vscode/launch.json` has debugger entry points. Install the recommended extensions when
offered; no virtualenv is needed, everything is standard library.

## The loop

```
python sokaligi_bot.py run
```

Each round it asks for the three BTTS prices, sizes the stakes from them, prints what to
place, then asks for the results:

```
cycle 1  stage 2/5  bankroll 20,400  deficit 600
  odds for this match week  (Enter reuses, 's' skip, 'q' quit, '?' help)
    match 1 yes,no [1.69,2.17]:
    match 2 yes,no [1.84,1.97]: 1.90,1.92
    match 3 yes,no [1.69,2.17]:
=== cycle 1, stage 2 ===
  stake per slip    300   round total 900
    soka-1  slip A  Y Y Y  @ 5.414  stake 300
    soka-2  slip B  N Y Y  @ 6.953  stake 300
    soka-3  slip C  Y Y N  @ 6.953  stake 300

  results for this match week (e.g. YNY, or 'q'): YNY
```

- **Nothing is hardcoded.** Stakes are solved from the prices you type, every round. A price
  that moves mid-session is handled; a stage sized off a stale price is not.
- **Enter alone reuses** the value in brackets, so only changed prices need typing — which is
  what makes a two-minute match week workable.
- `s` sits the round out, `q` stops. State saves after every round, so `run` again picks up
  mid-ladder exactly where it left off.
- If a gate blocks the round (unfunded, past the stop-loss, ladder exhausted) it says which
  and offers to reset, rather than dying with a deficit still carried.

Results are one triple in match order — Leeds, Spurs, N.Forest — `Y` where both teams scored.
One triple because one SokaBet draw settles all three accounts.

## Three people, three accounts

This is built for three people each on their own SokaBet account, one ticket per game — within
the one-ticket-per-game rule. Name the accounts after the people at `init`:

```
python sokaligi_bot.py init --bankroll 21000 --base 200 --stages 5 --step 100 --books Allan Baraka Juma --feed shared --stop-loss 19800
```

Each round the bot prints one card per person, with the picks spelled out so nobody decodes
`Y Y Y` against the clock:

```
  +-- Allan  (slip A) -----------------------------
  |   BTTS YES   Leeds/London Reds
  |   BTTS YES   Spurs/Leicester
  |   BTTS YES   N.Forest/London Blues
  |   combined odds 5.255   STAKE 200
  +--------------------------------------------
```

Everyone places their own ticket on their own account. The bot never touches the accounts; it
assigns and tracks.

**Fair sharing with `--rotate`.** Slip A sits at shorter odds than B and C, so whoever holds
it wins a little more often for a little less. Pass `--rotate` at init and the A/B/C
assignment rotates each cycle, so over time each person spends an equal share on each slip.
Leave it off if the bankroll is pooled and it doesn't matter who holds what.

**Settling up.** `python sokaligi_bot.py status` shows a per-person line — staked, returned,
net, tickets won — which is the number to square up on if the three keep separate money.

## The three slips

| account | slip | Leeds | Spurs | N.Forest |
|---|---|---|---|---|
| soka-1 | A | YES | YES | YES |
| soka-2 | B | NO | YES | YES |
| soka-3 | C | YES | YES | NO |

All three carry **Spurs YES**, and all three lose together whenever that leg fails. At most
one can win per round — they are mutually exclusive by construction.

## The three accounts

Nothing connects the bot to SokaBet. It prints three stakes; you place three tickets. What
ties an account to a ticket is **window order**, fixed by the launcher:

| window | profile | account | slip | legs |
|---|---|---|---|---|
| leftmost | `soka-1` | account 1 | A | Y Y Y |
| middle | `soka-2` | account 2 | B | N Y Y |
| rightmost | `soka-3` | account 3 | C | Y Y N |

That mapping is also what the bot prints each round, so the two always agree:

```
    soka-1  slip A  Y Y Y  @ 5.255  stake 200
    soka-2  slip B  N Y Y  @ 6.748  stake 200
    soka-3  slip C  Y Y N  @ 6.748  stake 200
```

### First time

Double-click **`browsers.bat`**. Three windows open side by side. Sign a **different account
into each** — left window gets account 1, middle gets account 2, right gets account 3.

Each window is a separate Chromium profile with its own cookie jar, which is what lets three
accounts be signed in at once: one browser profile holds one session per site, so a second
account in the same profile signs the first one out.

### Every time after

Double-click `browsers.bat` again. The profiles persist in `profiles\`, so the windows come
back already signed in, in the same order. Then run `start.bat` in a terminal alongside them.

Keep the windows where they open. If you shuffle them you lose the only thing telling you
which ticket belongs where, and a slip placed on the wrong account breaks the mutual
exclusivity the ladder is sized against.

### Options

```bash
python open_books.py --accounts 3                 # screen size auto-detected
python open_books.py --screen 1366x768            # if auto-detect is wrong
python open_books.py --dry-run                    # print commands, launch nothing
python open_books.py --browser "C:\Program Files\Google\Chrome\Application\chrome.exe"
```

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
