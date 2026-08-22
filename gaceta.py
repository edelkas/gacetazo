#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Downloader for La Gaceta de la RSME (https://gaceta.rsme.es).

Builds a local archive of the journal: one folder per volume, one subfolder
per issue, plus a sitemap.json describing everything that was found.
"""

import json
import os
import re
import sys
from optparse import OptionParser

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://gaceta.rsme.es/"
INDEX_URL = BASE_URL + "otrosnumeros.php"

USER_AGENT = (
    "Mozilla/5.0 (compatible; gaceta-archiver/0.1; "
    "+https://gaceta.rsme.es/) Python-requests"
)

# "Volumen 29 (2026)" -> (29, 2026)
VOLUME_RE = re.compile(r"Volumen\s+(\d+)\s*\((\d{4})\)")
# "Número 1" -> 1
ISSUE_RE = re.compile(r"N\w*mero\s+(\d+)")
# "Pág. 271-518" -> (271, 518); kept loose, any number range will do
PAGES_RE = re.compile(r"(\d+)\s*[-‐-―]\s*(\d+)")
# a handful of issues carry an extra volume served by versuplemento.php
SUPPLEMENT_RE = re.compile(r"versuplemento\.php")


def log(options, message):
    """Print progress information unless running quietly."""
    if not options.quiet:
        print(message)


def fetch(url):
    """Retrieve a URL and return its decoded body."""
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    return response.text


def absolute(href):
    """Turn a site-relative href such as './portadas/x.jpg' into a full URL."""
    from urllib.parse import urljoin

    return urljoin(BASE_URL, href)


def parse_issue(td):
    """Extract one issue from a <td> of a 'listanumeros' table.

    Returns None for the filler cells that carry no issue link.
    """
    anchor = td.find("a", href=re.compile(r"vernumero\.php"))
    if anchor is None:
        return None

    match = ISSUE_RE.search(anchor.get_text(" ", strip=True))
    if match is None:
        return None

    image = td.find("img")
    cover = absolute(image["src"]) if image and image.get("src") else None

    issue = {
        "num": int(match.group(1)),
        "cover": cover,
        "link": absolute(anchor["href"]),
    }

    supplement = td.find("a", href=SUPPLEMENT_RE)
    if supplement is not None:
        issue["sup"] = absolute(supplement["href"])

    # Page range, usually written "Pág. 271-518". The issue label is dropped
    # first so a heading like "Número 1" can never open a spurious range.
    label = anchor.get_text(" ", strip=True)
    text = td.get_text(" ", strip=True).replace(label, " ", 1)
    pages = PAGES_RE.search(text)
    if pages is not None:
        issue["page_start"] = int(pages.group(1))
        issue["page_end"] = int(pages.group(2))

    return issue


def parse_index(html):
    """Parse otrosnumeros.php into a list of volume dictionaries.

    The page lays out each volume as a <div class='barravolano'> header
    followed by a <table class='listanumeros'> of issues, so we walk the
    document in order and pair every header with the table that follows it.
    """
    soup = BeautifulSoup(html, "html.parser")

    volumes = []
    pending = None

    for element in soup.find_all(["div", "table"]):
        classes = element.get("class") or []

        if element.name == "div" and "barravolano" in classes:
            match = VOLUME_RE.search(element.get_text(" ", strip=True))
            pending = None
            if match:
                pending = {
                    "num": int(match.group(1)),
                    "year": int(match.group(2)),
                    "issues": [],
                }

        elif element.name == "table" and "listanumeros" in classes:
            if pending is None:
                continue
            for td in element.find_all("td"):
                issue = parse_issue(td)
                if issue is not None:
                    pending["issues"].append(issue)
            pending["issues"].sort(key=lambda issue: issue["num"])
            volumes.append(pending)
            pending = None

    volumes.sort(key=lambda volume: volume["num"])
    return volumes


def volume_dirname(volume):
    """Folder name for a volume, e.g. 'Vol 01 (1998)'."""
    return "Vol %02d (%d)" % (volume["num"], volume["year"])


def build_tree(volumes, options):
    """Create the volume/issue folder structure under the output root."""
    created = 0

    for volume in volumes:
        volume_path = os.path.join(options.output, volume_dirname(volume))

        for issue in volume["issues"]:
            issue_path = os.path.join(volume_path, str(issue["num"]))
            if os.path.isdir(issue_path):
                continue
            if not options.dry_run:
                os.makedirs(issue_path)
            created += 1
            log(options, "  created %s" % issue_path)

    return created


def write_sitemap(volumes, options):
    """Write sitemap.json in the output root."""
    path = os.path.join(options.output, "sitemap.json")
    sitemap = {"volumes": volumes}

    if not options.dry_run:
        if not os.path.isdir(options.output):
            os.makedirs(options.output)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(sitemap, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

    return path


def do_sitemap(options):
    """Fetch the index, lay out the folders and write the sitemap."""
    log(options, "Fetching %s ..." % INDEX_URL)
    volumes = parse_index(fetch(INDEX_URL))

    if not volumes:
        sys.stderr.write("error: no volumes found; the page layout may have changed\n")
        return 1

    issues = sum(len(volume["issues"]) for volume in volumes)
    log(options, "Found %d volumes, %d issues." % (len(volumes), issues))

    created = build_tree(volumes, options)
    log(options, "Created %d new issue folders." % created)

    path = write_sitemap(volumes, options)
    log(options, "Wrote %s" % path)

    if options.dry_run:
        log(options, "(dry run: nothing was written to disk)")

    return 0


def main(argv):
    parser = OptionParser(
        usage="usage: %prog [options]",
        description=(
            "Archive La Gaceta de la RSME. Run with --sitemap to build the "
            "volume/issue folder structure and sitemap.json."
        ),
        version="%prog 0.1",
    )
    parser.add_option(
        "-s", "--sitemap",
        action="store_true", default=False,
        help="fetch the volume index, create the folder tree and write sitemap.json",
    )
    parser.add_option(
        "-o", "--output",
        metavar="DIR", default=".",
        help="root folder for the archive [default: %default]",
    )
    parser.add_option(
        "-n", "--dry-run",
        action="store_true", default=False,
        help="report what would be done without creating or writing anything",
    )
    parser.add_option(
        "-q", "--quiet",
        action="store_true", default=False,
        help="suppress progress output",
    )

    options, args = parser.parse_args(argv)

    if args:
        parser.error("unexpected argument: %s" % args[0])

    if not options.sitemap:
        parser.print_help()
        return 0

    try:
        return do_sitemap(options)
    except requests.RequestException as error:
        sys.stderr.write("error: could not fetch the site: %s\n" % error)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
