"""Overseas club games for the Canada pool.

Sources (all public; finished games are cached under data/raw/overseas):
  * FIBA GDAP (digital-api.fiba.basketball) - EuroLeague / EuroCup / SuperCup Women.
    Every Canadian on a roster is picked up, so WNBA players who go to Europe appear too.
  * Genius LiveStats data.json - France LFB (org FFBB) and Romania LNBF (org FRB).
  * FEB (baloncestoenvivo.feb.es) - Spain Liga Femenina Endesa and LF-2.
  * ZBL (zbl.basketball) - Czech women's league, server-rendered box scores.
  * TBF (miniappapi.tbf.org.tr) - Turkey KBSL.
Same approach as SportsDataverse wehoop's fiba_gdap_*, genius_*, feb_* and tbf_* wrappers.

Each game is returned in the page's game schema plus `s` (season key) and `comp`.
"""
import datetime as dt
import html as htmlmod
import json
import re
import time
import unicodedata
from pathlib import Path

import requests

CACHE = Path(__file__).parent / "data" / "raw" / "overseas"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
S = requests.Session()
S.headers["User-Agent"] = UA
SEASON = "2026-27"
TODAY = dt.date.today()
_last = {}


def _get(url, host_gap=0.6, **kw):
    host = url.split("/")[2]
    wait = host_gap - (time.time() - _last.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    r = S.get(url, timeout=40, **kw)
    _last[host] = time.time()
    return r


def _cached(name, fetch):
    """Cache finished-game payloads forever; `fetch` returns (text, finished)."""
    p = CACHE / name
    if p.exists():
        return p.read_text()
    text, finished = fetch()
    if finished and text:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return text


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]+", " ", s).strip()


def tidy(name):
    name = " ".join(str(name or "").split())
    return name.title() if name.isupper() else name


def game(d, s, comp, team, opp, home, team_pts, opp_pts, st, **stats):
    team, opp = tidy(team), tidy(opp)
    g = {"d": d, "s": s, "comp": comp, "team": team, "po": False, "opp": opp, "oppab": "",
         "ha": "vs" if home else "@", "wl": "W" if team_pts > opp_pts else "L",
         "sc": f"{team_pts}-{opp_pts}", "st": None if st is None else bool(st)}
    for k in ("min", "pts", "reb", "oreb", "ast", "stl", "blk", "tov", "pf",
              "fgm", "fga", "tpm", "tpa", "ftm", "fta"):
        g[k] = int(round(float(stats.get(k) or 0)))
    return g


def mmss(v):
    if v in (None, ""):
        return 0
    if isinstance(v, (int, float)):
        return v / 60 if v > 100 else v
    parts = str(v).split(":")
    return int(parts[0]) + (int(parts[1]) / 60 if len(parts) > 1 and parts[1].isdigit() else 0)


# --------------------------------------------------------------------------- FIBA
FIBA = "https://digital-api.fiba.basketball/hapi"
META = {}  # pool name -> {"jersey", "pos"} from FIBA rosters
FIBA_WOMEN_CLUB = {209127: "EuroLeague Women", 209128: "EuroCup Women", 209131: "SuperCup Women"}


