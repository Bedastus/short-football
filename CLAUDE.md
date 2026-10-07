# SokaLigi BTTS Treble Ladder

## What This Is

A ladder management system for SokaLigi (Kiron virtual football) BTTS markets. Three people each hold one account. They place one treble ticket per round from three mutually exclusive slips. A 5-stage martingale ladder runs on a pooled 21,000 TZS bankroll at base stake 200 per slip.

## Project Structure

```
short-football/
├── CLAUDE.md                          # THIS FILE
├── .gitignore                         # ignores data/, profiles/, __pycache__/
├── .vscode/
│   ├── tasks.json                     # numbered VS Code tasks (0-4)
│   ├── launch.json                    # debug configurations
│   ├── settings.json                  # code-runner.runInTerminal = true
│   └── extensions.json                # recommends ms-python.python
│
└── short football/                    # all source lives here (note the space)
    ├── sokaligi_math.py               # pricing engine (790 lines)
    ├── sokaligi_bot.py                # ladder controller (717 lines)
    ├── open_books.py                  # browser profile launcher (190 lines)
    ├── start.bat                      # Windows launcher
    ├── start.ps1                      # PowerShell launcher
    ├── browsers.bat                   # opens 3 tiled browser windows
    ├── STRATEGY.md                    # full math write-up (verdict: DROP)
    ├── RUNBOOK.md                     # operating manual
    ├── analyze_markets.py             # pre-existing, not part of this system
    ├── collect_odds.py                # pre-existing, not part of this system
    ├── arb_scan.py                    # pre-existing, not part of this system
    ├── daily_report.py                # pre-existing, not part of this system
    └── data/                          # created at runtime, gitignored
        ├── sokaligi_state.json        # ladder state (cycle, stage, bankroll)
        └── sokaligi_ledger.csv        # all placed tickets with outcomes
```

## Dependencies

None. Everything is Python standard library.

## The Three Slips

| Slip | Leeds BTTS | Spurs BTTS | N.Forest BTTS | Default Odds |
|------|-----------|-----------|---------------|-------------|
| A    | YES       | YES       | YES           | ~5.255      |
| B    | NO        | YES       | YES           | ~6.748      |
| C    | YES       | YES       | NO            | ~6.748      |

All three share Spurs YES. Slips are mutually exclusive: at most one wins per round.

## Parameters

- Bankroll: 21,000 TZS pooled
- Base stake: 200 TZS per slip (600 per round)
- Stages: 5
- Stop-loss: 19,800 TZS
- Step: 100 TZS rounding
- Match cycle: 2-minute Kiron virtual match weeks

## Martingale Sizing

Deficit-driven, not fixed geometric:
```
per_slip_k = ceil( (cumulative_{k-1} + target) / (worst - 1) / 3 )
```

## What Has Been Built

### sokaligi_math.py — Pricing Engine
- De-vigging (proportional and Shin methods)
- Exact enumeration of all 8 joint outcomes per round
- Slip pricing (decimal odds and true probability per treble)
- Ladder sizing from carried deficit
- Cycle distribution (exact path enumeration)
- Ruin probability, breakeven margin, fit-to-budget
- Outcome collapse for mixed feeds
- Subcommands: price, ladder, cycle, ruin, breakeven, promo, fit
- Live odds via --odds flag on every subcommand

### sokaligi_bot.py — Ladder Controller
- State machine: init, plan, commit, settle, status, reset
- plan_round() — sizes next stage, checks 5 gates
- commit_round() — records pending round, deducts bankroll
- settle_round() — settles tickets, writes ledger, advances cycle
- Interactive loop (cmd_run) with live odds input
- Per-person distribution cards with match names
- --rotate for fair slip assignment rotation
- Per-person P&L in status
- LadderBlocked exception for gate checks
- CSV ledger audit trail
- PlacementAdapter plug-in seam for custom placement

### open_books.py — Browser Launcher
- 3 tiled Chromium windows with separate cookie jars
- Auto-detects browser and screen size
- Each window labeled with slip assignment

### Launchers and VS Code
- start.bat / start.ps1 — one-click init-then-run
- browsers.bat — open 3 browser windows
- VS Code tasks: START, Open browsers, Init, RUN loop, Status

### Documentation
- STRATEGY.md — full math analysis
- RUNBOOK.md — operating guide

## What Has NOT Been Built

### Auto-Staking
Automated placement via the operator's API. The PlacementAdapter class in sokaligi_bot.py (line 94) is designed as a plug-in point for this. A custom adapter subclass that implements the place() method and is registered in the ADAPTERS dict would complete the loop. Run with --adapter <name>.

### Odds Scraper
Auto-fetch current BTTS odds instead of manual input. Would feed directly into plan_round().

### Auto-Settlement
Auto-read match results instead of manual input. Would feed into settle_round().

### Web Dashboard
Browser-based UI replacing the CLI. Designed but not built. Would serve a single HTML page from a Python stdlib HTTP server with odds form, distribution cards, countdown timer, and P&L display.

## Key Functions for Extension

- `sokaligi_bot.plan_round(state, odds)` — sizes a round, returns plan with tickets
- `sokaligi_bot.commit_round(state, plan)` — records round as pending
- `sokaligi_bot.settle_round(state, results)` — settles and writes ledger
- `sokaligi_bot.parse_odds(["1.69,2.17", ...])` — validates odds
- `sokaligi_bot.parse_results("YNY", feed)` — validates results
- `sokaligi_math.ladder(base, stages, step, worst, target)` — stake table
- `sokaligi_math.round_outcomes(method, feed)` — exact outcome enumeration

## Running

```bash
cd "short football"
python sokaligi_bot.py init --bankroll 21000 --base 200 --stages 5 --books soka-1 soka-2 soka-3 --rotate
python sokaligi_bot.py run
```

## State File Format

```json
{
  "bankroll": 21000.0,
  "opening_bankroll": 21000.0,
  "base": 200.0,
  "step": 100.0,
  "target": 0.0,
  "max_stages": 5,
  "stop_loss": 19800.0,
  "books": ["soka-1", "soka-2", "soka-3"],
  "feed": "shared",
  "rotate": true,
  "cycle": 1,
  "stage": 0,
  "cycle_staked": 0.0,
  "cycle_returned": 0.0,
  "pending": null,
  "last_odds": null
}
```
