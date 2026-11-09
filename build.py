"""Build the Canada WNT player tracker page.

Pulls ESPN box scores + shot locations for NCAA women's basketball and the WNBA
from SportsDataverse (wehoop) releases, keeps the players in players.json, and
writes a single self-contained HTML page (headshots/logos embedded as data URIs).

    .venv/bin/python build.py            # download fresh data, then build
    .venv/bin/python build.py --offline  # reuse data/raw
"""
import base64, io, json, re, sys, datetime as dt
from pathlib import Path

import pandas as pd
import requests
from PIL import Image

import eurobasket
import overseas

ROOT = Path(__file__).parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "site" / "index.html"
REL = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download"

# (league, espn season, release tag prefix)
SOURCES = [
    ("NCAA", 2026, "espn_womens_college_basketball"),
    ("NCAA", 2027, "espn_womens_college_basketball"),
    ("WNBA", 2026, "espn_wnba"),
]
FIBA_HEADSHOT = ("https://assets.fiba.basketball/image/upload/w_2800/c_pad,ar_12:10/c_pad,ar_10:12/"
                 "ar_10:12,c_crop,g_face,z_0.25/e_trim/c_lpad,ar_1:1/w_2800/w_2200,h_2000,c_crop,x_300/"
                 "w_600,h_437,c_fill,g_north/q_auto/f_png/.headshot--person_{person}--competition_{competition}")
HOOP_Y = 1.0  # ESPN raw coords: x 0-50 across, y feet from rim line (calibrated so 3PA sit at >=22 ft)


def season_label(league, season):
    return f"{season - 1}-{str(season)[2:]}" if league == "NCAA" else str(season)


def fetch(offline):
    RAW.mkdir(parents=True, exist_ok=True)
    for league, season, tag in SOURCES:
        pre = league.lower()
        for kind, name in [("player_boxscores", "player_box"), ("shots", "shots")]:
            dest = RAW / f"{pre}_{name}_{season}.parquet"
            if offline and dest.exists():
                continue
            r = requests.get(f"{REL}/{tag}_{kind}/{name}_{season}.parquet", timeout=120)
            r.raise_for_status()
            dest.write_bytes(r.content)


def load():
    box, shots = [], []
    for league, season, _ in SOURCES:
        pre = league.lower()
        b = pd.read_parquet(RAW / f"{pre}_player_box_{season}.parquet")
        b["league"], b["skey"] = league, f"{league}-{season}"
        box.append(b)
        s = pd.read_parquet(RAW / f"{pre}_shots_{season}.parquet")
        s["skey"] = f"{league}-{season}"
        shots.append(s)
    box = pd.concat(box, ignore_index=True)
    box = box[~box.did_not_play.fillna(False).astype(bool) & box.minutes.fillna(0).gt(0)]
    shots = pd.concat(shots, ignore_index=True)
    shots = shots[~shots.type_text.str.contains("Free", na=False)
                  & shots.coordinate_x_raw.between(0, 50)
                  & shots.coordinate_y_raw.between(-6, 40)]
    return box, shots


_img_cache = {}


def data_uri(url, width):
    """Download an image, shrink it, return a webp data URI (None if unavailable)."""
    if not url or not isinstance(url, str):
        return None
    if (url, width) in _img_cache:
        return _img_cache[(url, width)]
    out = None
    try:
        r = requests.get(url, timeout=30)
        if r.ok and r.content:
            im = Image.open(io.BytesIO(r.content)).convert("RGBA")
            im.thumbnail((width, width * 2))
            buf = io.BytesIO()
            im.save(buf, "WEBP", quality=82)
            out = "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception as e:  # noqa: BLE001 - a missing photo just falls back to initials
        print("  image failed:", url, e)
    _img_cache[(url, width)] = out
    return out


def local_uri(path, width):
    im = Image.open(path).convert("RGBA")
    im.thumbnail((width, width * 2))
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=82)
    return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()


def r1(x):
    return None if pd.isna(x) else round(float(x), 1)


