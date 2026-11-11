"""Daily Hudl InStat pull (Canada Basketball subscription, internal use).

Opens Google Chrome with its own profile in data/instat_profile/ (not committed). When Hudl asks for a
sign-in, the script signs in with HUDL_EMAIL and HUDL_PASSWORD from .env (not committed; create it
yourself, see README). The daily run then opens each player's Games and Field goals pages like a person
would (a few seconds each, one player at a time) and records the data the InStat app loads.
Output: data/instat/2026-27.json (format in instat.py). If the session has expired, it says so and
leaves the previous file in place; run --login again.
"""
import json
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

import instat

ROOT = Path(__file__).parent
PROFILE = ROOT / "data" / "instat_profile"
BASE = "https://app.hudl.com/instat/basketball"
SEASON_ID = 38  # InStat id for 2026-27
STAT_IDS = [3, 4, 5, 7, 8, 10, 11, 13, 14, 15, 16, 17, 18, 19, 20, 165]  # PT FG+ FG 3PT+ 3PT FT+ FT OREB DREB REB AST STL BLK TOV F +/-
PAUSE = 4  # seconds on each page


class NeedLogin(Exception):
    pass


def env():
    """HUDL_EMAIL / HUDL_PASSWORD from the environment or the git-ignored .env file."""
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() and v and not k.startswith("#"):
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return os.environ.get("HUDL_EMAIL"), os.environ.get("HUDL_PASSWORD")


def sign_in(page):
    """Fill Hudl's two-step sign-in form (email, then password). Returns True when back in InStat."""
    email, password = env()
    if not (email and password):
        print("  InStat: no HUDL_EMAIL / HUDL_PASSWORD in .env")
        return False
    for _ in range(3):
        if "identity.hudl.com" not in page.url:
            break
        user = page.locator("input[name=username], input[type=email]")
        if user.count() and user.first.is_visible() and not page.locator("input[type=password]").count():
            user.first.fill(email)
            page.locator("button[type=submit][name=action], button[type=submit]").first.click()
            page.wait_for_load_state("networkidle")
        pw = page.locator("input[type=password]")
        if pw.count() and pw.first.is_visible():
            pw.first.fill(password)
            page.locator("button[type=submit][name=action], button[type=submit]").first.click()
            page.wait_for_load_state("networkidle")
        time.sleep(3)
    if page.locator("iframe[src*=captcha], iframe[title*=challenge]").count():
        print("  InStat: Hudl is showing a CAPTCHA - sign in once with --login")
    return signed_in(page)


def signed_in(page):
    return "/instat/basketball" in page.url and not page.locator("input[type=password]").count()


def pack(pid, caps):
    ms, tours, stat, shots = {}, {}, {}, {}
    for body, text in caps:
        try:
            b, d = json.loads(body or "{}"), json.loads(text)["data"][0]
        except (ValueError, KeyError, IndexError, TypeError):
            continue
        proc, pr = b.get("proc"), b.get("params") or {}
        if pr.get("_p_player_id") != pid or proc not in d:
            continue
        v = d[proc]
        if proc == "scout_uni_advanced_matches_list":
            tours.update({t["id"]: t["name_eng"] for t in v.get("tournaments") or []})
            ms.update({m["id"]: m for m in v.get("matches") or []})
        elif proc == "scout_uni_player_matches_stat":
            stat.update({s["match_id"]: s for s in v or []})
        elif proc == "scout_map_shoot":
            for mid, evs in (v.get("events") or {}).items():
                shots[mid] = [[round(e["x"], 1), round(e["y"], 1), int("+" in e["shot"]), int(e["shot"][0] == "3")]
                              for e in evs if e.get("player") == pid and e.get("type") == 1 and not e["shot"].endswith("F")]
    games = []
    for m in ms.values():
        if m.get("season_id") != SEASON_ID:
            continue
        s = stat.get(m["id"])
        vals = {x["p"]: x["v"] for x in s["params"] if x.get("o") == 0} if s else {}
        games.append([m["id"], m["date"][:10], tours.get(m["tournament_id"], str(m["tournament_id"])),
                      m["team"]["name_eng"], m["team"]["score"], m["opp_team"]["name_eng"], m["opp_team"]["score"],
                      m["home"], round(s["time"]["total"]) if s else None,
                      *([vals.get(i, 0) for i in STAT_IDS] if s else []), int(str(m["id"]) in shots)])
    keep = {str(g[0]) for g in games}
    return {"g": games, "s": {k: v for k, v in shots.items() if k in keep}}


