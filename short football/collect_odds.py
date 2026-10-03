"""Log Helabet's Short Football 2x2 odds at kickoff, then settle them against results.

Why this exists
---------------
Helabet serves no odds history: `gameEvents` returns an empty body the moment a
match finishes, and the league has no pre-match line at all
(`main-line-feed/v3/champGames` is empty for champ 2055906). Prices therefore
have to be captured live, as matches start, or they are gone. Without them the
23k scraped results cannot be turned into an expected-value test.

Two modes
---------
    python collect_odds.py collect --minutes 60
        Poll the live championship page, snapshot every market for each running
        match, and append to data/odds_snapshots.csv.

    python collect_odds.py settle
        Re-scrape today's results, join them to the earliest (closest to
        kickoff) snapshot of each match, and write data/odds_settled.csv with
        the realised outcome of every logged selection.

Discovery
---------
The live game list arrives as server-rendered HTML, not JSON: replaying
`main-live-feed/v3/games1x2` returns an empty array even from inside the page
session, because the browser receives later updates over a socket. So match ids
are read out of the championship page's HTML, and each id is then passed to
`gameEvents`, which does work over plain HTTP while the match is live.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

CATALOG = Path(__file__).with_name("leagues.json")
CHAMP_ID = 2055906  # kept for the single-champ results lookup in settle()
EVENTS_API = "https://helabet.co.tz/service-api/main-live-feed/v3/gameEvents"
RESULTS_API = "https://helabet.co.tz/service-api/result/web/api/v3/games"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)
SITE_TZ = dt.timezone(dt.timedelta(hours=3))
GAME_LINK_RE = re.compile(r"short-football-2x2/(\d{6,})-([a-z0-9-]+)")

# (groupId, type) -> market label.
#
# "verified" entries were confirmed arithmetically: the double-chance prices
# reproduce 1/(1/d_a + 1/d_b) from the 1X2 prices to within 0.2%, which pins
# both groups. Over/under legs are pinned by their ladders - the leg whose
# price lengthens as the line rises is the Over.
#
# "unverified" entries are structural guesses from the 1xBet-style schema and
# are recorded raw so a later pass can settle them against outcomes. Do not
# trade them on the strength of the label alone.
MARKETS = {
    (1, 1): ("W1", "verified"),
    (1, 2): ("X", "verified"),
    (1, 3): ("W2", "verified"),
    (8, 4): ("DC 1X", "verified"),
    (8, 5): ("DC 12", "verified"),
    (8, 6): ("DC X2", "verified"),
    (17, 9): ("Total Over", "verified"),
    (17, 10): ("Total Under", "verified"),
    (17, 3827): ("Asian Total Over", "verified"),
    (17, 3828): ("Asian Total Under", "verified"),
    (2, 7): ("Handicap 1", "verified"),
    (2, 8): ("Handicap 2", "verified"),
    (2, 3829): ("Asian Handicap 1", "verified"),
    (2, 3830): ("Asian Handicap 2", "verified"),
    (15, 11): ("Team1 Total Over", "unverified"),
    (15, 12): ("Team1 Total Under", "unverified"),
    (62, 13): ("Team2 Total Over", "unverified"),
    (62, 14): ("Team2 Total Under", "unverified"),
    (14, 182): ("Total Even/Odd A", "unverified"),
    (14, 183): ("Total Even/Odd B", "unverified"),
    # Group 20 is the Next Goal market. Confirmed against the bet slip: a
    # Division 4x4 game at 1-2 showed 1.936 / 1.936 / 9 on goal 4, matching
    # "Team 1 To Score Goal 4 / Team 2 To Score Goal 4 / No Goal 4" exactly.
    # The parameter is the goal index N, and several N are quoted at once.
    (20, 388): ("Next Goal Team1", "verified"),
    (20, 389): ("Next Goal Team2", "verified"),
    (20, 390): ("No Next Goal", "verified"),
    # Read off the live bet slip and matched to the JSON in the same instant:
    # "Each Team To Score 3 Or More - Yes/No" showed 5.04 / 1.144 against
    # g19/t11273/p3 and g19/t11274/p3. The parameter is the goal threshold N.
    (19, 11273): ("Each Team To Score N+ Yes", "verified"),
    (19, 11274): ("Each Team To Score N+ No", "verified"),
    # The panel labels these sections "Total 1" and "Total 2", confirming the
    # team-total reading that was previously only structural.
    (15, 11): ("Team1 Total Over", "verified"),
    (15, 12): ("Team1 Total Under", "verified"),
    (62, 13): ("Team2 Total Over", "verified"),
    (62, 14): ("Team2 Total Under", "verified"),
    # Panel sections "1, Result + Total" and "2, Result + Total".
    (87, 739): ("Result+Total A", "unverified"),
    (87, 741): ("Result+Total B", "unverified"),
    (87, 743): ("Result+Total C", "unverified"),
}

# Rows already on disk store group_id and event_type raw, so anything decoded
# later can be relabelled retroactively without recollecting.

SNAP_FIELDS = [
    "captured_utc",
    "match_id",
    "slug",
    "start_epoch",
    "score",
    "timer_sec",
    "status",
    "round_info",
    "scope",
    "scope_id",
    "group_id",
    "event_type",
    "parameter",
    "odds",
    "market",
    "market_confidence",
]

SETTLED_FIELDS = SNAP_FIELDS + [
    "home",
    "away",
    "pool",
    "final_score",
    "home_goals",
    "away_goals",
    "total_goals",
    "half1_total",
    "result_1x2",
]


def get(url: str, retries: int = 3) -> bytes | None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except Exception:  # noqa: BLE001 - transient network failure, retry
            if attempt == retries - 1:
                return None
            time.sleep(1.0 * (attempt + 1))
    return None


def champ_slug(name: str) -> str:
    text = name.lower().replace(".", "").replace("+", "-plus")
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def enabled_champs() -> dict[int, dict]:
    with CATALOG.open(encoding="utf-8") as handle:
        data = json.load(handle)
    return {int(k): v for k, v in data["leagues"].items() if v["enabled"]}


def discover() -> dict[str, tuple[str, str]]:
    """Map live match id -> (slug, league name) across every enabled champ."""
    found: dict[str, tuple[str, str]] = {}
    for champ_id, meta in enabled_champs().items():
        page = f"https://helabet.co.tz/en/live/football/{champ_id}-{champ_slug(meta['name'])}"
        body = get(page, retries=2)
        if not body:
            continue
        html = body.decode("utf-8", "replace")
        for gid in set(re.findall(rf"/{champ_id}-[a-z0-9-]+/(\d{{6,}})-", html)):
            found[gid] = (meta["name"], meta["name"])
    return found


def snapshot(match_id: str, slug: str) -> list[dict]:
    """Every priced selection for one live match, as flat rows."""
    url = (
        f"{EVENTS_API}?cfView=3&countEvents=250&fcountry=181&gameId={match_id}"
        "&gr=772&grMode=1&lng=en&marketType=1&ref=237"
    )
    body = get(url)
    if not body:
        return []  # finished matches return an empty body
    try:
        data = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict) or "subGamesForMainGame" not in data:
        return []

    scores = data.get("scores") or {}
    timer = scores.get("timer") or {}
    base = {
        "captured_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "match_id": data.get("id") or match_id,
        "slug": slug,
        "start_epoch": data.get("startTs"),
        "score": scores.get("fullScore"),
        "timer_sec": timer.get("timeSec"),
        "status": scores.get("statusLineStr"),
        "round_info": data.get("dopInfo"),
    }

    # Two scopes come back in one response and they are easy to confuse:
    #   top-level "eventGroups"      -> the full match (total lines around 15)
    #   "subGamesForMainGame[i]"     -> a period, in practice the 1st half
    #                                   (total lines around 7.5)
    # Both are logged and tagged, because reading the wrong one silently
    # compares a half-goal line against full-match results.
    scopes: list[tuple[str, str, list]] = [
        ("match", str(data.get("id") or match_id), data.get("eventGroups") or [])
    ]
    for index, sub in enumerate(data.get("subGamesForMainGame") or []):
        scopes.append(
            (f"sub{index}", str(sub.get("id") or ""), sub.get("eventGroups") or [])
        )

    rows = []
    for scope, scope_id, groups in scopes:
        for group in groups:
            group_id = group.get("groupId")
            for column in group.get("events") or []:
                for event in column:
                    label, confidence = MARKETS.get(
                        (group_id, event.get("type")), ("", "unknown")
                    )
                    rows.append(
                        base
                        | {
                            "scope": scope,
                            "scope_id": scope_id,
                            "group_id": group_id,
                            "event_type": event.get("type"),
                            "parameter": event.get("parameter"),
                            "odds": event.get("cf"),
                            "market": label,
                            "market_confidence": confidence,
                        }
                    )
    return rows


def append_rows(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if new:
            writer.writeheader()
        writer.writerows(rows)


def collect(args: argparse.Namespace) -> int:
    out = Path(args.out)
    deadline = time.time() + args.minutes * 60
    seen: set[tuple] = set()
    if out.exists():
        with out.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                seen.add((row["match_id"], row["timer_sec"], row["score"]))

    polls = 0
    while time.time() < deadline:
        polls += 1
        live = discover()
        batch = []
        for match_id, (slug, _league) in live.items():
            rows = snapshot(match_id, slug)
            if not rows:
                continue
            key = (str(rows[0]["match_id"]), str(rows[0]["timer_sec"]), str(rows[0]["score"]))
            if key in seen:
                continue  # clock and score unchanged since last poll
            seen.add(key)
            batch.extend(rows)

        if batch:
            append_rows(out, SNAP_FIELDS, batch)
        remaining = int(deadline - time.time())
        print(
            f"poll {polls}: {len(live)} live, +{len(batch)} rows, "
            f"{remaining}s left",
            flush=True,
        )
        time.sleep(args.interval)

    print(f"Done. Snapshots in {out}")
    return 0


def fetch_results(day: dt.date) -> dict[int, dict]:
    midnight = dt.datetime.combine(day, dt.time.min, tzinfo=SITE_TZ)
    start = int(midnight.timestamp())
    url = (
        f"{RESULTS_API}?champId={CHAMP_ID}&dateFrom={start}"
        f"&dateTo={start + 86400}&lng=en&ref=237"
    )
    body = get(url)
    if not body:
        return {}
    data = json.loads(body.decode("utf-8"))
    return {item["id"]: item for item in data.get("items") or []}


def settle(args: argparse.Namespace) -> int:
    snaps_path = Path(args.out)
    if not snaps_path.exists():
        print(f"No snapshots at {snaps_path}; run collect first.")
        return 1

    with snaps_path.open(encoding="utf-8") as handle:
        snaps = list(csv.DictReader(handle))

    # Keep the snapshot nearest kickoff for each match: lowest clock, and among
    # those the one taken earliest.
    def sort_key(row: dict) -> tuple:
        try:
            clock = int(row["timer_sec"] or 10**6)
        except ValueError:
            clock = 10**6
        return (clock, row["captured_utc"])

    earliest: dict[str, str] = {}
    for row in sorted(snaps, key=sort_key):
        earliest.setdefault(row["match_id"], row["captured_utc"])

    today = dt.datetime.now(SITE_TZ).date()
    results: dict[int, dict] = {}
    for offset in range(args.days):
        results |= fetch_results(today - dt.timedelta(days=offset))
    print(f"Fetched {len(results)} results across {args.days} day(s)")

    out_rows = []
    matched: set[str] = set()
    for row in snaps:
        if earliest.get(row["match_id"]) != row["captured_utc"]:
            continue
        result = results.get(int(row["match_id"]))
        if not result:
            continue
        match = re.match(r"^\s*(\d+)\s*:\s*(\d+)\s*(?:\((.*)\))?", result.get("score", ""))
        if not match:
            continue
        home_goals, away_goals = int(match.group(1)), int(match.group(2))
        halves = re.findall(r"(\d+)\s*:\s*(\d+)", match.group(3) or "")
        half1 = sum(int(v) for v in halves[0]) if halves else ""
        home, away = result.get("opp1", ""), result.get("opp2", "")
        matched.add(row["match_id"])
        out_rows.append(
            row
            | {
                "home": home,
                "away": away,
                "pool": "suffix" if "(2x2)" in home else "plain",
                "final_score": result.get("score", ""),
                "home_goals": home_goals,
                "away_goals": away_goals,
                "total_goals": home_goals + away_goals,
                "half1_total": half1,
                "result_1x2": "1" if home_goals > away_goals
                else ("2" if away_goals > home_goals else "X"),
            }
        )

    settled_path = snaps_path.with_name("odds_settled.csv")
    if not out_rows:
        print("Nothing settled yet - matches may still be running.")
        return 1
    settled_path.parent.mkdir(parents=True, exist_ok=True)
    with settled_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SETTLED_FIELDS)
        writer.writeheader()
        writer.writerows(out_rows)
    print(f"Settled {len(matched)} matches, {len(out_rows)} selections -> {settled_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)

    default_out = str(Path(__file__).with_name("data") / "odds_snapshots.csv")

    c = sub.add_parser("collect", help="poll live matches and log odds")
    c.add_argument("--minutes", type=float, default=60.0)
    c.add_argument("--interval", type=float, default=20.0, help="seconds between polls")
    c.add_argument("--out", default=default_out)

    s = sub.add_parser("settle", help="join logged odds to results")
    s.add_argument("--out", default=default_out)
    s.add_argument("--days", type=int, default=2, help="days of results to pull")

    args = parser.parse_args()
    return collect(args) if args.mode == "collect" else settle(args)


if __name__ == "__main__":
    raise SystemExit(main())
