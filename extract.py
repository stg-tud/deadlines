#!/usr/bin/env python3
"""Extract paper deadlines of the main conferences from the cached per-year
pages (cache/page_*.html, cache/dates_*.html, see sources.py) into
deadlines.json. Does no network access; run download.py first.

With --mail, also (heuristically) read the cached mailing list posts
(cache/mail/post_*.html, from download.py --mail) and print other conferences
that could be added. Web page data wins over mailing list data.

Usage: extract.py [--mail] [--out deadlines.json]
"""
import argparse
import datetime as dt
import glob
import html
import json
import re

from sources import DATES, PAGES, dates_cache, location_cache, page_url

BASE = "https://lists.seas.upenn.edu/pipermail/types-announce/"
CACHE = "cache"

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
MONTH_RE = (r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|"
            r"July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
            r"Nov(?:ember)?|Dec(?:ember)?)\.?")
DATE_RES = [  # (regex, order of groups)
    (re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + MONTH_RE + r",?\s+(\d{4})\b", re.I), "dmy"),
    (re.compile(r"\b" + MONTH_RE + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.I), "mdy"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "iso"),
]

MAIN = ["POPL", "PLDI", "OOPSLA", "ICFP", "ECOOP", "ESOP"]
# a post is about a main conference if its cleaned subject is just "<ABBR> [year]"
MAIN_RE = re.compile(r"^(?:ACM )?(?:SIGPLAN )?(%s)\b[\s'’]*(\d{2,4})?\W*$" % "|".join(MAIN), re.I)

# lines that give the deadline for submitting a paper
LABEL_RE = re.compile(r"submi|paper|deadline", re.I)
LABEL_SKIP_RE = re.compile(
    r"notif|camera|accept|decision|rebuttal|response|revis|artifact|poster|"
    r"workshop|tutorial|student|video|registration|talk|proposal|nominat|"
    r"conference dates?|publish", re.I)
ROUND_RE = re.compile(
    r"\bround\s*([12])\b|\bR([12])\b|\b(first|second)\s+(?:submission\s+)?(?:round|cycle)\b|"
    r"\bcycle\s*([12])\b", re.I)
LOC_RES = [
    re.compile(r"(?:will be |is )?(?:held|located|take place|takes place)\s+(?:in|at)\s+([^.\n(]{3,60})", re.I),
    re.compile(r"\b(?:hosted|held)\b.{0,800}?\bin\s+([A-Z][\w]+(?: [A-Z]\w+)*,\s*[A-Z]\w+)"),
    re.compile(r"^\s*(?:conference\s+)?(?:venue|location|where)\s*[:\-]\s*([^\n]{3,60})", re.I | re.M),
    # "Turin (Italy), 11-12 April 2026" / "Boston, USA, October 2026"
    re.compile(r"^\s*([A-Z][\w. ]+(?:\([A-Za-z ]+\)|,\s*[A-Z][\w. ]+)),?\s*\d{1,2}(?:\s*[-–]\s*\d{1,2})?\s+" + MONTH_RE, re.M),
]


def round_of(line):
    m = ROUND_RE.search(line)
    if not m:
        return None
    g = next(x for x in m.groups() if x).lower()
    return "R" + {"first": "1", "second": "2"}.get(g, g)


PLACE_LINE_RE = re.compile(r"^[A-Z][^\d:/@|*]{2,50},\s*[^\d:/@|*]{2,40}$")
DATE_END_RE = re.compile(r"\b20\d\d\s*\**\s*$")


def location(body):
    lines = [l.strip() for l in body.splitlines()]
    for a, b in zip(lines, lines[1:]):  # "<dates> 2026" followed by "City, Country"
        if DATE_END_RE.search(a) and PLACE_LINE_RE.match(b):
            return b
    flat = re.sub(r"\s+", " ", body)  # sentences wrap over lines
    for rx in LOC_RES:
        m = rx.search(body if rx.flags & re.M else flat)
        if m:
            loc = re.sub(r"\s+", " ", m.group(1))
            loc = re.split(r"\s+(?:co-located|from|on|during|colocated|between)\b|,?\s+\d", loc)[0]
            return loc.strip(" ,;:.-")
    return None


def extract_deadlines(body):
    """{round or None: date} - latest paper-submission date per round."""
    out, cur, pending = {}, None, None
    for line in body.splitlines():
        if not line.strip():
            continue
        found = list(parse_dates(line))
        # table layout: a bare date line, then a line with its label
        if len(found) == 1 and not re.search(r"[A-Za-z]{4}", line[:found[0][1]] + line[found[0][2]:]):
            pending = found[0][0]
            continue
        if pending and not found and LABEL_RE.search(line) and not LABEL_SKIP_RE.search(line):
            r = round_of(line) or cur
            out[r] = max(out.get(r, pending), pending)
        if pending and not found:
            pending = None
            if round_of(line) and len(line) <= 60:
                cur = round_of(line)
            continue
        pending = None
        r = round_of(line)
        if not found:
            if r and len(line) <= 60:  # a round heading; applies to the following date lines
                cur = r
            continue
        if not LABEL_RE.search(line) or LABEL_SKIP_RE.search(line):
            continue
        # "Round 1 deadline X and Round 2 deadline Y": one date per round
        segs, prev = [], 0
        for d, s, en in found:
            segs.append((round_of(line[prev:en]), d))
            prev = en
        if len(found) > 1 and all(r for r, _ in segs):
            pairs = segs
        else:
            pairs = [(r or cur, found[-1][0])]
        for r, d in pairs:
            out[r] = max(out.get(r, d), d)
    if len(out) > 1:  # stray round-less dates (news items, sidebars) next to real rounds
        out.pop(None, None)
    return out


