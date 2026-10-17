"""Conferences whose call for papers lives on a per-year web page
(not announced on the mailing list)."""

PAGES = {  # abbreviation -> url template; {yyyy} / {yy} = edition year
    "PLDI": "https://pldi{yy}.sigplan.org/track/pldi-{yyyy}-papers",
    "POPL": "https://popl{yy}.sigplan.org/track/popl-{yyyy}-popl-research-papers",
    "ICFP": "https://icfp{yy}.sigplan.org/track/icfp-{yyyy}-icfp-papers",
    "ECOOP": "https://{yyyy}.ecoop.org/track/ecoop-{yyyy}-technical-papers",
    "ESOP": "https://etaps.org/{yyyy}/conferences/esop/",
    "OOPSLA": "https://conf.researchr.org/track/splash-{yyyy}/oopsla-{yyyy}",
}


def page_url(conf, year):
    return PAGES[conf].format(yyyy=year, yy=str(year)[2:])


def page_cache(conf, year):
    return f"cache/page_{conf}_{year}.html"


# where the venue is stated if the call-for-papers page lacks it
LOCATION_PAGES = {"ESOP": "https://etaps.org/{yyyy}/"}  # ESOP is part of ETAPS


def location_url(conf, year):
    return LOCATION_PAGES[conf].format(yyyy=year, yy=str(year)[2:])


def location_cache(conf, year):
    return f"cache/location_{conf}_{year}.html"


# "Important Dates" pages: conference -> (url template, track name of the main paper track)
DATES = {
    "PLDI": ("https://pldi{yy}.sigplan.org/dates", "PLDI Research Papers"),
    "POPL": ("https://popl{yy}.sigplan.org/dates", "POPL"),
    "ICFP": ("https://icfp{yy}.sigplan.org/dates", "ICFP Papers"),
    "ECOOP": ("https://{yyyy}.ecoop.org/dates", "Technical Papers"),
    "OOPSLA": ("https://{yyyy}.splashcon.org/dates", "OOPSLA"),
}


def dates_url(conf, year):
    return DATES[conf][0].format(yyyy=year, yy=str(year)[2:])


def dates_cache(conf, year):
    return f"cache/dates_{conf}_{year}.html"
