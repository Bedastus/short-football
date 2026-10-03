"""Settle every collected kickoff quote against its own match result.

This is the only test in the project that uses no baseline at all. It takes the
price that was actually on offer at kickoff, looks up what that exact match
actually did, and books the bet. No historical averages, no probability model,
nothing to go stale.

That matters because every false edge found in this project came from comparing
a live price against a historical baseline:

  * a 73rd-minute price against a whole-match probability  (+397%, false)
  * a live line against a 5-month mean that had drifted    (+53%,  false)
  * the same against a 21-day mean                         (+24%,  false)

Short Football D1's mean total went 14.70 in May to 7.95 in September. Any
baseline averages regimes together. Settling on each match's own result cannot
fail that way.

    python daily_report.py
    python daily_report.py --since 2026-10-02      # today's collection only
    python daily_report.py --by-league

Quotes are taken at kickoff only (score 0-0, clock under 90s) so that no part of
the match has already happened when the price is read.
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import json
import math
import re
import statistics
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
SITE_TZ = dt.timezone(dt.timedelta(hours=3))
UA = {"User-Agent": "Mozilla/5.0"}
RESULTS_API = "https://helabet.co.tz/service-api/result/web/api/v3/games"

MARKET_NAMES = {
    ("1", "1"): "1X2 W1", ("1", "2"): "1X2 Draw", ("1", "3"): "1X2 W2",
    ("8", "4"): "DC 1X", ("8", "5"): "DC 12", ("8", "6"): "DC X2",
    ("17", "9"): "Total Over", ("17", "10"): "Total Under",
    ("15", "11"): "T1 Total Over", ("15", "12"): "T1 Total Under",
    ("62", "13"): "T2 Total Over", ("62", "14"): "T2 Total Under",
    ("2", "7"): "Handicap 1", ("2", "8"): "Handicap 2",
}


def fetch_results(days: int) -> dict[int, dict]:
    with (HERE / "leagues.json").open(encoding="utf-8") as handle:
        champs = [int(k) for k, v in json.load(handle)["leagues"].items()
                  if v["enabled"]]
    out: dict[int, dict] = {}
    today = dt.datetime.now(SITE_TZ).date()
    for champ in champs:
        for offset in range(days):
            day = today - dt.timedelta(days=offset)
            start = int(dt.datetime.combine(day, dt.time.min,
                                            tzinfo=SITE_TZ).timestamp())
            url = (f"{RESULTS_API}?champId={champ}&dateFrom={start}"
                   f"&dateTo={start + 86400}&lng=en&ref=237")
            try:
                body = urllib.request.urlopen(
                    urllib.request.Request(url, headers=UA), timeout=30).read()
                for item in (json.loads(body).get("items") or []):
                    out[item["id"]] = item
            except Exception:  # noqa: BLE001 - a missing day is not fatal
                continue
    return out


def settle(group: str, etype: str, line: float | None,
           home: int, away: int) -> bool | str | None:
    """Did this selection win? 'void' means the stake comes back."""
    total = home + away
    if group == "1":
        return {"1": home > away, "2": home == away, "3": away > home}.get(etype)
    if group == "8":
        return {"4": home >= away, "5": home != away, "6": away >= home}.get(etype)
    if line is None:
        return None
    if group == "17":
        if etype == "9":
            return "void" if total == line else total > line
        if etype == "10":
            return "void" if total == line else total < line
    if group == "15":
        if etype == "11":
            return "void" if home == line else home > line
        if etype == "12":
            return "void" if home == line else home < line
    if group == "62":
        if etype == "13":
            return "void" if away == line else away > line
        if etype == "14":
            return "void" if away == line else away < line
    if group == "2":
        if etype == "7":
            return "void" if home + line == away else home + line > away
        if etype == "8":
            return "void" if away + line == home else away + line > home
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--odds-csv",
                        default=str(HERE / "data" / "odds_all_leagues.csv"))
    parser.add_argument("--days", type=int, default=3,
                        help="days of results to pull")
    parser.add_argument("--since", help="only quotes captured on/after YYYY-MM-DD")
    parser.add_argument("--by-league", action="store_true")
    parser.add_argument("--max-clock", type=int, default=90)
    args = parser.parse_args()

    path = Path(args.odds_csv)
    if not path.exists():
        print(f"No snapshots at {path}")
        return 1
    with path.open(encoding="utf-8") as handle:
        snaps = [r for r in csv.DictReader(handle) if r["scope"] == "match"]

    def clock(row: dict) -> int:
        try:
            return int(row["timer_sec"])
        except (TypeError, ValueError):
            return -1

    kick = [r for r in snaps
            if r["score"] == "0-0" and 0 <= clock(r) <= args.max_clock]
    if args.since:
        kick = [r for r in kick if r["captured_utc"][:10] >= args.since]
    if not kick:
        print("No kickoff quotes in range.")
        return 1

    # One quote per selection per match: the earliest seen.
    first: dict[tuple, dict] = {}
    for row in sorted(kick, key=lambda r: r["captured_utc"]):
        first.setdefault(
            (int(row["match_id"]), row["group_id"], row["event_type"],
             row["parameter"]), row)

    results = fetch_results(args.days)
    print(f"{len(kick):,} kickoff rows -> {len(first):,} unique quotes; "
          f"{len(results):,} results available\n")

    by_market: dict[str, list] = collections.defaultdict(list)
    by_pair: dict[tuple, list] = collections.defaultdict(list)
    for (match_id, group, etype, param), row in first.items():
        result = results.get(match_id)
        if not result:
            continue
        score = re.match(r"^\s*(\d+)\s*:\s*(\d+)", result.get("score", ""))
        if not score:
            continue
        home, away = int(score.group(1)), int(score.group(2))
        line = float(param) if param else None
        won = settle(group, etype, line, home, away)
        name = MARKET_NAMES.get((group, etype))
        if won is None or not name:
            continue
        odds = float(row["odds"])
        profit = 0.0 if won == "void" else (odds - 1 if won else -1.0)
        entry = (profit, won == "void", bool(won is True))
        by_market[name].append(entry)
        by_pair[(row["slug"], name)].append(entry)

    def summarise(label: str, rows: list) -> tuple:
        bets = len(rows)
        voids = sum(1 for _p, v, _w in rows if v)
        live = bets - voids
        wins = sum(1 for _p, _v, w in rows if w)
        pnl = sum(p for p, _v, _w in rows)
        roi = pnl / live if live else 0.0
        # error bar on ROI from the win-rate standard error
        if live:
            rate = wins / live
            err = 1.96 * math.sqrt(rate * (1 - rate) / live) * 2.0
        else:
            err = 0.0
        return bets, voids, live, wins, pnl, roi, err

    print("SETTLED ON EACH MATCH'S OWN RESULT - no baseline used")
    print(f"{'market':<16} {'bets':>6} {'void':>5} {'win rate':>9} "
          f"{'P&L':>10} {'ROI':>9} {'95% band':>18}")
    total_pnl = total_live = 0
    for name, rows in sorted(by_market.items(),
                             key=lambda kv: -sum(p for p, _v, _w in kv[1])
                             / max(len(kv[1]), 1)):
        bets, voids, live, wins, pnl, roi, err = summarise(name, rows)
        if live < 30:
            continue
        total_pnl += pnl
        total_live += live
        band = f"{100 * (roi - err):+.2f}% .. {100 * (roi + err):+.2f}%"
        print(f"{name:<16} {bets:>6,} {voids:>5,} {100 * wins / live:>8.1f}% "
              f"{pnl:>+10.1f} {100 * roi:>+8.2f}% {band:>18}")
    if total_live:
        print(f"\n{'ALL':<16} {total_live:>6,} {'':>5} {'':>9} "
              f"{total_pnl:>+10.1f} {100 * total_pnl / total_live:>+8.2f}%")

    print("\nA band that spans zero means the sample cannot yet tell an edge "
          "from noise.")

    if args.by_league:
        print("\n\nBY LEAGUE AND MARKET (60+ settled bets)")
        print(f"{'league':<28} {'market':<16} {'bets':>6} {'ROI':>9} {'95% band':>18}")
        ranked = []
        for (league, name), rows in by_pair.items():
            bets, voids, live, wins, pnl, roi, err = summarise(name, rows)
            if live >= 60:
                ranked.append((roi, league, name, live, roi, err))
        for _s, league, name, live, roi, err in sorted(ranked, reverse=True):
            band = f"{100 * (roi - err):+.2f}% .. {100 * (roi + err):+.2f}%"
            print(f"{league:<28} {name:<16} {live:>6,} "
                  f"{100 * roi:>+8.2f}% {band:>18}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
