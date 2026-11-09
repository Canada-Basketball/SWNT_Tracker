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
| Sweden, Germany DBBL, Baltic WBBL, current clubs | [Eurobasket.com](https://www.eurobasket.com/) | Canada Basketball subscription; pages read in a logged-in browser and saved to `data/eurobasket/` (not committed) |

The approach mirrors wehoop's `fiba_gdap_*`, `genius_*`, `feb_*` and `tbf_*` functions. Finished games are cached in `data/raw/overseas/`, so each run only fetches new games.

**Photos:** ESPN headshots for NCAA/WNBA players; FIBA national-team headshots (2026 events) for everyone else. **Logos and numbers** for overseas players come from each player's latest club box score.

## Run it

```
python3 -m venv .venv && .venv/bin/pip install pandas pyarrow requests pillow
.venv/bin/python build.py              # download fresh data, write site/index.html
.venv/bin/python build.py --offline    # reuse downloaded NCAA/WNBA files
.venv/bin/python build.py --public     # same page, written to docs/index.html for GitHub Pages
```

Every build checks each game (points add up from the shooting splits, W/L matches the score). If one source fails, the build reports it and carries on with the others.

## Daily refresh

`run_daily.sh` runs at 07:00 via a macOS launch agent (`~/Library/LaunchAgents/ca.canadabasketball.wnt-player-watch.plist`). It rebuilds the page, commits `docs/index.html` when it changes and pushes to GitHub Pages. If a build fails it keeps the previous page. Logs go to `logs/<date>.log`. The Mac must be on at 07:00.

Eurobasket is not part of the automatic run: Eurobasket blocks scripts. Refresh those pages in a logged-in browser (ask Claude to "refresh Eurobasket"), especially when a card shows "No games in 14d".

## Updating the pool

Edit `players.json`. Fields:

| Field | Purpose |
|---|---|
| `name` | Display name; also used to match box scores |
| `espn_id` | ESPN athlete id for NCAA/WNBA players |
| `overseas` | Club sources: `lfb`, `genius_hosted` (org + comp_id), `feb`, `zbl` (player_id + team slug) |
| `eurobasket_id` | Links the saved Eurobasket page in `data/eurobasket/` |
| `fiba_photo` | `{person, competition}` for the FIBA headshot |
| `team`, `note`, `pos` | Fallbacks shown when a source has nothing |

Overrides: drop an image in `data/photos/<player-slug>.png` (e.g. `sami-hill.png`) to replace a photo, or in `data/logos/<club-slug>.png` (e.g. `lulea-basket.png`) to replace a club logo.

## Files

| File | What it does |
|---|---|
| `build.py` | Loads all sources, merges seasons, embeds photos/logos, writes the page |
| `overseas.py` | FIBA, LiveStats, FEB, ŽBL and TBF collectors |
| `eurobasket.py` | Parses saved Eurobasket pages |
| `template.html` | The page (cards, player file, shot chart) |
| `run_daily.sh` | Daily build + push |
| `docs/index.html` | Published page (GitHub Pages) |
