"""Eurobasket.com club game logs (Canada Basketball subscription).

Fetch (daily, on the Mac): opens Google Chrome with its own profile in data/eurobasket_profile/ (not
committed), signs in at the Eurobasket login page with EUROBASKET_EMAIL / EUROBASKET_PASSWORD from .env
only when the saved session has ended, then opens each player's page a few seconds apart and reads the
game-by-game tables. It stops, keeping the previous data, if Eurobasket shows its device-limit or
verification page, or a Cloudflare challenge that does not clear by itself. It never clicks through those.

Output: data/eurobasket_stats/2026-27.json, parsed stats only (no saved pages):
{eurobasket_id: [[date, competition, team, opp, team_pts, opp_pts, min, pts, 2pm, 2pa, 3pm, 3pa, ftm, fta,
                  oreb, dreb, reb, ast, pf, blk, stl, tov], ...]}
Usage: python eurobasket.py            daily fetch
       python eurobasket.py --login    open the window to sign in / pass a verification page by hand
"""
import datetime as dt
import io
import json
import os
import random
import re
import sys
import time
from pathlib import Path

import overseas

ROOT = Path(__file__).parent
PROFILE = ROOT / "data" / "eurobasket_profile"
FILE = ROOT / "data" / "eurobasket_stats" / f"{overseas.SEASON}.json"
LOGIN = "https://www.eurobasket.com/news_system/login.aspx?"
SEASON = "2026-2027"
PAUSE = (8, 15)  # random seconds between player pages, so requests stay slow and spaced out


def rest(lo=2, hi=5):
    time.sleep(random.uniform(lo, hi))
COMPS = {"Euroleague": "EuroLeague Women", "Eurocup": "EuroCup Women", "Lithuania-LMKL": "Lithuania LMKL",
         "Baltic-WBBL": "Baltic WBBL", "WBBL": "Baltic WBBL", "Sweden-Damligan": "Sweden Damligan", "Germany-DBBL": "Germany DBBL",
         "Spain-Liga Femenina": "Spain Liga Femenina", "Spain-LF Challenge": "Spain LF Challenge",
         "France-LFB": "France LFB", "Czech Republic-ZBL": "Czech ZBL", "Turkey-KBSL": "Turkey KBSL"}


class Stop(Exception):
    pass


def creds():
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip().startswith("EUROBASKET_") and v:
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return os.environ.get("EUROBASKET_EMAIL"), os.environ.get("EUROBASKET_PASSWORD")


