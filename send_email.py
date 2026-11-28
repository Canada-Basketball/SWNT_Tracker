"""Daily 7:00 email: yesterday's games for the SWNT pool, from the published page's data.

Sends through Gmail SMTP with an app password. Settings come from the environment (GitHub secrets):
GMAIL_ADDRESS (sender), GMAIL_APP_PASSWORD, EMAIL_TO (comma-separated recipients).
Usage: python send_email.py [--dry-run]   (--dry-run writes email.html instead of sending)
"""
import datetime as dt
import html
import json
import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent
SITE = "https://canada-basketball.github.io/SWNT_Tracker/"


def data():
    page = (ROOT / "docs" / "index.html").read_text()
    start = page.index("const DATA = ") + len("const DATA = ")
    return json.JSONDecoder().raw_decode(page[start:])[0]


def league(s):
    return "NCAA" if s.startswith("NCAA-") else "WNBA" if s.startswith("WNBA-") else s.split("|")[0]


def pct(m, a):
    return f"{100 * m / a:.0f}%" if a else "–"


def build():
    d = data()
    today = dt.datetime.now(ZoneInfo("America/Toronto")).date()
    day = (today - dt.timedelta(days=1)).isoformat()
    rows = []
    for p in d["players"]:
        team_of = {s["key"]: s.get("short") or s.get("team") for s in p.get("seasons", [])}
        for g in p.get("games", []):
            if g["d"] == day:
                rows.append((g["pts"], p["name"], g.get("team") or team_of.get(g["s"], ""), league(g["s"]), g))
    rows.sort(key=lambda r: -r[0])
    th = "padding:6px 8px;background:#85091e;color:#fff;font:600 11px Arial;text-align:right"
    td = "padding:6px 8px;border-bottom:1px solid #eee;font:13px Arial;text-align:right"
    head = "".join(f'<th style="{th}{";text-align:left" if i < 4 else ""}">{h}</th>' for i, h in enumerate(
        ["Player", "Team", "League", "Result", "MIN", "PTS", "REB", "AST", "STL", "BLK", "TO", "FG", "3P", "FT"]))
    body = ""
    for pts, name, team, lg, g in rows:
        cells = [name, team, lg, f'{g["wl"]} {g["sc"]} {"@" if g.get("ha") == "@" else "vs"} {g["opp"]}', g["min"], f"<b>{pts}</b>",
                 g["reb"], g["ast"], g["stl"], g["blk"], g["tov"], f'{g["fgm"]}-{g["fga"]}', f'{g["tpm"]}-{g["tpa"]}', f'{g["ftm"]}-{g["fta"]}']
        body += "<tr>" + "".join(f'<td style="{td}{";text-align:left" if i < 4 else ""}">{c if i == 5 else html.escape(str(c))}</td>'
                                 for i, c in enumerate(cells)) + "</tr>"
    st_file = ROOT / "data" / "eurobasket_stats" / "status.json"
    st = json.loads(st_file.read_text()) if st_file.exists() else None
    if st and st["ok"] and st["at"][:10] == today.isoformat():
        eb = f'Eurobasket updated today at {st["at"][11:16]}.'
    elif st:
        eb = f'<b style="color:#ba0c2f">Eurobasket did not update today</b> ({html.escape(st["msg"])}). Last good data stays on the site. ' \
             f'If it says a click is needed, run <code>python eurobasket.py --login</code> on the Mac.'
    else:
        eb = "Eurobasket has not run yet."
    top = rows[0] if rows else None
    lead = (f"{len(rows)} game{'s' if len(rows) != 1 else ''} yesterday. Top scorer: <b>{html.escape(top[1])}</b>, {top[0]} pts ({html.escape(top[3])})."
            if rows else "None of our players played yesterday.")
    title = f"SWNT daily · {dt.date.fromisoformat(day):%a %b %-d}"
    page = f"""<div style="font:14px Arial;color:#1b1517;max-width:900px">
<h2 style="font:700 20px Arial;color:#ba0c2f;margin:0 0 6px">{title}</h2>
<p style="margin:0 0 12px">{lead}</p>
{f'<div style="overflow-x:auto"><table style="border-collapse:collapse;width:100%"><tr>{head}</tr>{body}</table></div>' if rows else ''}
<p style="margin:16px 0 4px"><a href="{SITE}" style="color:#ba0c2f">Open the SWNT Tracker</a> for 7-day stats, season averages and player views.</p>
<p style="margin:0;color:#6c6064;font-size:12px">{eb} Data through {d["data_through"]} (NCAA/WNBA via ESPN; overseas via Hudl InStat and Eurobasket).</p></div>"""
    return title, page


def main():
    title, page = build()
    if "--dry-run" in sys.argv:
        (ROOT / "email.html").write_text(page)
        print("wrote email.html:", title)
        return
    sender, pw = os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"]
    to = [x.strip() for x in os.environ.get("EMAIL_TO", sender).split(",") if x.strip()]
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = title, sender, ", ".join(to)
    msg.attach(MIMEText(page, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(sender, pw)
        s.sendmail(sender, to, msg.as_string())
    print("sent:", title, "to", len(to), "recipient(s)")


if __name__ == "__main__":
    main()