def parse_dates(line):
    """Yield (date, start, end) for each date found in line."""
    for rx, order in DATE_RES:
        for m in rx.finditer(line):
            g = m.groups()
            try:
                if order == "dmy":
                    d = dt.date(int(g[2]), MONTHS[g[1][:3].lower()], int(g[0]))
                elif order == "mdy":
                    d = dt.date(int(g[2]), MONTHS[g[0][:3].lower()], int(g[1]))
                else:
                    d = dt.date(int(g[0]), int(g[1]), int(g[2]))
            except ValueError:
                continue
            yield d, m.start(), m.end()


def post_body(page):
    m = re.search(r"<!--beginarticle-->(.*?)<!--endarticle-->", page, re.S)
    body = m.group(1) if m else page
    body = re.sub(r"<[^>]+>", "", body)
    return html.unescape(body)


def post_info(page):
    title = re.search(r"<TITLE>(.*?)</TITLE>", page, re.S | re.I)
    posted = re.search(r"<I>([^<]*\d{4})</I>", page)
    ts = None
    if posted:
        try:
            ts = dt.datetime.strptime(" ".join(posted.group(1).split()[:3] + [posted.group(1).split()[-1]]),
                                      "%a %b %d %Y").date().isoformat()
        except ValueError:
            pass
    return ts


def clean_name(subject):
    s = re.sub(r"\[[^\]]*(types|announce)[^\]]*\]", "", subject, flags=re.I)
    s = re.sub(r"^\s*(re|fwd?):\s*", "", s, flags=re.I)
    s = re.sub(r"\b(\d+(st|nd|rd|th)|final|last|first|second|third|extended|reminder)?\s*"
               r"(call for (papers|participation|submissions|contributions|abstracts|proposals|talks)|cfp)\b",
               "", s, flags=re.I)
    s = re.sub(r"\(?\s*deadlines? (extended|extension)\s*\)?", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" -:–—,;()")
    return s or subject


def page_text(page):
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", page, flags=re.S | re.I)
    page = re.sub(r"</(p|div|li|tr|h\d|td|th)>|<br\s*/?>", "\n", page, flags=re.I)
    page = html.unescape(re.sub(r"<[^>]+>", "", page))
    return re.sub(r"(?<=[.!?])[ \t]+(?=[A-Z(])", "\n", page)  # one sentence per line


# page header: "PLDI 2027Sat 5 - Fri 11 June 2027 Atlanta, Georgia, United States"
PAGE_LOC_RE = re.compile(r"-\s*(?:\w{3}\s+)?\d{1,2}\s+" + MONTH_RE + r"\s+20\d\d\s+([A-Z][^\n]+)")


def location_from_home(conf, edition):
    """Venue from a home page that lists "April 10-15, 2027" then the place."""
    try:
        text = page_text(open(location_cache(conf, edition), encoding="utf-8").read())
    except OSError:
        return None
    lines = [" ".join(l.split()) for l in text.splitlines() if l.strip()]
    for a, b in zip(lines, lines[1:]):
        if re.fullmatch(MONTH_RE + r"\s+\d{1,2}\s*[-–]\s*\d{1,2},?\s+20\d\d", a) and len(b) < 80:
            return b
    return None


RESPONSE_RE = re.compile(r"author response|rebuttal", re.I)


def dates_table(text, track, response=False):
    """{round or None: date} from an "Important Dates" table (When | Track | What)
    for the rows of the given track: paper deadlines, or with response=True
    the start of the author response period."""
    lines = [" ".join(l.split()) for l in text.splitlines() if l.strip()]
    out = {}
    for k in range(len(lines) - 2):
        found = list(parse_dates(lines[k]))
        if len(found) != 1 or re.search(r"[A-Za-z]{4}", lines[k][:found[0][1]] + lines[k][found[0][2]:]):
            continue  # not a bare date cell
        if lines[k + 1] != track:
            continue
        what = lines[k + 2]
        if response and RESPONSE_RE.search(what):
            r = round_of(what)
            start = found[0][0]
            m = re.match(r"(?:\w{3}\s+)?(\d{1,2})\s*-\s*(?:\w{3}\s+)?\d{1,2}\s", lines[k])
            if m:  # "Mon 7 - Thu 10 Sep 2026": the period starts on the 7th
                first = int(m.group(1))
                if first > start.day:  # range crosses a month boundary
                    start = (start.replace(day=1) - dt.timedelta(days=1))
                start = start.replace(day=first)
            out[r] = min(out.get(r, start), start)
        elif not response and LABEL_RE.search(what) and not LABEL_SKIP_RE.search(what):
            r = round_of(what)
            out[r] = max(out.get(r, found[0][0]), found[0][0])
    return out


