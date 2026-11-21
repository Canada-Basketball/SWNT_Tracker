"""Scouting-report numbers for NCAA and WNBA players: percentiles vs same-season peers, skill ratings and
similar players. Peers = everyone in that league-season who played enough (see pool()), split by role:
guards and wings (forwards who shoot threes and rarely crash the offensive glass) vs bigs. Overseas leagues have no league-wide data, so they get no percentiles.
"""
import numpy as np
import pandas as pd

# (key, label, higher_is_better, format)
METRICS = [
    ("pts40", "Points / 40", True, "{:.1f}"),
    ("usg", "Usage %", True, "{:.1f}"),
    ("ts", "TS%", True, "{:.1f}"),
    ("efg", "eFG%", True, "{:.1f}"),
    ("tp", "3P%", True, "{:.1f}"),
    ("tpa40", "3PA / 40", True, "{:.1f}"),
    ("ft", "FT%", True, "{:.1f}"),
    ("ftr", "FT rate", True, "{:.2f}"),
    ("ast40", "Assists / 40", True, "{:.1f}"),
    ("ato", "AST / TOV", True, "{:.2f}"),
    ("tovp", "Turnover %", False, "{:.1f}"),
    ("oreb40", "Off reb / 40", True, "{:.1f}"),
    ("dreb40", "Def reb / 40", True, "{:.1f}"),
    ("stl40", "Steals / 40", True, "{:.1f}"),
    ("blk40", "Blocks / 40", True, "{:.1f}"),
    ("pf40", "Fouls / 40", False, "{:.1f}"),
]
# skill ratings = average percentile of their metrics
SKILLS = [
    ("Scoring", ["pts40", "usg"]),
    ("Efficiency", ["ts", "efg", "ft"]),
    ("Shooting", ["tp", "tpa40"]),
    ("Playmaking", ["ast40", "ato", "tovp"]),
    ("Rebounding", ["oreb40", "dreb40"]),
    ("Defense", ["stl40", "blk40"]),
]
MIN_MPG = 12


def season_table(box):
    """One row per player-season with the rate stats above."""
    b = box.copy()
    b["poss"] = b.field_goals_attempted + 0.44 * b.free_throws_attempted + b.turnovers
    team = b.groupby(["game_id", "team_id"]).agg(t_poss=("poss", "sum"), t_min=("minutes", "sum")).reset_index()
    b = b.merge(team, on=["game_id", "team_id"])
    cols = {"minutes": "min", "points": "pts", "field_goals_made": "fgm", "field_goals_attempted": "fga",
            "three_point_field_goals_made": "tpm", "three_point_field_goals_attempted": "tpa",
            "free_throws_made": "ftm", "free_throws_attempted": "fta", "offensive_rebounds": "oreb",
            "defensive_rebounds": "dreb", "rebounds": "reb", "assists": "ast", "steals": "stl", "blocks": "blk",
            "turnovers": "tov", "fouls": "pf", "poss": "poss", "t_poss": "t_poss", "t_min": "t_min"}
    g = b.rename(columns=cols).groupby(["skey", "athlete_id"])
    t = g[list(cols.values())].sum()
    t["gp"] = g.game_id.nunique()
    last = b.sort_values("game_date_time").groupby(["skey", "athlete_id"]).last()
    t["name"], t["team"], t["pos"] = last.athlete_display_name, last.team_location, last.athlete_position_abbreviation
    t = t.reset_index()
    m = t["min"].where(t["min"] > 0)
    per40 = lambda c: 40 * t[c] / m
    div = lambda a, b: a / b.where(b > 0)
    t["mpg"] = t["min"] / t.gp
    t["ppg"], t["rpg"], t["apg"] = t.pts / t.gp, t.reb / t.gp, t.ast / t.gp
    t["pts40"], t["tpa40"], t["ast40"] = per40("pts"), per40("tpa"), per40("ast")
    t["oreb40"], t["dreb40"], t["stl40"], t["blk40"], t["pf40"] = (per40(c) for c in ("oreb", "dreb", "stl", "blk", "pf"))
    t["usg"] = 100 * div(t.poss * t.t_min / 5, m * t.t_poss)
    t["ts"] = 100 * div(t.pts, 2 * (t.fga + 0.44 * t.fta))
    t["efg"] = 100 * div(t.fgm + 0.5 * t.tpm, t.fga)
    t["tp"] = 100 * div(t.tpm, t.tpa)
    t["ft"] = 100 * div(t.ftm, t.fta)
    t["ftr"] = div(t.fta, t.fga)
    t["ato"] = div(t.ast, t.tov.clip(lower=1))
    t["tovp"] = 100 * div(t.tov, t.poss)
    return t