def fiba_games(pool):
    page = _get("https://www.fiba.basketball/en").text
    m = re.search(r'NEXT_CLIENT_APIM_SUBSCRIPTION_KEY\\*"\s*:\s*\\*"([0-9a-f]{32})', page)
    if not m:
        print("  FIBA: key not found, skipping")
        return {}
    H = {"Ocp-Apim-Subscription-Key": m.group(1)}
    fj = lambda method, **q: _get(f"{FIBA}/{method}", headers=H, params=q).json()

    meta = {}
    for g in fj("getgdapgamesbetweentwodates", dateFrom="2026-09-01",
                dateTo=(TODAY + dt.timedelta(days=1)).isoformat()):
        meta[g["gameId"]] = g
    teams = {(g["competition"]["competitionId"], t["teamId"])
             for g in meta.values() if g["competition"]["competitionId"] in FIBA_WOMEN_CLUB
             for t in (g["teamA"], g["teamB"])}
    # Canadians on any women's club roster, matched to the pool by surname
    found = {}
    for comp, tid in sorted(teams):
        for p in fj("getgdapcompetitionteamlatestrosterbyteamid", gdapTeamId=tid).get("players", []):
            if p.get("nationality") != "CAN":
                continue
            name = pool.match(f"{p['firstName']} {p['lastName']}")
            if name:
                found.setdefault(name, set()).add((p["personId"], comp))
                META.setdefault(name, {}).update(
                    jersey=str(p.get("uniformNumber") or ""),
                    pos=next((v for k, v in (("Guard", "G"), ("Forward", "F"), ("Center", "C"))
                              if k in (p.get("position") or "")), ""))
    out = {}
    for name, pairs in found.items():
        for pid, comp in sorted(pairs):
            body = fj("getgdapplayergamestatisticsbyplayerid", gdapPlayerId=pid, gdapCompetitionId=comp)
            for r in body.get("gameStatistics") or []:
                m_ = meta.get(r["gameId"])
                if not m_ or m_.get("statusCode") not in ("VALID", "FINAL", "COMPLETE", "FINISHED", None) and not m_.get("teamAScore"):
                    continue
                home = m_["teamA"]["teamId"] == r["teamId"]
                tp, op = (m_["teamAScore"], m_["teamBScore"]) if home else (m_["teamBScore"], m_["teamAScore"])
                if tp is None or op is None:
                    continue
                out.setdefault(name, []).append(game(
                    m_["gameDateTime"][:10], f"{FIBA_WOMEN_CLUB[comp]}|{SEASON}", FIBA_WOMEN_CLUB[comp],
                    r["teamName"], r["versusTeamName"], home, int(tp), int(op), None,
                    min=(r.get("playDurationInSeconds") or 0) / 60, pts=r["points"], reb=r["rebounds"],
                    oreb=r["offensiveRebounds"], ast=r["assists"], stl=r["steals"], blk=r["blockedShots"],
                    tov=r["turnovers"], pf=r["personalFouls"], fgm=r["fieldGoalsMade"],
                    fga=r["fieldGoalsAttempted"], tpm=r["threePointsMade"], tpa=r["threePointsAttempted"],
                    ftm=r["freeThrowsMade"], fta=r["freeThrowsAttempted"]))
    print(f"  FIBA: {sum(map(len, out.values()))} games for {', '.join(sorted(out)) or 'nobody'}")
    return out


# --------------------------------------------------------------------------- Genius LiveStats
GENIUS = "https://fibalivestats.dcd.shared.geniussports.com"
COURT_L, COURT_W, RIM = 28.0, 15.0, 1.575  # metres (FIBA court)


def genius_data(match_id):
    def fetch():
        r = _get(f"{GENIUS}/data/{match_id}/data.json", host_gap=1.0)
        if r.status_code != 200:
            return "", False
        d = r.json()
        done = str(d.get("period")) and d.get("clock") in ("00:00", "0:00", "00:00:00")
        return r.text, bool(done)
    t = _cached(f"genius_{match_id}.json", fetch)
    return json.loads(t) if t else None


def genius_player_games(fixtures, comp, season_key, surname, club):
    """fixtures: [(match_id, date)]; returns (games, shots) for the player whose family name matches."""
    games, shots = [], []
    for mid, date in fixtures:
        d = genius_data(mid)
        if not d:
            continue
        for tno, t in d["tm"].items():
            if club not in norm(t.get("name")):
                continue
            other = d["tm"]["2" if tno == "1" else "1"]
            for pno, p in t["pl"].items():
                if surname not in norm(p.get("familyName")).split():
                    continue
                if mmss(p.get("sMinutes")) <= 0:
                    continue
                games.append(game(date, season_key, comp, t["name"], other["name"], tno == "1",
                                  int(t.get("full_score") or t.get("score")),
                                  int(other.get("full_score") or other.get("score")), p.get("starter"),
                                  min=mmss(p.get("sMinutes")), pts=p["sPoints"], reb=p["sReboundsTotal"],
                                  oreb=p["sReboundsOffensive"], ast=p["sAssists"], stl=p["sSteals"],
                                  blk=p["sBlocks"], tov=p["sTurnovers"], pf=p["sFoulsPersonal"],
                                  fgm=p["sFieldGoalsMade"], fga=p["sFieldGoalsAttempted"],
                                  tpm=p["sThreePointersMade"], tpa=p["sThreePointersAttempted"],
                                  ftm=p["sFreeThrowsMade"], fta=p["sFreeThrowsAttempted"]))
                for sh in t.get("shot", []):
                    if str(sh.get("p")) != str(pno):
                        continue
                    x, y = float(sh["x"]), float(sh["y"])
                    if x > 50:  # attack the left basket so every shot is on one half
                        x, y = 100 - x, 100 - y
                    along = x / 100 * COURT_L - RIM          # metres from the rim line
                    across = y / 100 * COURT_W               # metres from the sideline
                    shots.append([round(across / COURT_W * 50, 1), round(along * 3.281, 1), int(sh.get("r", 0))])
    return games, shots