RANGE_RE = re.compile(MONTH_RE + r"\s+(\d{1,2})(?:\s*[-–]\s*\d{1,2})?,?\s+(\d{4})", re.I)


def responses_from_text(text):
    """{round or None: start date} from call-for-papers lines like
    "Rebuttal: July 20-22, 2026" under a "Round 1:" heading."""
    out, cur = {}, None
    for line in text.splitlines():
        line = " ".join(line.split())
        if not RESPONSE_RE.match(line):
            if round_of(line) and len(line) <= 60:
                cur = round_of(line)
            continue
        m = RANGE_RE.search(line)
        if m:
            d = dt.date(int(m.group(3)), MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
            r = round_of(line) or cur
            out[r] = min(out.get(r, d), d)
    return out


def read_text(path):
    try:
        return page_text(open(path, encoding="utf-8").read())
    except OSError:
        return None


def edition_data(conf, edition):
    """({round: date}, location, {round: response date}) of one edition, from its cached pages.
    The important-dates table wins over the call-for-papers page, per round."""
    cfp = read_text(f"{CACHE}/page_{conf}_{edition}.html")
    dates = read_text(dates_cache(conf, edition)) if conf in DATES else None
    deadlines = extract_deadlines(cfp) if cfp else {}
    responses = responses_from_text(cfp) if cfp else {}
    if dates:
        responses.update(dates_table(dates, DATES[conf][1], response=True))
        if len(responses) > 1:
            responses.pop(None, None)
        table = dates_table(dates, DATES[conf][1])
        if table:
            deadlines.update(table)
            if len(deadlines) > 1:
                deadlines.pop(None, None)
    loc = None
    for text in (cfp, dates):
        m = PAGE_LOC_RE.search(text) if text else None
        if m:
            loc = " ".join(m.group(m.lastindex).split())
            break
    return deadlines, loc or location_from_home(conf, edition), responses


def page_entries(entries):
    """Entries for every edition found in the cache."""
    editions = {(c, int(re.search(r"_(\d{4})\.html", p).group(1)))
                for c, pat in [(c, f"{CACHE}/page_{c}_*.html") for c in PAGES]
                + [(c, f"{CACHE}/dates_{c}_*.html") for c in DATES]
                for p in glob.glob(pat)}
    for conf, edition in sorted(editions):
        deadlines, loc, responses = edition_data(conf, edition)
        for rnd, date in deadlines.items():
            resp = responses.get(rnd) or (responses.get(None) if len(deadlines) == 1 else None)
            entries[(conf, edition, rnd)] = {
                "conf": conf, "edition": edition, "round": rnd,
                "deadline": date.isoformat(), "location": loc,
                "url": page_url(conf, edition), "posted": None,
                "response": resp.isoformat() if resp else None,
            }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="deadlines.json")
    ap.add_argument("--mail", action="store_true", help="also use the cached mailing list posts")
    args = ap.parse_args()

    entries, others = {}, set()  # (abbr, year, round) -> entry; later posts override
    for path in sorted(glob.glob(f"{CACHE}/mail/post_*.html")) if args.mail else []:
        year, pid = re.search(r"post_(\d+)_(\d+)\.html", path).groups()
        page = open(path, encoding="utf-8").read()
        title = re.search(r"<TITLE>(.*?)</TITLE>", page, re.S | re.I)
        subject = " ".join(html.unescape(title.group(1)).split()) if title else pid
        name = clean_name(subject)
        m = MAIN_RE.match(name)
        body = post_body(page)
        deadlines = extract_deadlines(body)
        if not m:
            if deadlines:
                others.add(re.sub(r"^(\s*\[[^\]]*\])+\s*", "", name).strip(" -:,[]()"))
            continue
        abbr, edition = m.group(1).upper(), m.group(2)
        edition = (2000 + int(edition)) if edition and len(edition) == 2 else int(edition or year)
        loc = location(body)
        for rnd, date in deadlines.items():
            entries[(abbr, edition, rnd)] = {
                "conf": abbr, "edition": edition, "round": rnd,
                "deadline": date.isoformat(), "location": loc,
                "url": f"{BASE}{year}/{pid}.html", "posted": post_info(page),
            }
    page_entries(entries)
    result = sorted(entries.values(), key=lambda e: e["deadline"])
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"wrote {len(result)} deadlines to {args.out}")
    if args.mail:
        print("\nOther conferences that could be added:")
        for n in sorted(others, key=str.lower):
            print("  " + n)


if __name__ == "__main__":
    main()