WING_3PA40 = 4.0  # a forward is a wing with this many 3PA per 40 and below-median offensive rebounding for bigs


def roles(t, peers):
    """'G' (guards and wings) or 'F' (bigs) by how a player plays, not only the listed position:
    ESPN lists stretch wings like Bridget Carleton as F, which would compare them with centres."""
    pos = t.pos.fillna("G")
    big = ~pos.str.contains("G")
    oreb_med = peers[~peers.pos.fillna("G").str.contains("G")].oreb40.median()
    wing = big & ~pos.str.contains("C") & (t.tpa40 >= WING_3PA40) & (t.oreb40 < oreb_med)
    return np.where(big & ~wing, "F", "G")


def pool(t, skey):
    """Peers for a league-season: at least MIN_MPG minutes a game and 40% of the typical games played."""
    s = t[t.skey == skey]
    need = max(2, int(0.4 * s[s.mpg >= MIN_MPG].gp.median()))
    return s[(s.mpg >= MIN_MPG) & (s.gp >= need)], need


def pct_rank(series, v, higher):
    s = series.dropna()
    if pd.isna(v) or s.empty:
        return None
    r = ((s < v).sum() + 0.5 * (s == v).sum()) / len(s)
    return int(round(100 * (r if higher else 1 - r)))


def profiles(box, ids):
    """{espn_id: {skey: profile}} for the given ESPN athlete ids."""
    t = season_table(box)
    out = {}
    for skey in t.skey.unique():
        peers_all, need = pool(t, skey)
        peers_all = peers_all.assign(group=roles(peers_all, peers_all))
        mine = t[(t.skey == skey) & t.athlete_id.isin(ids)]
        mine = mine.assign(group=roles(mine, peers_all))
        for _, r in mine.iterrows():
            peers = peers_all[peers_all.group == r.group]
            # shooting % only counts peers with real attempts
            att = {"tp": peers.tpa >= 1.0 * peers.gp, "ft": peers.fta >= 1.0 * peers.gp}
            pcts = {}
            for k, label, hi, fmt in METRICS:
                ser = peers[k][att[k]] if k in att else peers[k]
                pcts[k] = pct_rank(ser, r[k], hi)
            skills = []
            for name, ks in SKILLS:
                vals = [pcts[k] for k in ks if pcts[k] is not None]
                skills.append([name, int(round(sum(vals) / len(vals))) if vals else None])
            ok = [v for _, v in skills if v is not None]
            # similar players: closest percentile profile among all peers (both groups)
            vec_keys = [k for k, *_ in METRICS]
            P = pd.DataFrame({k: peers_all[k].rank(pct=True) * 100 for k in vec_keys}).fillna(50)
            me = P.loc[peers_all.athlete_id == r.athlete_id]
            sim = []
            if not me.empty:
                d = np.sqrt(((P - me.iloc[0]) ** 2).mean(axis=1))
                for i in d.drop(me.index).nsmallest(6).index:
                    q = peers_all.loc[i]
                    sim.append({"name": q["name"], "team": q.team, "pos": q.pos, "gp": int(q.gp),
                                "mpg": round(float(q.mpg), 1), "ppg": round(float(q.ppg), 1), "rpg": round(float(q.rpg), 1),
                                "apg": round(float(q.apg), 1), "ts": None if pd.isna(q.ts) else round(float(q.ts), 1),
                                "match": int(round(100 - float(d[i])))})
            out.setdefault(int(r.athlete_id), {})[skey] = {
                "peers": int(len(peers)), "league": skey.split("-")[0], "group": "guards and wings" if r.group == "G" else "bigs (forwards and centres)",
                "role": "G" if r.group == "G" else "F",
                "min_gp": need, "min_mpg": MIN_MPG, "qualified": bool(r.mpg >= MIN_MPG and r.gp >= need),
                "metrics": [[k, label, None if pd.isna(r[k]) else fmt.format(r[k]), pcts[k]] for k, label, hi, fmt in METRICS],
                "skills": skills, "overall": int(round(sum(ok) / len(ok))) if ok else None,
                "usg": None if pd.isna(r.usg) else round(float(r.usg), 1),
                "similar": sim,
            }
    return out