def lfb_fixtures(club_word):
    page = _get("https://basketlfb.com/laboulangerewonderligue/saison-reguliere").text
    rows = re.findall(r'<span class="date">\s*(\d\d)/(\d\d)\s+[\d:]+\s*</span>.*?u/FFBB/(\d+)" title="([^"]+)"', page, re.S)
    out = []
    for dd, mm, mid, title in rows:
        y = 2026 if int(mm) >= 8 else 2027
        d = dt.date(y, int(mm), int(dd))
        if club_word in norm(htmlmod.unescape(title)) and d <= TODAY:
            out.append((mid, d.isoformat()))
    return out


def hosted_fixtures(org, comp_id, club_word):
    page = _get(f"https://hosted.dcd.shared.geniussports.com/{org}/en/competition/{comp_id}/schedule").text
    out = []
    for block in re.split(r'(?=<div class="match-wrap )', page)[1:]:
        if "STATUS_COMPLETE" not in block[:80]:
            continue
        mid = re.search(r'extfix_(\d+)', block)
        when = re.search(r'match-time"><h6>[^<]*</h6><span>([^<]+)</span>', block)
        names = " ".join(re.findall(r'team-name-full">([^<]+)<', block))
        if mid and when and club_word in norm(names):
            d = dt.datetime.strptime(when.group(1).split(",")[0] + "," + when.group(1).split(",")[1], "%b %d, %Y").date()
            out.append((mid.group(1), d.isoformat()))
    return out


# --------------------------------------------------------------------------- FEB (Spain)
FEB = "https://baloncestoenvivo.feb.es"


def feb_games(group, comp, players):
    """players: {pool_name: 'S. HILL'} as FEB prints names. Scans every played game of the group."""
    cal = _get(f"{FEB}/calendario.aspx?g={group}&t=2026").text
    # played games show a score as the link text; the exact date comes from each box score header
    played = sorted(set(re.findall(r"Partido\.aspx\?p=(\d+)['\"]>\s*\d+-\d+\s*<", cal)))
    if not played:
        return {}
    token = None
    out = {}
    for pid in played:
        def fetch():
            nonlocal token
            if token is None:
                pg = _get(f"{FEB}/Partido.aspx?p={pid}").text
                token = re.search(r'id="_ctl0_token" value="([^"]+)"', pg).group(1)
            r = _get(f"https://intrafeb.feb.es/LiveStats.API/api/v1/BoxScore/{pid}",
                     headers={"Authorization": f"Bearer {token}", "Origin": FEB, "Referer": FEB + "/"})
            if r.status_code != 200:
                return "", False
            return r.text, r.json().get("HEADER", {}).get("statusText") == "FINISHED"
        t = _cached(f"feb_{pid}.json", fetch)
        if not t:
            continue
        d = json.loads(t)
        st = re.match(r"(\d\d)-(\d\d)-(\d{4})", d["HEADER"].get("starttime") or "")
        if not st:
            continue
        date = f"{st.group(3)}-{st.group(2)}-{st.group(1)}"
        teams = d["BOXSCORE"]["TEAM"]
        tot = [int(d["HEADER"]["TEAM"][i]["pts"]) for i in (0, 1)]
        for i, team in enumerate(teams):
            for p in team.get("PLAYER", []):
                for pool_name, feb_name in players.items():
                    if norm(p.get("name")) == norm(feb_name) and mmss(p.get("minFormatted")) > 0:
                        out.setdefault(pool_name, []).append(game(
                            date, f"{comp}|{SEASON}", comp, team["name"].title(), teams[1 - i]["name"].title(),
                            i == 0, tot[i], tot[1 - i], None,
                            min=mmss(p.get("minFormatted")), pts=p.get("pts"), reb=p.get("rt"), oreb=p.get("ro"),
                            ast=p.get("assist"), stl=p.get("st"), blk=p.get("bs"), tov=p.get("to"),
                            pf=p.get("pf"), fgm=p.get("fgm"), fga=p.get("fga"), tpm=p.get("p3m"),
                            tpa=p.get("p3a"), ftm=p.get("p1m"), fta=p.get("p1a")))
    return out


# --------------------------------------------------------------------------- ZBL (Czechia)
ZBL = "https://zbl.basketball"