def season_summary(g):
    n = len(g)
    s = g[["minutes", "points", "rebounds", "offensive_rebounds", "assists", "steals", "blocks",
           "turnovers", "fouls", "field_goals_made", "field_goals_attempted",
           "three_point_field_goals_made", "three_point_field_goals_attempted",
           "free_throws_made", "free_throws_attempted"]].sum()
    pct = lambda m, a: None if a == 0 else round(100 * m / a, 1)
    tsa = s.field_goals_attempted + 0.44 * s.free_throws_attempted
    return {
        "gp": n, "gs": int(g.starter.fillna(False).sum()),
        "mpg": r1(s.minutes / n), "ppg": r1(s.points / n), "rpg": r1(s.rebounds / n),
        "apg": r1(s.assists / n), "spg": r1(s.steals / n), "bpg": r1(s.blocks / n),
        "tpg": r1(s.turnovers / n),
        "fg": pct(s.field_goals_made, s.field_goals_attempted),
        "tp": pct(s.three_point_field_goals_made, s.three_point_field_goals_attempted),
        "tpa": r1(s.three_point_field_goals_attempted / n),
        "ft": pct(s.free_throws_made, s.free_throws_attempted),
        "ts": None if tsa == 0 else round(100 * s.points / (2 * tsa), 1),
    }


def build_player(p, box, shots, data_date, logos):
    base = {"name": p["name"], "note": p.get("note", ""), "manual_team": p.get("team", "")}
    if not p.get("espn_id"):
        return {**base, "covered": False}
    g = box[box.athlete_id == p["espn_id"]].sort_values("game_date_time")
    if g.empty:
        return {**base, "covered": False}
    last = g.iloc[-1]
    seasons = []
    for skey, sg in g.groupby("skey", sort=False):
        lg = sg.iloc[-1]
        seasons.append({
            "key": skey, "league": lg.league, "label": season_label(lg.league, int(lg.season)),
            "team": lg.team_location, "team_full": lg.team_display_name,
            "logo": logos.setdefault(lg.team_logo, lg.team_logo),
            "last": str(lg.game_date), **season_summary(sg),
        })
    seasons.sort(key=lambda s: s["last"], reverse=True)
    games = []
    for _, r in g.iloc[::-1].iterrows():
        games.append({
            "d": str(r.game_date), "s": r.skey, "po": int(r.season_type) == 3,
            "opp": r.opponent_team_location, "oppab": r.opponent_team_abbreviation,
            "ha": "vs" if r.home_away == "home" else "@",
            "wl": "W" if r.team_winner else "L", "sc": f"{int(r.team_score)}-{int(r.opponent_team_score)}",
            "st": bool(r.starter), "min": int(r.minutes), "pts": int(r.points), "reb": int(r.rebounds),
            "oreb": int(r.offensive_rebounds), "ast": int(r.assists), "stl": int(r.steals),
            "blk": int(r.blocks), "tov": int(r.turnovers), "pf": int(r.fouls),
            "fgm": int(r.field_goals_made), "fga": int(r.field_goals_attempted),
            "tpm": int(r.three_point_field_goals_made), "tpa": int(r.three_point_field_goals_attempted),
            "ftm": int(r.free_throws_made), "fta": int(r.free_throws_attempted),
        })
    sh = shots[shots.athlete_id_1 == p["espn_id"]]
    shot_map = {k: [[round(float(x), 1), round(float(y) - HOOP_Y, 1), int(m)]
                    for x, y, m in zip(v.coordinate_x_raw, v.coordinate_y_raw, v.scoring_play)]
                for k, v in sh.groupby("skey")}
    days_since = (dt.date.today() - last.game_date).days
    return {
        **base, "covered": True, "espn_id": int(p["espn_id"]),
        "jersey": str(last.athlete_jersey or ""), "pos": last.athlete_position_abbreviation or "",
        "photo": data_uri(last.athlete_headshot_href, 360),
        "team": last.team_location, "team_full": last.team_display_name,
        "team_color": "#" + (last.team_color or "666666"), "league": last.league,
        "last_game": str(last.game_date), "last_espn": str(last.game_date), "days_since": days_since,
        "seasons": seasons, "games": games, "shots": shot_map,
    }


SHORT = {"Spain LF Challenge": "LF Challenge", "EuroLeague Women": "EuroLeague", "EuroCup Women": "EuroCup", "SuperCup Women": "SuperCup",
         "Spain Liga Femenina": "Liga Femenina", "Spain LF-2": "LF-2", "Czech ZBL": "Czech ZBL",
         "France LFB": "LFB", "Romania LNBF": "Romania LNBF", "Turkey KBSL": "Turkey KBSL",
         "Sweden Damligan": "Damligan", "Germany DBBL": "DBBL", "Baltic WBBL": "Baltic WBBL"}