# ---------------------------------------------------------------- play-by-play (ESPN shot events, incl. free throws)
def team_ratings(box):
    """{skey: {team_id: rank}} from game scores: least-squares margin ratings with home court, lightly shrunk
    to 0 so teams with few games don't jump to the top. Only teams with 3+ games are ranked."""
    out = {}
    tg = box.drop_duplicates(["skey", "game_id", "team_id"])
    for skey, g in tg.groupby("skey"):
        g = g.dropna(subset=["team_score", "opponent_team_score"])
        n_games = g.team_id.value_counts()
        teams = sorted(set(g.team_id) | set(g.opponent_team_id))
        ix = {t: i for i, t in enumerate(teams)}
        X = np.zeros((len(g), len(teams) + 1))
        X[np.arange(len(g)), g.team_id.map(ix)] = 1
        X[np.arange(len(g)), g.opponent_team_id.map(ix)] = -1
        X[:, -1] = np.where(g.home_away == "home", 1, -1)
        y = (g.team_score.astype(float) - g.opponent_team_score.astype(float)).to_numpy()
        lam = 2.0
        r = np.linalg.solve(X.T @ X + lam * np.eye(X.shape[1]), X.T @ y)[:-1]
        rated = sorted((t for t in teams if n_games.get(t, 0) >= 3), key=lambda t: -r[ix[t]])
        out[skey] = {int(t): i + 1 for i, t in enumerate(rated)}
    return out


def _secs(c):
    m, _, s = str(c).rpartition(":")
    try:
        return (int(m) if m else 0) * 60 + float(s)
    except ValueError:
        return None


def pbp_table(pbp):
    """Per player-season: self-created makes, and-ones, FT trips, by-quarter and clutch scoring.
    Clutch = 4th quarter or OT, last 5:00, score within 5 before the shot."""
    p = pbp.copy().reset_index(drop=True)
    p["is_ft"] = p.type_text.str.contains("Free ?Throw", regex=True)
    p["tech"] = p.type_text.str.contains("Technical|Flagrant|Clear Path")
    p["made"] = p.scoring_play.fillna(False).astype(bool)
    p["pts"] = p.score_value.fillna(0).astype(int) * p.made
    p["tp"] = ~p.is_ft & (p.score_value == 3)
    # score margin (shooter's team minus opponent) before each event
    p["seq"] = np.arange(len(p))
    p["team_pts_before"] = p.groupby(["game_id", "team_id"]).pts.cumsum() - p.pts
    p["game_pts_before"] = p.groupby("game_id").pts.cumsum() - p.pts
    p["margin"] = 2 * p.team_pts_before - p.game_pts_before
    p["left"] = p.clock_display_value.map(_secs)
    p["clutch"] = (p.period_number >= 4) & (p.left <= 300) & (p.margin.abs() <= 5)
    p["q"] = p.period_number.clip(upper=5)
    # free-throw trips and and-ones: free throws by the same player at the same moment
    ft = p[p.is_ft & ~p.tech]
    trips = ft.groupby(["skey", "game_id", "period_number", "clock_display_value", "athlete_id_1"]).size().rename("n_ft")
    fg = p[~p.is_ft]
    made = fg[fg.made].join(trips, on=["skey", "game_id", "period_number", "clock_display_value", "athlete_id_1"])
    made["and1"] = made.n_ft.eq(1)
    k = ["skey", "athlete_id_1"]
    t = pd.DataFrame({
        "p_fgm": fg.groupby(k).made.sum(), "p_fga": fg.groupby(k).size(),
        "ast_fgm": made.groupby(k).athlete_id_2.apply(lambda s: s.notna().sum()),
        "and1": made.groupby(k).and1.sum(),
        "trips": trips.reset_index().groupby(k).size(),
    }).fillna(0)
    t["self_fgm"] = t.p_fgm - t.ast_fgm
    t["self_pct"] = 100 * t.self_fgm / t.p_fgm.where(t.p_fgm > 0)
    # quarters and clutch: [pts, fgm, fga, ftm, fta]
    def agg(d):
        f, fr = d[~d.is_ft], d[d.is_ft]
        return [int(d.pts.sum()), int(f.made.sum()), len(f), int(fr.made.sum()), len(fr)]
    quarters = {key: {int(q): agg(d) for q, d in g.groupby("q")} for key, g in p.groupby(k)}
    clutch = {key: agg(g) + [int(g.game_id.nunique())] for key, g in p[p.clutch].groupby(k)}
    return t.reset_index().rename(columns={"athlete_id_1": "athlete_id"}), quarters, clutch


