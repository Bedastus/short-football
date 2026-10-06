"""Open one isolated browser profile per SokaBet account, tiled side by side.

Why this exists
---------------
A browser stores one session cookie per site, so one profile holds one logged-in
account - open a second account in the same profile and the first is signed out.
Chromium's `--user-data-dir` points the browser at its own profile directory,
giving each window a separate cookie jar and session. It is the same mechanism
behind Chrome's built-in profile switcher, just addressable from a script so
three windows come up tiled and labelled rather than hunted for by hand.

That matters at two-minute match weeks: three tickets have to go on before the
round starts, and the stake differs per stage. Windows that open in a known
order and a known screen position are the difference between placing three
tickets in time and placing two.

Not included: anything that disguises the profiles from one another -
user-agent or fingerprint masking, proxy or IP rotation, automated form filling
or stake placement. This opens labelled browser windows and stops there; what
goes on in them is yours.

    python open_books.py                 # three profiles, tiled, on SokaLigi
    python open_books.py --accounts 2
    python open_books.py --dry-run       # print the commands, launch nothing
    python open_books.py --browser /path/to/chrome
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

PROFILES = Path(__file__).with_name("profiles")
DEFAULT_URL = "https://sokabet.co.tz/SokaLigi"

# Chromium-family browsers only: --user-data-dir is a Chromium flag. Firefox
# uses `-P <name> --no-remote` instead and is handled separately below.
CANDIDATES = {
    "Windows": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    ],
    "Darwin": [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ],
    "Linux": [],
}
LINUX_NAMES = [
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
    "brave-browser", "microsoft-edge", "microsoft-edge-stable",
]


def find_browser(override: str | None) -> str:
    if override:
        if not (Path(override).exists() or shutil.which(override)):
            raise SystemExit(f"No browser at {override!r}")
        return override

    system = platform.system()
    for candidate in CANDIDATES.get(system, []):
        if Path(candidate).exists():
            return candidate
    for name in LINUX_NAMES:
        found = shutil.which(name)
        if found:
            return found
    raise SystemExit(
        "No Chromium-family browser found. Install Chrome, Edge, Brave or\n"
        "Chromium, or point at one with --browser /path/to/browser."
    )


def detect_screen(fallback: tuple[int, int] = (1920, 1080)) -> tuple[int, int]:
    """Actual screen size, so the windows tile without being told the resolution."""
    try:
        import tkinter

        root = tkinter.Tk()
        root.withdraw()
        size = (root.winfo_screenwidth(), root.winfo_screenheight())
        root.destroy()
        return size
    except Exception:  # noqa: BLE001 - no display, or no tkinter; the default is fine
        return fallback


def tile(index: int, count: int, width: int, height: int) -> tuple[int, int, int, int]:
    """Left-to-right tiling across one screen, so window N is always account N.

    Windows land in a fixed order and a fixed place, which is what makes three
    accounts manageable under a two-minute clock: the position is the label.
    """
    pane = max(width // max(count, 1), 480)
    return index * pane, 0, pane, height


def command(browser: str, profile: Path, url: str, geometry, incognito: bool) -> list[str]:
    left, top, pane, height = geometry
    argv = [
        browser,
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        f"--window-position={left},{top}",
        f"--window-size={pane},{height}",
        "--new-window",
    ]
    if incognito:
        # Private windows share no storage even within a profile, but they also
        # forget the login each time; off by default for that reason.
        argv.append("--incognito")
    argv.append(url)
    return argv


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--accounts", type=int, default=3)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--browser", help="path to a Chromium-family browser")
    parser.add_argument("--profiles-dir", default=str(PROFILES))
    parser.add_argument("--names", nargs="*", help="profile names; default soka-1..N")
    parser.add_argument("--screen", default="auto",
                        help="WIDTHxHEIGHT for tiling, or 'auto' to detect")
    parser.add_argument("--incognito", action="store_true",
                        help="private windows; they will not remember logins")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.accounts < 1:
        raise SystemExit("--accounts must be at least 1")
    if args.screen.lower() == "auto":
        width, height = detect_screen()
    else:
        try:
            width, height = (int(v) for v in args.screen.lower().split("x"))
        except ValueError:
            raise SystemExit(f"Bad --screen {args.screen!r}; expected e.g. 1920x1080")

    names = args.names or [f"soka-{i + 1}" for i in range(args.accounts)]
    slips = ["A  Y Y Y", "B  N Y Y", "C  Y Y N"]
    if len(names) != args.accounts:
        raise SystemExit(f"Got {len(names)} names for {args.accounts} accounts")

    browser = find_browser(args.browser)
    root = Path(args.profiles_dir)
    print(f"browser  {browser}")
    print(f"profiles {root}")

    for index, name in enumerate(names):
        profile = root / name
        fresh = not profile.exists()
        if not args.dry_run:
            profile.mkdir(parents=True, exist_ok=True)
        argv = command(browser, profile, args.url,
                       tile(index, args.accounts, width, height), args.incognito)
        state = "new profile, sign in" if fresh else "existing profile"
        carries = f"  carries slip {slips[index]}" if index < len(slips) else ""
        print(f"\n  [{index + 1}] {name}{carries}  ({state})")
        if args.dry_run:
            print("      " + " ".join(argv))
            continue
        try:
            subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as error:
            print(f"      failed to launch: {error}", file=sys.stderr)
            return 1

    if not args.dry_run:
        print(f"\n{len(names)} window(s) opening, left to right in account order:")
        for index, name in enumerate(names[:len(slips)]):
            print(f"  window {index + 1} (leftmost+{index})  {name}  -> slip {slips[index]}")
        print("\nEach profile keeps its own session. Sign a DIFFERENT account into each,")
        print("once - they are remembered, so later runs open already signed in.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
