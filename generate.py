#!/usr/bin/env python3
"""Write a static HTML table of deadlines from JSON.

Usage: generate.py [deadlines.json] [index.html] [--all]
Without --all, deadlines in the past are omitted, unless their author response
period is still ahead. If a conference has no
upcoming deadline, an estimate is added: the latest known one, moved by whole
years into the future.

JSON format: [{"conf", "round", "deadline": "YYYY-MM-DD", "location", "url", "response"?}]
("response" = start of the author response period)
"""
import datetime as dt
import html
import glob
import json
import os
import sys
from zoneinfo import ZoneInfo

args = [a for a in sys.argv[1:] if not a.startswith("--")]
show_all = "--all" in sys.argv
src = args[0] if args else "deadlines.json"
dst = args[1] if len(args) > 1 else "index.html"

# fills the "Left" column in the browser (months + days); stays empty without JS
SCRIPT = """\
var now = new Date();
var t = new Date(now.getFullYear(), now.getMonth(), now.getDate());
document.querySelectorAll("td.left [data-date]").forEach(function (td) {
  var p = td.dataset.date.split("-");
  var d = new Date(+p[0], p[1] - 1, +p[2]);
  if (d < t) { td.textContent = "past"; return; }
  var m = (d.getFullYear() - t.getFullYear()) * 12 + d.getMonth() - t.getMonth();
  var a = new Date(t.getFullYear(), t.getMonth() + m, t.getDate());
  if (a > d) { m--; a = new Date(t.getFullYear(), t.getMonth() + m, t.getDate()); }
  var days = Math.round((d - a) / 86400000);
  td.textContent = (m ? m + "mo " : "") + days + "d";
});
// relative time of the last download, appended after the absolute one
var el = document.getElementById("dl");
if (el && el.dateTime) {
  var h = Math.round((now - new Date(el.dateTime)) / 3600000);
  el.insertAdjacentText("afterend", " (" + (h < 1 ? "just now" : h < 48 ? h + "h ago" : Math.round(h / 24) + "d ago") + ")");
}"""

today = dt.date.today().isoformat()
# last download = newest file in the cache (files are only written when fetched)
mtimes = [os.path.getmtime(p) for p in glob.glob("cache/**", recursive=True) if os.path.isfile(p)]
dl_time = dt.datetime.fromtimestamp(max(mtimes), ZoneInfo("Europe/Berlin")) if mtimes else None
downloaded = ('<time id="dl" datetime="%s">%s</time>' % (dl_time.isoformat(), dl_time.strftime("%Y-%m-%d %H:%M %Z"))
              if dl_time else "never")


def pretty(iso):
    d = dt.date.fromisoformat(iso)
    suffix = "th" if 11 <= d.day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(d.day % 10, "th")
    return f"{d:%b} {d.day}{suffix}"

COUNTRIES = {"United States": "US", "United States of America": "US", "USA": "US",
             "United Kingdom": "UK", "The Netherlands": "Netherlands"}


def short_location(loc):
    """"Atlanta, Georgia, United States" -> "Atlanta, US": city and country only."""
    parts = [p.strip() for p in (loc or "").split(",")]
    if len(parts) > 2:
        parts = [parts[0], parts[-1]]
    return ", ".join(COUNTRIES.get(p, p) for p in parts)


def shift_year(iso, years):
    d = dt.date.fromisoformat(iso)
    try:
        return d.replace(year=d.year + years).isoformat()
    except ValueError:  # Feb 29
        return d.replace(year=d.year + years, day=28).isoformat()


events = json.load(open(src, encoding="utf-8"))
# Estimate: if the latest known deadline of a (conference, round) is past,
# assume the same date again, in the first future year. Not while the response
# period of the passed one is ahead: that row stays instead, so each shows once.
latest = {}
for e in events:
    k = (e["conf"], e.get("round"))
    if k not in latest or e["deadline"] > latest[k]["deadline"]:
        latest[k] = e
estimates = []
for e in latest.values():
    if e["deadline"] < today and (e.get("response") or "") < today:
        n = 1
        while shift_year(e["deadline"], n) < today:
            n += 1
        estimates.append(dict(e, deadline=shift_year(e["deadline"], n), estimated=True,
                              location=None,
                              response=shift_year(e["response"], n) if e.get("response") else None))
# a passed deadline stays visible while its (known) response period is still ahead
rows = [e for e in events
        if show_all or e["deadline"] >= today or (e.get("response") or "") >= today] + estimates
hidden = len(events) - len([e for e in rows if not e.get("estimated")])
rows.sort(key=lambda e: e["deadline"])

esc = html.escape
out = ["<!DOCTYPE html>", '<html lang="en"><head><meta charset="utf-8">',
       "<title>Deadlines</title>", "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
       "<style>body { font-family: sans-serif; margin: 0.5em; } table { border-collapse: collapse; }"
       " td, th { padding: 4px; border: 1px solid #ccc; text-align: left; vertical-align: top; } tr.est { color: #888; } small { display: block; color: #888; }</style></head><body>", "<h1>Deadlines</h1>",
       f"<p>Data downloaded {downloaded}."
       + (f" {hidden} past deadlines hidden." if hidden else "") + "</p>",
       "<table>",
       "<tr><th>Conference<br><small>Location</small></th><th>Deadline<br><small>Response</small></th><th>Left</th></tr>"]
for e in rows:
    name = esc(e["conf"] + (" " + e["round"] if e.get("round") else ""))
    if e.get("url"):
        name = f'<a href="{esc(e["url"], quote=True)}">{name}</a>'
    loc = f"<small>{esc(short_location(e['location']))}</small>" if e.get("location") else ""
    out.append(f"<tr{' class=\"est\"' if e.get('estimated') else ''}><td>{name}{loc}</td>"
               f"<td>{'~' if e.get('estimated') else ''}{pretty(e['deadline'])}"
               + (f"<small>{'~' if e.get('estimated') else ''}{pretty(e['response'])}</small>" if e.get("response") else "")
               + "</td>"
               f"<td class=\"left\"><span data-date=\"{esc(e['deadline'])}\"></span>"
               + (f"<small data-date=\"{esc(e['response'])}\"></small>" if e.get("response") else "")
               + "</td></tr>")
out += ["</table>", "<script>", SCRIPT, "</script>", "</body></html>"]
open(dst, "w", encoding="utf-8").write("\n".join(out) + "\n")
print(f"wrote {len(rows)} rows to {dst}")
