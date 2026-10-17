#!/usr/bin/env python3
"""Write a static HTML table of deadlines from JSON.

Usage: generate.py [deadlines.json] [index.html] [--all]
Without --all, deadlines in the past are omitted. If a conference has no
upcoming deadline, an estimate is added: the latest known one, moved by whole
years into the future.

JSON format: [{"conf", "round", "deadline": "YYYY-MM-DD", "location", "url"}]
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
document.querySelectorAll("td.left").forEach(function (td) {
  var p = td.dataset.date.split("-");
  var d = new Date(+p[0], p[1] - 1, +p[2]);
  if (d < t) { td.textContent = "past"; return; }
  var m = (d.getFullYear() - t.getFullYear()) * 12 + d.getMonth() - t.getMonth();
  var a = new Date(t.getFullYear(), t.getMonth() + m, t.getDate());
  if (a > d) { m--; a = new Date(t.getFullYear(), t.getMonth() + m, t.getDate()); }
  var days = Math.round((d - a) / 86400000);
  td.textContent = (m ? m + "mo " : "") + days + "d";
});"""

today = dt.date.today().isoformat()
# last download = newest file in the cache (files are only written when fetched)
mtimes = [os.path.getmtime(p) for p in glob.glob("cache/**", recursive=True) if os.path.isfile(p)]
downloaded = (dt.datetime.fromtimestamp(max(mtimes), ZoneInfo("Europe/Berlin"))
              .strftime("%Y-%m-%d %H:%M %Z")
              if mtimes else "never")
def shift_year(iso, years):
    d = dt.date.fromisoformat(iso)
    try:
        return d.replace(year=d.year + years).isoformat()
    except ValueError:  # Feb 29
        return d.replace(year=d.year + years, day=28).isoformat()


events = json.load(open(src, encoding="utf-8"))
# Estimate: if the latest known deadline of a (conference, round) is past,
# assume the same date again, in the first future year.
latest = {}
for e in events:
    k = (e["conf"], e.get("round"))
    if k not in latest or e["deadline"] > latest[k]["deadline"]:
        latest[k] = e
estimates = []
for e in latest.values():
    if e["deadline"] < today:
        n = 1
        while shift_year(e["deadline"], n) < today:
            n += 1
        estimates.append(dict(e, deadline=shift_year(e["deadline"], n), estimated=True,
                              location=None))
rows = [e for e in events if show_all or e["deadline"] >= today] + estimates
hidden = len(events) - len([e for e in rows if not e.get("estimated")])
rows.sort(key=lambda e: e["deadline"])

esc = html.escape
out = ["<!DOCTYPE html>", '<html lang="en"><head><meta charset="utf-8">',
       "<title>Deadlines</title>", "<style>tr.est { color: #888; }</style></head><body>", "<h1>Deadlines</h1>",
       f"<p>Data downloaded {downloaded}."
       + (f" {hidden} past deadlines hidden." if hidden else "") + "</p>",
       "<table border=\"1\" cellpadding=\"4\">",
       "<tr><th>Conference</th><th>Location</th><th>Deadline</th><th>Left</th></tr>"]
for e in rows:
    name = esc(e["conf"] + (" " + e["round"] if e.get("round") else ""))
    if e.get("url"):
        name = f'<a href="{esc(e["url"], quote=True)}">{name}</a>'
    out.append(f"<tr{' class=\"est\"' if e.get('estimated') else ''}><td>{name}</td><td>{esc(e.get('location') or '')}</td>"
               f"<td>{esc(e['deadline'])}{' (estimated)' if e.get('estimated') else ''}</td>"
               f"<td class=\"left\" data-date=\"{esc(e['deadline'])}\"></td></tr>")
out += ["</table>", "<script>", SCRIPT, "</script>", "</body></html>"]
open(dst, "w", encoding="utf-8").write("\n".join(out) + "\n")
print(f"wrote {len(rows)} rows to {dst}")
