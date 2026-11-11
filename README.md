# Canada SWNT Player Watch

Player cards for the Canada senior women's national team pool, showing how each player is doing with her club or college this season.

**Live site:** https://canada-basketball.github.io/SWNT_Tracker/ (rebuilt every morning)

Each card shows the player's photo, number, club logo, current status ("Played 3d ago", "No games in 14d", "WNBA offseason"), season averages (PPG, RPG, APG, TS%), her last game and a shot chart where one exists. Click a card for season averages by competition, last-5 form, points by game and the full game log.

## Data sources

| Coverage | Source | How |
|---|---|---|
| NCAA D-I, WNBA | ESPN via [SportsDataverse](https://www.sportsdataverse.org/) (wehoop) | Release parquet files: box scores + shot locations |
| EuroLeague / EuroCup / SuperCup Women | FIBA | FIBA's public data API. Every Canadian on any roster is picked up, so mid-season moves and WNBA players going overseas appear automatically |
| France LFB, Romania LNBF | FIBA LiveStats (Genius Sports) | Public game files, including shot locations |
| Spain Liga Femenina, LF Challenge, LF-2 | Spanish federation (FEB) | Every played game is scanned for every pool player |
| Czechia ŽBL | zbl.basketball | Server-rendered box scores |
| Turkey KBSL | Turkish federation (TBF) | Public app API; every game scanned |
| All overseas club games (main source) | [Hudl InStat](https://www.hudl.com/products/instat) | Canada Basketball subscription. Full box scores and shot locations, collected in a logged-in browser and saved to `data/instat/` (not committed). Replaces the feeds above for the same games |

The approach mirrors wehoop's `fiba_gdap_*`, `genius_*`, `feb_*` and `tbf_*` functions. Finished games are cached in `data/raw/overseas/`, so each run only fetches new games.

**Photos:** ESPN headshots for NCAA/WNBA players; FIBA national-team headshots (2026 events) for everyone else. **Logos and numbers** for overseas players come from each player's latest club box score.

## Run it

```
python3 -m venv .venv && .venv/bin/pip install pandas pyarrow requests pillow playwright
.venv/bin/python build.py              # download fresh data, write site/index.html
.venv/bin/python build.py --offline    # reuse downloaded NCAA/WNBA files
.venv/bin/python build.py --public     # same page, written to docs/index.html for GitHub Pages
```

Every build checks each game (points add up from the shooting splits, W/L matches the score). If one source fails, the build reports it and carries on with the others.

## Daily refresh

`.github/workflows/daily.yml` runs on GitHub's servers every day at 12:00 UTC (07:00 Toronto in winter), so no laptop is needed. It pulls InStat, rebuilds the page and pushes `docs/index.html` when it changes. Run it by hand from the repo's Actions tab ("Daily refresh" → Run workflow). The Hudl login is stored as repository secrets `HUDL_EMAIL` and `HUDL_PASSWORD`. InStat data is fetched fresh each run and never committed. If the InStat pull fails, the run stops and yesterday's page stays up.

`run_daily.sh` does the same on a Mac, using `.env` for the login. Its launch agent is switched off (`~/Library/LaunchAgents/ca.canadabasketball.wnt-player-watch.plist.disabled`) so it doesn't overlap with GitHub Actions; run the script by hand if Actions is down.

InStat is part of the daily run: `instat_fetch.py` opens Chrome with its own profile (`data/instat_profile/`), signs in with `HUDL_EMAIL` and `HUDL_PASSWORD` from `.env` when Hudl asks, and visits each player's Games and Field goals pages. Create `.env` yourself (it is git-ignored):

```
HUDL_EMAIL=...
HUDL_PASSWORD=...
```

A Chrome window is open for about two minutes during the run, because Hudl rejects windowless Chrome. If the sign-in fails, the build uses the last saved InStat data and the log says so.

## Updating the pool

Edit `players.json`. Fields:

| Field | Purpose |
|---|---|
| `name` | Display name; also used to match box scores |
| `espn_id` | ESPN athlete id for NCAA/WNBA players |
| `overseas` | Club sources: `lfb`, `genius_hosted` (org + comp_id), `feb`, `zbl` (player_id + team slug) |
| `instat_id` | Hudl InStat player id. Matching is by id, not name (InStat uses league-feed names, e.g. "Samantha Elizabeth Holli Hill") |
| `jersey` | Fallback number when no box score has one |
| `fiba_photo` | `{person, competition}` for the FIBA headshot |
| `team`, `note`, `pos` | Fallbacks shown when a source has nothing |

Overrides: drop an image in `data/photos/<player-slug>.png` (e.g. `sami-hill.png`) to replace a photo, or in `data/logos/<club-slug>.png` (e.g. `lulea-basket.png`) to replace a club logo.

## Files

| File | What it does |
|---|---|
| `build.py` | Loads all sources, merges seasons, embeds photos/logos, writes the page |
| `overseas.py` | FIBA, LiveStats, FEB, ŽBL and TBF collectors |
| `instat.py` | Reads the saved InStat file into games and shot charts |
| `instat_fetch.py` | Daily InStat pull (Chrome via Playwright) |
| `instat_collect.js` | Manual fallback: same collector, pasted into a logged-in InStat tab |
| `template.html` | The page (cards, player file, shot chart) |
| `run_daily.sh` | Daily build + push |
| `docs/index.html` | Published page (GitHub Pages) |