def _text(html):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S)
    t = re.sub(r"<[^>]+>", "|", t)
    t = htmlmod.unescape(re.sub(r"\s+", " ", t))
    return re.sub(r"(\|\s*)+", "|", t)


def zbl_games(player_id, surname, team_slug=None):
    page = _get(f"{ZBL}/hrac/{player_id}").text
    if team_slug:  # the team page lists the newest games before the player page catches up
        page += _get(f"{ZBL}/tym/{team_slug}").text
    ids = sorted(set(re.findall(r'href="/zapas/(\d+)"', page)), reverse=True)
    out = []
    for zid in ids:
        def fetch():
            r = _get(f"{ZBL}/zapas/{zid}")
            return r.text, "Boxscore" in r.text
        t = _text(_cached(f"zbl_{zid}.html", fetch))
        if "|Boxscore|" not in t:
            continue
        when = re.search(r"\|(\d{1,2})\. (\d{1,2})\. (\d{4}) - \d", t)
        if not when or int(when.group(3)) < 2026 or (int(when.group(3)) == 2026 and int(when.group(2)) < 8):
            continue  # 2026-27 season only
        box = t.split("|Boxscore|", 1)[1]
        # two team tables: "Team|Číslo|Hráč|Min.|...|+/-|rows...|Celkem|..."
        tables = re.findall(r"([^|]+)\|Číslo\|Hráč\|Min\.\|2B\|3B\|TH\|DU\|DO\|DC\|BL\|AS\|M\+\|M-\|F\+\|F-\|Val\|B\|\+/-\|(.*?)\|Celkem\|", box)
        if len(tables) < 2:
            continue
        pts, rows = [], []
        for team, body in tables[:2]:
            cells = body.split("|")
            players = []
            i = 0
            while i + 18 <= len(cells):
                if re.fullmatch(r"\d{1,2}", cells[i].strip()) and re.fullmatch(r"\d{1,2}:\d\d", cells[i + 2].strip()):
                    players.append(cells[i:i + 18])
                    i += 18
                else:
                    i += 1
            pts.append(sum(int(r[16]) for r in players))
            rows.append((team.strip(), players))
        for k, (team, players) in enumerate(rows):
            for r in players:
                if surname not in norm(r[1]).split():
                    continue
                f2, f3, ft = (list(map(int, r[j].split("/"))) for j in (3, 4, 5))
                out.append(game(f"{when.group(3)}-{int(when.group(2)):02d}-{int(when.group(1)):02d}",
                                f"Czech ZBL|{SEASON}", "Czech ZBL", team, rows[1 - k][0], k == 0, pts[k], pts[1 - k],
                                None, min=mmss(r[2]), pts=r[16], reb=r[8], oreb=r[6], ast=r[10], stl=r[11],
                                blk=r[9], tov=r[12], pf=r[14], fgm=f2[0] + f3[0], fga=f2[1] + f3[1], tpm=f3[0],
                                tpa=f3[1], ftm=ft[0], fta=ft[1]))
    return out


# --------------------------------------------------------------------------- TBF (Turkey)
TBF = "https://miniappapi.tbf.org.tr/webapi-service/api"


def tbf_games(pool, competition="kbsl"):
    seasons = _get(f"{TBF}/League/get-leagues-and-seasons-by-prefix", params={"prefix": competition}).json()["data"]
    row = next((r for r in seasons if r["sezon"] == "2026-2027"), None)
    if not row:
        return {}
    sid, aid = int(row["sezon_ID"]), int(row["faaliyet_ID"])
    weeks = [w["sezon_Hafta"] for w in _get(f"{TBF}/League/get-league-weeks",
                                            params={"seasonId": sid, "leagueId": aid}).json()["data"]]
    out = {}
    for w in weeks:
        for m in _get(f"{TBF}/Match/get-all-matches-for-filter",
                      params={"ActivityId": aid, "WeekFilter": w, "Page": 1, "PageSize": -1}).json()["data"]:
            if m["matchDateOnly"] > TODAY.isoformat() or not m["homeTeam"].get("score"):
                continue
            mid = int(m["matchId"])
            def fetch():
                r = _get(f"{TBF}/Match/mac-istatistik", params={"matchId": mid})
                return r.text, r.status_code == 200
            t = _cached(f"tbf_{mid}.json", fetch)
            box = json.loads(t).get("data") or {}
            for side, other in (("home", "away"), ("away", "home")):
                for p in (box.get(f"{side}TopFive") or []) + (box.get(f"{side}BenchPlayers") or []):
                    name = pool.match(p.get("playerName"))
                    if not name or mmss(p.get("minutesPlayed")) <= 0:
                        continue
                    me, op = m[f"{side}Team"], m[f"{other}Team"]
                    out.setdefault(name, []).append(game(
                        m["matchDateOnly"], f"Turkey KBSL|{SEASON}", "Turkey KBSL", me["name"].title(),
                        op["name"].title(), side == "home", int(me["score"]), int(op["score"]),
                        p in (box.get(f"{side}TopFive") or []), min=mmss(p["minutesPlayed"]), pts=p["points"],
                        reb=p["totalRebounds"], oreb=p["offensiveRebounds"], ast=p["assists"], stl=p["steals"],
                        blk=p["blocks"], tov=p["turnovers"], pf=p["fouls"], fgm=p["successfulShots"],
                        fga=p["shotAttempts"], tpm=p["threePointShots"], tpa=p["threePointShotAttempts"],
                        ftm=p["freeThrows"], fta=p["freeThrowAttempts"]))
    return out


