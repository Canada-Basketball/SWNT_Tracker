"""Hudl InStat club games + shot locations (Canada Basketball subscription, internal use).

InStat has no public API. The data is collected in a logged-in browser with instat_collect.js
(it records the responses the InStat app itself loads; no login or token is stored) and saved as
data/instat/2026-27.json: {instat_player_id: {"g": [game rows], "s": {match_id: [[x, y, made, is3]]}}}.

Game row: [match_id, date, tournament, team, team_pts, opp, opp_pts, home, seconds,
           pts, fgm, fga, tpm, tpa, ftm, fta, oreb, dreb, reb, ast, stl, blk, tov, pf, plus_minus, has_shots]
Shot x runs along the court (0-28 m, attacking the basket at x = 26.4), y across it (0-15 m).
Players are matched by InStat id (players.json "instat_id"), never by name: InStat takes names from
league feeds, e.g. Sami Hill is "Samantha Elizabeth Holli Hill" and Shay Colley "Shaylisha Colley".
"""
import json
from pathlib import Path

import overseas

FILE = Path(__file__).parent / "data" / "instat" / f"{overseas.SEASON}.json"
COURT_L, COURT_W, RIM = 28.0, 15.0, 1.575
LEAGUES = {
    "Spain. Liga Femenina W": "Spain Liga Femenina", "Spain. Supercopa (W)": "Spain Supercopa",
    "Spain. LF Challenge": "Spain LF Challenge", "Eurocup Women": "EuroCup Women",
    "Euroleague (W)": "EuroLeague Women", "France. LFB": "France LFB", "France. Coupe de France (W)": "France Cup",
    "Czech Republic. ZBL W": "Czech ZBL", "Sweden. Basketligan Dam": "Sweden Damligan",
    "Germany. 1. DBBL": "Germany DBBL", "Turkey. KBSL": "Turkey KBSL",
}
SKIP = ("Friendlies",)  # pre-season friendlies are not shown


def load():
    return json.loads(FILE.read_text()) if FILE.exists() else {}


def player(data, instat_id):
    """Return (games, shots by season key) for one player, newest game first."""
    rec = data.get(str(instat_id))
    if not rec:
        return [], {}
    games, shots = [], {}
    for r in rec["g"]:
        if len(r) < 26 or any(s in r[2] for s in SKIP):
            continue  # no box score yet, or a friendly
        (mid, d, tour, team, tp, opp, op, home, secs,
         pts, fgm, fga, tpm, tpa, ftm, fta, oreb, dreb, reb, ast, stl, blk, tov, pf, _pm, _hs) = r
        comp = LEAGUES.get(tour, tour.replace(". ", " "))
        key = f"{comp}|{overseas.SEASON}"
        games.append(overseas.game(d, key, comp, team, opp, home, tp, op, None,
                                   min=(secs or 0) / 60, pts=pts, reb=reb, oreb=oreb, ast=ast, stl=stl, blk=blk,
                                   tov=tov, pf=pf, fgm=fgm, fga=fga, tpm=tpm, tpa=tpa, ftm=ftm, fta=fta))
        for x, y, made, _is3 in rec["s"].get(str(mid), []):
            along = COURT_L - RIM - x  # metres from the rim line into the court
            across = COURT_W - y       # same orientation as the LiveStats charts
            shots.setdefault(key, []).append([round(across / COURT_W * 50, 1), round(along * 3.281, 1), made])
    games.sort(key=lambda g: g["d"], reverse=True)
    return games, shots