PBP_METRICS = [("self_pct", "Self-created makes %", "{:.0f}"), ("self40", "Self-created makes / 40", "{:.1f}"),
               ("and140", "And-ones / 40", "{:.2f}"), ("trips40", "FT trips / 40", "{:.1f}")]


def add_pbp(out, box, pbp):
    """Adds creation, quarter, clutch and schedule data to the profiles built by profiles()."""
    t = season_table(box)
    pt, quarters, clutch = pbp_table(pbp)
    t = t.merge(pt, on=["skey", "athlete_id"], how="left")
    m = t["min"].where(t["min"] > 0)
    t["self40"], t["and140"], t["trips40"] = 40 * t.self_fgm / m, 40 * t.and1 / m, 40 * t.trips / m
    ranks = team_ratings(box)
    games = box.drop_duplicates(["skey", "athlete_id", "game_id"])
    for aid, seasons in out.items():
        for skey, prof in seasons.items():
            peers_all, _ = pool(t, skey)
            peers_all = peers_all.assign(group=roles(peers_all, peers_all))
            peers = peers_all[peers_all.group == prof["role"]]
            r = t[(t.skey == skey) & (t.athlete_id == aid)]
            if r.empty or pd.isna(r.iloc[0].p_fga):
                continue
            r = r.iloc[0]
            crt = []
            for k, label, fmt in PBP_METRICS:
                ser = peers[k][peers.p_fgm >= 1.0 * peers.gp] if k == "self_pct" else peers[k]
                crt.append([k, label, None if pd.isna(r[k]) else fmt.format(r[k]), pct_rank(ser, r[k], True)])
            prof["creation"] = crt
            prof["counts"] = {"fgm": int(r.p_fgm), "ast_fgm": int(r.ast_fgm), "and1": int(r.and1), "trips": int(r.trips)}
            prof["quarters"] = quarters.get((skey, aid), {})
            prof["clutch"] = clutch.get((skey, aid))
            # schedule: opponent rank for each game, keyed by date
            rk = ranks.get(skey, {})
            mine = games[(games.skey == skey) & (games.athlete_id == aid)]
            opp = {str(d): rk.get(int(o)) for d, o in zip(mine.game_date, mine.opponent_team_id)}
            known = [v for v in opp.values() if v]
            prof["opp_rank"] = opp
            prof["n_teams"] = len(rk)
            prof["top"] = 50 if skey.startswith("NCAA") else 5
            prof["avg_opp_rank"] = round(sum(known) / len(known)) if known else None
    return out