# --------------------------------------------------------------------------- driver
class Pool:
    """Match any printed name to a pool player: first + last name both present."""
    def __init__(self, names):
        self.names = names
        self.keys = []
        for n in names:
            parts = norm(re.sub(r"\(.*?\)", "", n)).split()
            self.keys.append((n, parts[0], parts[-1]))

    def match(self, printed):
        toks = norm(printed).split()
        for n, first, last in self.keys:
            if last in toks and first in toks:
                return n
        return None


def collect(roster, overseas_cfg):
    """roster: list of pool names. overseas_cfg: per-player source hints from players.json."""
    pool = Pool(roster)
    games, shots, sources = {}, {}, {}

    def add(name, gs, src, sh=None, skey=None):
        if gs:
            games.setdefault(name, []).extend(gs)
            sources.setdefault(name, set()).add(src)
        if sh and skey:
            shots.setdefault(name, {}).setdefault(skey, []).extend(sh)

    steps = [
        ("FIBA EuroLeague/EuroCup", lambda: [add(n, g, "FIBA") for n, g in fiba_games(pool).items()]),
        ("Turkey KBSL", lambda: [add(n, g, "TBF") for n, g in tbf_games(pool).items()]),
    ]
    for name, cfg in overseas_cfg.items():
        for src in cfg:
            kind = src["source"]
            if kind == "lfb":
                def run(name=name, src=src):
                    key = f"France LFB|{SEASON}"
                    g, sh = genius_player_games(lfb_fixtures(src["club"]), "France LFB", key,
                                                src["surname"], src["club"])
                    add(name, g, "LiveStats", sh, key)
                steps.append((f"France LFB · {name}", run))
            elif kind == "genius_hosted":
                def run(name=name, src=src):
                    fx = hosted_fixtures(src["org"], src["comp_id"], src["club"])
                    g, sh = genius_player_games(fx, src["comp"], f"{src['comp']}|{SEASON}", src["surname"], src["club"])
                    add(name, g, "LiveStats", sh, f"{src['comp']}|{SEASON}")
                steps.append((f"{src['comp']} · {name}", run))
            elif kind == "zbl":
                steps.append((f"Czech ZBL · {name}", lambda name=name, src=src: add(
                    name, zbl_games(src["player_id"], src["surname"], src.get("team")), "ZBL")))
    feb_names = {n: c["name"] for n, cfg in overseas_cfg.items() for c in cfg if c["source"] == "feb"}
    if feb_names:
        steps.append(("Spain Liga Femenina", lambda: [add(n, g, "FEB") for n, g in
                                                      feb_games(4, "Spain Liga Femenina", feb_names).items()]))
        steps.append(("Spain LF-2", lambda: [add(n, g, "FEB") for n, g in
                                             feb_games(9, "Spain LF-2", feb_names).items()]))
    for label, fn in steps:
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - one broken source must not sink the build
            print(f"  {label}: FAILED ({type(e).__name__}: {e})")
    for n in games:  # newest first, drop duplicates (same date + opponent from two sources)
        seen, uniq = set(), []
        for g in sorted(games[n], key=lambda g: g["d"], reverse=True):
            k = (g["d"], g["comp"], norm(g["opp"]))
            if k not in seen:
                seen.add(k)
                uniq.append(g)
        games[n] = uniq
    return games, shots, {n: sorted(v) for n, v in sources.items()}