def summarize_games(gs):
    n = len(gs)
    tot = {k: sum(g[k] for g in gs) for k in ("min", "pts", "reb", "ast", "stl", "blk", "tov",
                                              "fgm", "fga", "tpm", "tpa", "ftm", "fta")}
    pct = lambda m, a: None if a == 0 else round(100 * m / a, 1)
    tsa = tot["fga"] + 0.44 * tot["fta"]
    return {
        "gp": n, "gs": sum(1 for g in gs if g["st"]), "gs_known": all(g["st"] is not None for g in gs),
        "mpg": r1(tot["min"] / n), "ppg": r1(tot["pts"] / n), "rpg": r1(tot["reb"] / n),
        "apg": r1(tot["ast"] / n), "spg": r1(tot["stl"] / n), "bpg": r1(tot["blk"] / n),
        "tpg": r1(tot["tov"] / n), "fg": pct(tot["fgm"], tot["fga"]), "tp": pct(tot["tpm"], tot["tpa"]),
        "tpa": r1(tot["tpa"] / n), "ft": pct(tot["ftm"], tot["fta"]),
        "ts": None if tsa == 0 else round(100 * tot["pts"] / (2 * tsa), 1),
    }


LOGOS = {}  # overseas club logo URLs to embed


def club_logo_override(team):
    """data/logos/<club-slug>.(png|jpg|webp|svg) replaces the source logo, e.g. data/logos/lulea-basket.png"""
    folder = ROOT / "data" / "logos"
    if not folder.exists():
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", (team or "").lower()).strip("-")
    hit = next(iter(sorted(folder.glob(slug + ".*"))), None)
    return "local:" + str(hit) if hit else None


def norm_team(name):
    return re.sub(r"[^a-z]", "", (name or "").lower())[:8]


def merge_overseas(pl, games, shots, sources):
    """Add club games from overseas.py: one season per competition plus an all-competitions total."""
    by_comp = {}
    for g in games:
        by_comp.setdefault(g["s"], []).append(g)
    seasons = []
    first_logo = lambda gs: next((g["logo"] for g in gs if g.get("logo") and norm_team(g["team"]) == norm_team(gs[0]["team"])), None)
    for key, gs in by_comp.items():
        comp, label = key.split("|")
        seasons.append({"key": key, "league": comp, "label": label, "team": gs[0]["team"],
                        "team_full": gs[0]["team"], "logo": first_logo(gs), "last": gs[0]["d"], **summarize_games(gs)})
    if len(by_comp) > 1:
        comps = sorted(by_comp, key=lambda k: -len(by_comp[k]))
        label = " + ".join(SHORT.get(k.split("|")[0], k.split("|")[0]) for k in comps)
        seasons.append({"key": "All club|" + overseas.SEASON, "league": label,
                        "label": overseas.SEASON, "team": games[0]["team"], "team_full": games[0]["team"],
                        "logo": first_logo(games) or next((s["logo"] for s in seasons if s["logo"]), None),
                        "last": games[0]["d"], "parts": list(by_comp), **summarize_games(games)})
        shots = {**shots, "All club|" + overseas.SEASON: [s for v in shots.values() for s in v]}
    # the all-competitions row goes first when it exists, then newest competition first
    seasons.sort(key=lambda s: (s["last"], s["key"].startswith("All club")), reverse=True)
    for s in seasons:
        override = club_logo_override(s["team"])
        if override:
            s["logo"] = override
        if s["logo"]:
            LOGOS.setdefault(s["logo"], s["logo"])
    keep = [{k: v for k, v in g.items() if k not in ("comp", "logo", "no")} for g in games]
    for g in keep:
        g["oppab"] = g["opp"]
    last = games[0]
    pl.update({
        "covered": True,
        "seasons": seasons + pl.get("seasons", []),
        "games": sorted(keep + pl.get("games", []), key=lambda g: g["d"], reverse=True),
        "shots": {**pl.get("shots", {}), **shots},
        "last_game": max(last["d"], pl.get("last_game", "")),
        "sources": sorted(set(pl.get("sources", [])) | set(sources)),
    })
    pl["days_since"] = (dt.date.today() - dt.date.fromisoformat(pl["last_game"])).days
    newest_no = next((g["no"] for g in games if g.get("no")), None)
    if newest_no and (not pl.get("jersey") or games[0]["d"] > (pl.get("last_espn") or "")):
        pl["jersey"] = newest_no  # club number from the latest overseas box score
    pl.setdefault("jersey", "")
    pl.setdefault("pos", "")
    pl.setdefault("photo", None)
    pl["team"], pl["team_full"], pl["league"] = last["team"], last["team"], last["s"].split("|")[0]


PUBLIC = "--public" in sys.argv
EB_NOTE = ("    Eurobasket (Canada Basketball subscription, internal use) fills Sweden, Germany and the Baltic league "
           "and confirms current clubs. ")