def login():
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(PROFILE, channel="chrome", headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(BASE)
        print("Sign in to Hudl in the Chrome window that just opened (waiting up to 5 minutes)...")
        for _ in range(150):
            time.sleep(2)
            if signed_in(page):
                print("Signed in. The daily run will use this session.")
                break
        else:
            print("Not signed in; run --login again.")
        ctx.close()


def fetch(ids, headless=True):
    out = instat.load()
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(PROFILE, channel="chrome", headless=headless,
                                                   viewport={"width": 1600, "height": 1000})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        pending = []
        page.on("response", lambda r: pending.append(r) if "instatscout.com/data" in r.url else None)

        def visit(url):
            page.goto(url)
            time.sleep(PAUSE)
            for _ in range(5):  # the first visit can pass through Hudl's silent sign-in redirect
                if signed_in(page):
                    return
                time.sleep(2)
            if not (sign_in(page) and (page.goto(url) or True) and (time.sleep(PAUSE) or signed_in(page))):
                raise NeedLogin

        def drain():
            caps = []
            for r in pending:
                try:
                    caps.append((r.request.post_data, r.text()))
                except Exception:
                    pass
            pending.clear()
            return caps

        try:
            for pid in ids:
                caps = []
                visit(f"{BASE}/players/{pid}/matches")
                for _ in range(4):  # the Games table loads box scores in batches as it scrolls
                    page.mouse.move(800, 600)
                    page.mouse.wheel(0, 4000)
                    page.keyboard.press("End")
                    time.sleep(1.5)
                caps += drain()
                visit(f"{BASE}/players/{pid}/fieldgoals")
                # shot range: "All games of current season" (the app remembers it after the first time).
                # Clicked from script, not with the mouse, because Hudl's side menu can cover the dropdown.
                opener = page.get_by_text("Last 10 games", exact=True)
                if opener.count():
                    try:
                        opener.first.dispatch_event("click")
                        time.sleep(1)
                        page.get_by_text("All games of current season", exact=True).first.dispatch_event("click")
                        time.sleep(PAUSE)
                    except Exception:
                        print("  InStat: could not pick the season range; shots cover the last 10 games")
                caps += drain()
                rec = pack(pid, caps)
                if rec["g"]:
                    out[str(pid)] = rec
                nobox = [g[1] for g in rec["g"] if len(g) < 26]
                print(f"  InStat {pid}: {len(rec['g'])} games, {sum(map(len, rec['s'].values()))} shots"
                      + (f", no box score yet: {', '.join(sorted(nobox))}" if nobox else ""), flush=True)
        except NeedLogin:
            print("  InStat: could not sign in - check .env or run --login; keeping previous data")
            ctx.close()
            return False
        ctx.close()
    instat.FILE.parent.mkdir(parents=True, exist_ok=True)
    instat.FILE.write_text(json.dumps(out, separators=(",", ":")))
    return True


if __name__ == "__main__":
    if "--login" in sys.argv:
        login()
    else:
        roster = json.loads((ROOT / "players.json").read_text())
        ids = [p["instat_id"] for p in roster if p.get("instat_id")]
        # Hudl rejects windowless Chrome, so a window opens for the ~2 minutes this takes
        sys.exit(0 if fetch(ids, headless="--headless" in sys.argv) else 1)
