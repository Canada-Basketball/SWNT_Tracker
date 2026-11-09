"""Eurobasket player pages -> game rows (organization subscription, internal use).

Pages are read in a logged-in browser (Claude in Chrome) at browsing pace and saved as plain
text under data/eurobasket/{eurobasket_id}_{slug}.txt; this module only parses those files.
No login, cookie or automated download lives in this repo.

Row format (Eurobasket DETAILS table; RESULT lists the player's team score first):
DATE TEAM AGAINST RESULT MIN PTS 2FGP 3FGP FT RO RD RT AS PF BS ST TO RNK
"""
import re
from pathlib import Path

DIR = Path(__file__).parent / "data" / "eurobasket"
SEASON = "2026-27"
LEAGUES = {  # Eurobasket league label -> page label
    "Sweden-Damligan": "Sweden Damligan", "Germany-DBBL": "Germany DBBL", "WBBL": "Baltic WBBL",
    "Euroleague": "EuroLeague Women", "Eurocup": "EuroCup Women", "Spain-Liga Femenina": "Spain Liga Femenina",
    "France-LFB": "France LFB", "Czech Republic-ZBL": "Czech ZBL", "Turkey-KBSL": "Turkey KBSL",
    "Romania-Liga Nationala": "Romania LNBF", "Hungary-A Division": "Hungary NB I",
    "Italy-Serie A1": "Italy Serie A1", "Poland-PLKK": "Poland BLK", "Australia-WNBL": "Australia WNBL",
}
ROW = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4}) (.+?) (\d+)-(\d+) (\d+) (\d+) (\d+)-(\d+) (\d+)-(\d+) (\d+)-(\d+)"
                 r" (\d+) (\d+) (\d+) (\d+) (\d+) (\d+) (\d+) (\d+) (-?\d+)$")


def parse(path):
    text = Path(path).read_text()
    club = re.search(r"most recently played at (.+?) in (.+?)\.", text)
    jersey = re.search(r"^JERSEY: (\S+)", text, re.M)
    logo = re.search(r"^TEAMLOGO: (\S+)", text, re.M)
    fetched = re.search(r"^FETCHED: (\S+)", text, re.M)
    games, teams = [], {}
    league = None
    section = None
    for line in text.splitlines():
        m = re.match(r"Season: (\d{4})-(\d{4}) \((.+)\)", line)
        if m:
            league = LEAGUES.get(m.group(3), m.group(3)) if m.group(1) == "2026" else None
            continue
        if line in ("SUMMARY", "DETAILS"):
            section = line
            continue
        if not league:
            continue
        if section == "SUMMARY" and not line.startswith("TEAM"):
            name = re.match(r"(.+?) \d+ \d+ \d+ ", line)
            if name:
                teams.setdefault(league, []).append(name.group(1))
        r = ROW.match(line) if section == "DETAILS" else None
        if not r:
            continue
        mo, dy, yr, rest = r.group(1), r.group(2), r.group(3), r.group(4)
        team = next((t for t in teams.get(league, []) if rest.startswith(t + " ")), None)
        if not team:
            continue
        opp = rest[len(team) + 1:]
        tp, op = int(r.group(5)), int(r.group(6))
        f2m, f2a, f3m, f3a, ftm, fta = (int(r.group(i)) for i in range(9, 15))
        games.append({
            "d": f"{yr}-{int(mo):02d}-{int(dy):02d}", "s": f"{league}|{SEASON}", "comp": league,
            "team": team, "po": False, "opp": opp, "oppab": opp, "ha": "", "wl": "W" if tp > op else "L",
            "sc": f"{tp}-{op}", "st": None, "min": int(r.group(7)), "pts": int(r.group(8)),
            "logo": None, "no": jersey.group(1) if jersey else None,
            "fgm": f2m + f3m, "fga": f2a + f3a, "tpm": f3m, "tpa": f3a, "ftm": ftm, "fta": fta,
            "oreb": int(r.group(15)), "reb": int(r.group(17)), "ast": int(r.group(18)), "pf": int(r.group(19)),
            "blk": int(r.group(20)), "stl": int(r.group(21)), "tov": int(r.group(22)),
        })
    if logo:  # logo applies to the player's current club games
        for g in games:
            if club and g["team"].split()[0].lower() in club.group(1).lower():
                g["logo"] = logo.group(1)
    return {"games": games, "club": club.group(1) if club else None,
            "league": club.group(2) if club else None, "fetched": fetched.group(1) if fetched else None}


def load(eurobasket_id):
    hits = list(DIR.glob(f"{eurobasket_id}_*.txt"))
    return parse(hits[0]) if hits else None
