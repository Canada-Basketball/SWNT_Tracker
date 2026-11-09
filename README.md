# Canada WNT Player Watch

Player cards for the Canada senior women's pool, showing how each player is doing with her own club or school.
Click a card for season averages, last-5 form, a shot chart, points by game and the game log.

Data:
- NCAA D-I and WNBA: ESPN box scores + shot locations from [SportsDataverse](https://www.sportsdataverse.org/) (wehoop) releases.
- Overseas (`overseas.py`, same sources as wehoop's `fiba_gdap_*`, `genius_*`, `feb_*`, `tbf_*`):
  FIBA (EuroLeague / EuroCup Women; any Canadian on a roster is picked up automatically),
  FIBA LiveStats (France LFB, Romania LNBF), Spanish federation (Liga Femenina, LF-2),
  zbl.basketball (Czechia), Turkish federation (KBSL). Finished games are cached in `data/raw/overseas/`.
- Not connected yet: German DBBL and Lithuanian domestic leagues.

```
python3 -m venv .venv && .venv/bin/pip install pandas pyarrow requests pillow
.venv/bin/python build.py          # download latest data and write site/index.html
.venv/bin/python build.py --offline
```

Edit `players.json` to change the pool. `espn_id` links a player to ESPN; `overseas` lists club sources (lfb, genius_hosted, feb, zbl).