def main():
    offline = "--offline" in sys.argv
    print("fetching SportsDataverse releases..." if not offline else "using cached data")
    fetch(offline)
    box, shots = load()
    data_date = box.game_date.max()
    roster = json.loads((ROOT / "players.json").read_text())
    logos = {}
    players = []
    for p in roster:
        print(" ", p["name"])
        pl = build_player(p, box, shots, data_date, logos)
        if pl["covered"]:
            pl["sources"] = ["ESPN via SportsDataverse"]
        players.append(pl)
    print("overseas club games...")
    og, osh, osrc = overseas.collect([p["name"] for p in roster],
                                     {p["name"]: p["overseas"] for p in roster if p.get("overseas")})
    # Eurobasket (org subscription; pages saved from a logged-in browser): fills leagues the other
    # sources lack and gives each player's current club. Games another source already has are skipped.
    for p in roster:
        if PUBLIC:  # Eurobasket data is licensed for internal use only; never in the public build
            break
        eb = eurobasket.load(p["eurobasket_id"]) if p.get("eurobasket_id") else None
        if not eb:
            continue
        have = {g["d"] for g in og.get(p["name"], [])}
        extra = [g for g in eb["games"] if g["d"] not in have]
        if extra:
            og.setdefault(p["name"], []).extend(extra)
            og[p["name"]].sort(key=lambda g: g["d"], reverse=True)
            osrc.setdefault(p["name"], []).append("Eurobasket")
        pl = next(x for x in players if x["name"] == p["name"])
        if eb["club"]:
            pl["eb_club"] = f'{eb["club"]} ({eb["league"]})'
            pl["eb_checked"] = eb["fetched"]
    for pl in players:
        if og.get(pl["name"]):
            merge_overseas(pl, og[pl["name"]], osh.get(pl["name"], {}), osrc.get(pl["name"], []))
            print(f"  {pl['name']}: {len(og[pl['name']])} club games ({', '.join(osrc[pl['name']])})")
    # photos for players without a current ESPN headshot: data/photos/<slug>.* first, then ESPN college photo
    for p, pl in zip(roster, players):
        meta = overseas.META.get(p["name"], {})
        if not pl.get("jersey") and meta.get("jersey"):
            pl["jersey"] = meta["jersey"]
        if not pl.get("pos") and (meta.get("pos") or p.get("pos")):
            pl["pos"] = meta.get("pos") or p["pos"]
        if pl.get("photo"):
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", p["name"].lower()).strip("-")
        local = next(iter(sorted((ROOT / "data" / "photos").glob(slug + ".*"))), None) \
            if (ROOT / "data" / "photos").exists() else None
        if local:
            pl["photo"] = local_uri(local, 360)
        elif p.get("fiba_photo") and (fp := data_uri(FIBA_HEADSHOT.format(**p["fiba_photo"]), 360)):
            pl["photo"] = fp  # Canada national-team headshot from the latest FIBA event
        elif p.get("photo_espn_id"):
            pl["photo"] = data_uri("https://a.espncdn.com/i/headshots/womens-college-basketball/players/full/"
                                   f"{p['photo_espn_id']}.png", 360)
    logos.update(LOGOS)
    logo_uris = {u: (local_uri(Path(u[6:]), 96) if u.startswith("local:") else data_uri(u, 96)) for u in logos}
    for pl in players:
        for s in pl.get("seasons", []):
            s["logo"] = logo_uris.get(s["logo"]) if s["logo"] else None
    # which NCAA season is current (has games), so cards can flag players with none yet
    current = {"NCAA": f"NCAA-{box[box.league == 'NCAA'].season.max()}",
               "WNBA": f"WNBA-{box[box.league == 'WNBA'].season.max()}"}
    # a league is in season if any game was played in the last week of data
    in_season = {lg: bool((data_date - box[box.league == lg].game_date.max()).days <= 7) for lg in ("NCAA", "WNBA")}
    payload = {
        "built": dt.date.today().isoformat(), "data_through": str(data_date),
        "current": current, "in_season": in_season, "players": players,
    }
    html = (ROOT / "template.html").read_text().replace(
        "/*__DATA__*/null", json.dumps(payload, separators=(",", ":")))
    out = OUT
    if PUBLIC:
        html = html.replace(EB_NOTE.strip(), "Sweden, Germany and Baltic league games are not in this public version.")
        out = ROOT / "docs" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html)
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB), data through {data_date}")


if __name__ == "__main__":
    main()
