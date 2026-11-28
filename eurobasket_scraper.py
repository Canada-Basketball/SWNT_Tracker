"""
Stealth Playwright scraper for Eurobasket (personal use).

Setup:
    pip install playwright playwright-stealth pandas lxml
    playwright install chromium

Usage:
    python eurobasket_scraper.py login              # opens a browser; log in by hand, then close it
    python eurobasket_scraper.py fetch urls.txt     # fetch each URL (one per line), cache raw HTML
    python eurobasket_scraper.py parse              # pull every HTML table from the cache into CSVs

Design:
  - Persistent browser profile: cookies and your login survive between runs, so the
    site sees one returning visitor instead of a fresh bot every time.
  - Stealth patches (navigator.webdriver, plugins, WebGL, etc.) via playwright-stealth.
  - Fingerprint kept consistent with your real machine (platform, locale, timezone).
  - Slow, human-ish pacing: random delays, scrolling, long breaks every N pages.
  - Caching: a page is never fetched twice. Delete the file in cache/ to refetch.
  - Stops on CAPTCHA / block pages rather than hammering the site.

Files live in data/eurobasket_scraper/ (profile/, cache/, tables/), which is git-ignored:
the profile holds your login cookies and the cache holds subscription pages.
"""

import random
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from playwright_stealth import Stealth

# ---------- config ----------
BASE_DIR = Path(__file__).parent / "data" / "eurobasket_scraper"
PROFILE_DIR = BASE_DIR / "profile"
CACHE_DIR = BASE_DIR / "cache"
OUT_DIR = BASE_DIR / "tables"

HEADLESS = False                 # headful is much harder to detect; keep False if you can
DELAY_RANGE = (6.0, 14.0)        # seconds between pages
LONG_BREAK_EVERY = 25            # pages
LONG_BREAK_RANGE = (90, 240)     # seconds
MAX_RETRIES = 3

BLOCK_MARKERS = [
    "captcha", "are you a robot", "access denied", "unusual traffic",
    "cf-challenge", "just a moment", "verify you are human",
    "performing security verification", "challenge-platform", "cf-turnstile",
]

# Match navigator.platform to the real OS so the fingerprint isn't contradictory
PLATFORM = {"darwin": "MacIntel", "win32": "Win32"}.get(sys.platform, "Linux x86_64")


def make_stealth() -> Stealth:
    return Stealth(
        navigator_platform_override=PLATFORM,
        navigator_languages_override=("en-CA", "en"),
    )


def launch(p):
    """Persistent context = same cookies/localStorage/history every run."""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return p.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=HEADLESS,
        channel="chrome" if _has_chrome(p) else None,  # real Chrome > bundled Chromium
        viewport={"width": 1440, "height": 900},
        locale="en-CA",
        timezone_id="America/Toronto",
        args=["--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"],
    )


def _has_chrome(p) -> bool:
    try:
        b = p.chromium.launch(channel="chrome", headless=True)
        b.close()
        return True
    except Exception:
        return False


def human_pause(lo=None, hi=None):
    lo, hi = lo or DELAY_RANGE[0], hi or DELAY_RANGE[1]
    time.sleep(random.uniform(lo, hi))


def human_browse(page):
    """Scroll and move the mouse a bit, like a person reading the page."""
    for _ in range(random.randint(2, 5)):
        page.mouse.move(random.randint(100, 1300), random.randint(100, 800), steps=random.randint(8, 25))
        page.mouse.wheel(0, random.randint(250, 700))
        time.sleep(random.uniform(0.4, 1.5))
    if random.random() < 0.3:
        page.mouse.wheel(0, -random.randint(200, 500))
        time.sleep(random.uniform(0.3, 1.0))


def looks_blocked(html: str, status: int | None) -> bool:
    if status in (403, 429, 503):
        return True
    low = html.lower()
    return any(m in low for m in BLOCK_MARKERS) and len(low) < 50_000


def cache_path(url: str) -> Path:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", url.split("://", 1)[-1]).strip("_")[:180]
    return CACHE_DIR / f"{slug}.html"


# ---------- commands ----------
def cmd_login():
    with make_stealth().use_sync(sync_playwright()) as p:
        ctx = launch(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.eurobasket.com/", wait_until="domcontentloaded")
        print("Log in in the browser window, browse a page or two, then close the window.")
        try:
            page.wait_for_event("close", timeout=0)
        except Exception:
            pass
        ctx.close()
    print(f"Session saved to {PROFILE_DIR}/")


def cmd_fetch(url_file: str):
    urls = [u.strip() for u in Path(url_file).read_text().splitlines() if u.strip() and not u.startswith("#")]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    todo = [u for u in urls if not cache_path(u).exists()]
    print(f"{len(urls)} URLs, {len(urls) - len(todo)} cached, {len(todo)} to fetch")

    with make_stealth().use_sync(sync_playwright()) as p:
        ctx = launch(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        for i, url in enumerate(todo, 1):
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    resp = page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=10_000)
                    except PWTimeout:
                        pass
                    human_browse(page)
                    html = page.content()
                    status = resp.status if resp else None

                    if looks_blocked(html, status):
                        print(f"\n[!] Blocked or challenged at {url} (status {status}).")
                        if not HEADLESS:
                            input("    Solve it in the browser if you can, then press Enter (Ctrl+C to quit)... ")
                            try:
                                page.wait_for_load_state("networkidle", timeout=15_000)
                            except PWTimeout:
                                pass
                            html = page.content()
                            if looks_blocked(html, None):
                                print("    Still blocked. Stopping: wait a few hours before retrying.")
                                ctx.close()
                                return
                        else:
                            print("    Stopping. Rerun later with HEADLESS = False.")
                            ctx.close()
                            return

                    cache_path(url).write_text(html, encoding="utf-8")
                    print(f"[{i}/{len(todo)}] saved {url}")
                    break
                except PWTimeout:
                    wait = 20 * attempt + random.uniform(0, 10)
                    print(f"  timeout ({attempt}/{MAX_RETRIES}), retrying in {wait:.0f}s")
                    time.sleep(wait)
            else:
                print(f"  gave up on {url}")

            if i % LONG_BREAK_EVERY == 0:
                b = random.uniform(*LONG_BREAK_RANGE)
                print(f"  long break {b:.0f}s")
                time.sleep(b)
            else:
                human_pause()

        ctx.close()


def cmd_parse():
    import pandas as pd
    from io import StringIO

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in sorted(CACHE_DIR.glob("*.html")):
        try:
            tables = pd.read_html(StringIO(f.read_text(encoding="utf-8")))
        except ValueError:
            continue  # no tables on this page
        for j, df in enumerate(tables):
            if df.shape[0] < 2 or df.shape[1] < 3:
                continue  # skip layout/nav tables
            df.to_csv(OUT_DIR / f"{f.stem}__t{j}.csv", index=False)
            n += 1
    print(f"Wrote {n} tables to {OUT_DIR}/")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in {"login", "fetch", "parse"}:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "login":
        cmd_login()
    elif cmd == "fetch":
        if len(sys.argv) < 3:
            sys.exit("usage: python eurobasket_scraper.py fetch urls.txt")
        cmd_fetch(sys.argv[2])
    else:
        cmd_parse()
