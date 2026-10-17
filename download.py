#!/usr/bin/env python3
"""Download the per-year conference pages (and optionally the types-announce
mailing list archive) into cache/ (mailing list files go to cache/mail/).

Conference pages: the call-for-papers and important-dates pages from
sources.py, for as few editions as needed: next year's; this year's if next
year's is not published yet (or may leave deadlines ahead in this year's); the
one after next if all of next year's deadlines have passed. Pages are refreshed
at most once per day; pages that do not exist yet (404) are retried at most
once per day.

With --mail, also the mailing list archive: every post is fetched at most once (cache/mail/post_<year>_<id>.html); the index
of the current year at most once per day; indexes of past years once.
Only posts whose subject looks like a call/school announcement are fetched.

Usage: download.py [--no-cache] [--mail [--years 2025 2026]]
  --no-cache  fetch everything again, ignoring (but still writing) the cache
"""
import argparse
import datetime as dt
import html
import os
import re
import time
import urllib.error
import urllib.request

from extract import edition_data
from sources import (DATES, LOCATION_PAGES, PAGES, dates_cache, dates_url, location_cache,
                     location_url, page_cache, page_url)

BASE = "https://lists.seas.upenn.edu/pipermail/types-announce/"
CACHE = "cache"
MAIL_CACHE = f"{CACHE}/mail"  # mailing list files live apart from the web pages
UA = "deadlines-extractor/0.1 (personal use)"

SUBJECT_RE = re.compile(
    r"call for|cfp|c\.f\.p|summer school|winter school|spring school|"
    r"deadline|school|workshop|conference|symposium|submission", re.I)
SUBJECT_SKIP_RE = re.compile(
    r"phd|postdoc|position|opening|vacanc|job|professor|studentship|"
    r"fellowship|lectureship|researcher|engineer", re.I)
NO_CACHE = False  # --no-cache: always fetch, ignoring what is cached


def fetch(url, path, max_age=None):
    """Return text of url, using the cache file at path.
    max_age (seconds): refetch if cache is older; None = cache forever."""
    if NO_CACHE:
        max_age = 0
    if os.path.exists(path):
        age = time.time() - os.path.getmtime(path)
        if max_age is None or age < max_age:
            return open(path, encoding="utf-8").read()
    if not NO_CACHE and os.path.exists(path + ".404") and time.time() - os.path.getmtime(path + ".404") < 24 * 3600:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:  # not published yet; remember for a day
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path + ".404", "w").close()
            return None
        print(f"warning: {url}: {e}")
        return None
    except Exception as e:
        if os.path.exists(path):  # stale cache beats nothing
            print(f"warning: {url}: {e}; using stale cache")
            return open(path, encoding="utf-8").read()
        print(f"warning: {url}: {e}")
        return None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    time.sleep(0.5)  # be polite
    return text


def list_posts(year, current_year):
    max_age = 24 * 3600 if year == current_year else None
    page = fetch(f"{BASE}{year}/date.html", f"{MAIL_CACHE}/index_{year}.html", max_age)
    if not page:
        return []
    seen, posts = set(), []
    for m in re.finditer(r'<LI><A HREF="(\d+)\.html">(.*?)</A>', page, re.S | re.I):
        pid, subj = m.group(1), " ".join(html.unescape(m.group(2)).split())
        if pid not in seen:
            seen.add(pid)
            posts.append((pid, subj))
    return posts


def download_edition(conf, year, now):
    """Fetch the pages of one edition; return its {round: date} deadlines."""
    # past editions are final; this and next year's may still change
    max_age = 24 * 3600 if year >= now else None
    fetch(page_url(conf, year), page_cache(conf, year), max_age)
    if conf in DATES:
        fetch(dates_url(conf, year), dates_cache(conf, year), max_age)
    if conf in LOCATION_PAGES:
        fetch(location_url(conf, year), location_cache(conf, year), max_age)
    return edition_data(conf, year)[0]


def download_pages(now):
    """Fetch as few editions as needed to know each conference's next deadline."""
    today = dt.date.today()
    for conf in PAGES:
        nxt = download_edition(conf, now + 1, now)
        if not nxt:  # next edition not published yet: this year's is the newest
            download_edition(conf, now, now)
            continue
        last = max(nxt.values())
        if last < today:  # all passed: the edition after it may be out already
            download_edition(conf, now + 2, now)
        else:
            try:
                year_ago = last.replace(year=last.year - 1)
            except ValueError:  # Feb 29
                year_ago = last.replace(year=last.year - 1, day=28)
            if year_ago >= today:  # this year's edition may still have deadlines ahead
                download_edition(conf, now, now)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mail", action="store_true", help="also download the mailing list archive")
    ap.add_argument("--years", nargs="*", type=int, help="mailing list years (default: last and this)")
    ap.add_argument("--no-cache", action="store_true", help="ignore the cache, fetch everything")
    args = ap.parse_args()
    global NO_CACHE
    NO_CACHE = args.no_cache
    now = dt.date.today().year
    if args.mail:
        for year in sorted(args.years or [now - 1, now]):
            for pid, subject in list_posts(year, now):
                if SUBJECT_RE.search(subject) and not SUBJECT_SKIP_RE.search(subject):
                    fetch(f"{BASE}{year}/{pid}.html", f"{MAIL_CACHE}/post_{year}_{pid}.html")
    download_pages(now)


if __name__ == "__main__":
    main()