def wait_cloudflare(page, secs=180):
    """Cloudflare's check often clears by itself. When it shows the "Verify you are human" box instead,
    the script waits for a person to tick it in the window (up to 3 minutes) and never ticks it itself."""
    human = False
    for _ in range(secs // 4):
        if "Just a moment" not in page.title():
            return
        # the "Verify you are human" checkbox lives in a Cloudflare frame; a person has to click it
        if any("challenges.cloudflare.com" in f.url for f in page.frames):
            human = True
        time.sleep(4)
    raise Stop("Cloudflare's 'Verify you are human' box was not ticked" if human else "Cloudflare check did not clear")


def sign_in(page):
    email, pw = creds()
    if not (email and pw):
        raise Stop("no EUROBASKET_EMAIL / EUROBASKET_PASSWORD in .env")
    if "login.aspx" not in page.url:
        page.goto(LOGIN, timeout=60000, wait_until="domcontentloaded")
        wait_cloudflare(page)
    rest()
    page.fill("#Text1", email)
    rest(1, 3)
    page.fill("#Password1", pw)
    page.click("input[type=submit][name=B1]")
    time.sleep(15)  # Eurobasket's login takes a while, like in a normal browser
    if "erroruser" in page.url:
        raise Stop("Eurobasket says the login is in use on too many computers")
    if "verifikacija" in page.url.lower():
        raise Stop("Eurobasket wants a verification click; run `python eurobasket.py --login` and do it by hand")


def parse(html):
    """Game rows for the current season from a logged-in player page."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    rows, seen, comp = [], set(), None
    for el in soup.find_all("table"):
        head = el.find_previous(string=re.compile(r"Season:\s*\d{4}-\d{4}\s*\("))
        m = re.search(r"Season:\s*(\d{4}-\d{4})\s*\((.+?)\)", head or "")
        if not m or m.group(1) != SEASON:
            continue
        comp = COMPS.get(m.group(2).strip(), m.group(2).strip().replace("-", " "))
        trs = el.find_all("tr")
        cells = [[c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])] for tr in trs]
        hdr = next((c for c in cells if c[:2] == ["Date", "Team"]), None)
        if not hdr:
            continue
        ix = {h: i for i, h in enumerate(hdr)}
        for c in cells:
            if len(c) != len(hdr) or not re.match(r"\d{1,2}/\d{1,2}/\d{4}$", c[0]):
                continue
            mo, d, y = map(int, c[0].split("/"))
            date = dt.date(y, mo, d).isoformat()
            if (date, comp) in seen:
                continue  # the page repeats some tables
            seen.add((date, comp))
            num = lambda k: int(re.sub(r"[^\d-]", "", c[ix[k]]) or 0) if k in ix else 0
            ma = lambda k: [int(x) for x in c[ix[k]].split("-")] if k in ix and "-" in c[ix[k]] else [0, 0]
            tp, op = (int(x) for x in c[ix["Result"]].split("-")) if "-" in c[ix["Result"]] else (0, 0)
            (m2, a2), (m3, a3), (fm, fa) = ma("2FGP"), ma("3FGP"), ma("FT")
            rows.append([date, comp, c[ix["Team"]], c[ix["Against Team"]], tp, op, num("MIN"), num("PTS"),
                         m2, a2, m3, a3, fm, fa, num("RO"), num("RD"), num("RT"), num("AS"), num("PF"),
                         num("BS"), num("ST"), num("TO")])
    return sorted(rows, reverse=True)


def fetch(players):
    from playwright.sync_api import sync_playwright
    out = load()
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(PROFILE, channel="chrome", headless=False, ignore_default_args=["--no-sandbox"],
                                                   viewport={"width": 1400, "height": 950})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            # stay signed in between runs: logging in again each day makes Eurobasket ask for a verification
            # click, so the script signs in (Cohen Macdonald's login steps) only when the session has ended
            signed_in = False
            skipped = []
            for pl in players:
              try:
                page.goto(pl["eurobasket_url"], timeout=60000, wait_until="domcontentloaded")
                wait_cloudflare(page)
                rest()
                if page.locator("text=ONLY FOR SUBSCRIBERS").count():
                    if signed_in:
                        raise Stop("still not signed in after logging in")
                    sign_in(page)
                    signed_in = True
                    page.goto(pl["eurobasket_url"], timeout=60000, wait_until="domcontentloaded")
                    wait_cloudflare(page)
                    rest()
                rows = parse(page.content())
                eid = pl["eurobasket_url"].rstrip("/").split("/")[-1]
                if rows:
                    out[eid] = rows
                print(f"  Eurobasket {pl['name']}: {len(rows)} games this season", flush=True)
                rest(*PAUSE)
              except Stop:
                raise
              except Exception as e:  # a slow or broken page: skip this player, keep her previous data
                skipped.append(pl["name"])
                print(f"  Eurobasket {pl['name']}: skipped ({type(e).__name__}; page: {page.title()!r} {page.url})", flush=True)
                rest(*PAUSE)
        except Stop as e:
            print(f"  Eurobasket: {e}; keeping previous data for the rest", flush=True)
            ctx.close()
            save(out)
            status(False, str(e))
            return False
        ctx.close()
    save(out)
    if skipped:
        status(False, f"{len(players) - len(skipped)} of {len(players)} updated; page did not load for {', '.join(skipped)}")
        return False
    status(True, f"{len(players)} players updated")
    return True


def save(out):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(out, separators=(",", ":")))


def status(ok, msg):
    """data/eurobasket_stats/status.json: read by the daily email to say whether Eurobasket updated."""
    (FILE.parent / "status.json").write_text(json.dumps(
        {"ok": ok, "at": dt.datetime.now().isoformat(timespec="minutes"), "msg": msg}))


def login():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(PROFILE, channel="chrome", headless=False, ignore_default_args=["--no-sandbox"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(LOGIN)
        print("Sign in / finish any verification in the window (closes after 5 minutes or when you close it).")
        try:
            page.wait_for_event("close", timeout=300000)
        except Exception:
            pass
        ctx.close()


def load():
    return json.loads(FILE.read_text()) if FILE.exists() else {}


def player(data, url):
    """overseas.game() rows for one player, newest first."""
    if not url:
        return []
    games = []
    for (d, comp, team, opp, tp, op, mins, pts, m2, a2, m3, a3, fm, fa,
         oreb, dreb, reb, ast, pf, blk, stl, tov) in data.get(url.rstrip("/").split("/")[-1], []):
        games.append(overseas.game(d, f"{comp}|{overseas.SEASON}", comp, team, opp, None, tp, op, None,
                                   min=mins, pts=pts, reb=reb, oreb=oreb, ast=ast, stl=stl, blk=blk, tov=tov, pf=pf,
                                   fgm=m2 + m3, fga=a2 + a3, tpm=m3, tpa=a3, ftm=fm, fta=fa))
        games[-1]["ha"] = ""  # Eurobasket's game log doesn't say home or away
    return games


if __name__ == "__main__":
    if "--login" in sys.argv:
        login()
    else:
        roster = json.loads((ROOT / "players.json").read_text())
        sys.exit(0 if fetch([p for p in roster if p.get("eurobasket_url")]) else 1)
