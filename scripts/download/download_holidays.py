#!/usr/bin/env python3

import csv
import sys
import time
import logging
from datetime import date
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter

try:
    from urllib3.util.retry import Retry
except ImportError:  # older urllib3 versions
    from requests.packages.urllib3.util.retry import Retry  # type: ignore


# --------------------------------------------------------------------------- #
# Output paths (relative to project root)
# --------------------------------------------------------------------------- #

SCRIPT_DIR = Path(__file__).resolve().parent

# scripts/download -> main-folder
PROJECT_ROOT = SCRIPT_DIR.parents[2]

OUTPUT_DIR = PROJECT_ROOT / "data" / "raw" / "holidays"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PUBLIC_CSV = OUTPUT_DIR / "public_holidays.csv"
SCHOOL_CSV = OUTPUT_DIR / "school_holidays.csv"


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
YEAR_START = 2020
YEAR_END = 2027            # inclusive
LANGUAGE = "EN"            # language for labels (desired: English)
REQUEST_PAUSE = 0.20       # politeness delay between requests (seconds)
TIMEOUT = 30               # seconds per request

NAGER_BASE = "https://date.nager.at/api/v3"
OPEN_BASE = "https://openholidaysapi.org"

PUBLIC_CSV = "public_holidays.csv"
SCHOOL_CSV = "school_holidays.csv"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("holidays")


# --------------------------------------------------------------------------- #
# HTTP session with automatic retry/backoff
# --------------------------------------------------------------------------- #
def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=1.0,            # 0s, 1s, 2s, 4s, 8s
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update({"accept": "application/json"})
    return session


def get_json(session: requests.Session, url: str, params: dict | None = None):
    """GET with delay and error handling. Returns parsed JSON or None."""
    time.sleep(REQUEST_PAUSE)
    try:
        resp = session.get(url, params=params, timeout=TIMEOUT)
    except requests.RequestException as exc:
        log.warning("Request failed %s (%s): %s", url, params, exc)
        return None

    if resp.status_code == 404:
        return None  # no data for this country/year
    if resp.status_code != 200:
        log.warning("HTTP %s for %s (%s)", resp.status_code, url, params)
        return None
    try:
        return resp.json()
    except ValueError:
        log.warning("Response is not valid JSON: %s (%s)", url, params)
        return None


# --------------------------------------------------------------------------- #
# Helper functions
# --------------------------------------------------------------------------- #
def pick_name(name_field, language: str = LANGUAGE) -> str:
    """OpenHolidays returns names as list [{language, text}, ...]."""
    if not name_field:
        return ""
    for entry in name_field:
        if entry.get("language", "").upper() == language.upper():
            return entry.get("text", "")
    return name_field[0].get("text", "")  # fallback: first available name


def three_year_windows(start: int, end: int):
    """Yields (validFrom, validTo) windows of max. 3 years.
    OpenHolidays allows max. 3-year ranges per request."""
    y = start
    while y <= end:
        chunk_end = min(y + 2, end)
        yield f"{y}-01-01", f"{chunk_end}-12-31"
        y = chunk_end + 1


# --------------------------------------------------------------------------- #
# 1) PUBLIC HOLIDAYS  ->  Nager
# --------------------------------------------------------------------------- #
PUBLIC_FIELDS = [
    "country_code",
    "country_name",
    "year",
    "date",
    "name",
    "local_name",
    "is_global",
    "subdivision_code",
    "types",
    "fixed",
    "launch_year",
]


def fetch_public_holidays(session: requests.Session) -> list[dict]:
    countries = get_json(session, f"{NAGER_BASE}/AvailableCountries") or []
    log.info("Nager: %d countries available", len(countries))

    rows: list[dict] = []
    for i, c in enumerate(countries, 1):
        code = c.get("countryCode")
        name = c.get("name", "")
        log.info("[Public holidays %d/%d] %s (%s)", i, len(countries), name, code)

        for year in range(YEAR_START, YEAR_END + 1):
            data = get_json(session, f"{NAGER_BASE}/PublicHolidays/{year}/{code}")
            if not data:
                continue
            for h in data:
                base = {
                    "country_code": code,
                    "country_name": name,
                    "year": year,
                    "date": h.get("date", ""),
                    "name": h.get("name", ""),
                    "local_name": h.get("localName", ""),
                    "is_global": h.get("global", False),
                    "types": ";".join(h.get("types") or []),
                    "fixed": h.get("fixed", False),
                    "launch_year": h.get("launchYear") or "",
                }
                counties = h.get("counties")
                if counties:
                    for county in counties:
                        row = dict(base)
                        row["subdivision_code"] = county
                        rows.append(row)
                else:
                    row = dict(base)
                    row["subdivision_code"] = ""
                    rows.append(row)
    return rows


# --------------------------------------------------------------------------- #
# 2) SCHOOL HOLIDAYS  ->  OpenHolidays
# --------------------------------------------------------------------------- #
SCHOOL_FIELDS = [
    "country_code",
    "country_name",
    "holiday_id",
    "name",
    "start_date",
    "end_date",
    "type",
    "nationwide",
    "subdivision_code",
    "subdivision_name",
]


def fetch_school_holidays(session: requests.Session) -> list[dict]:
    countries = get_json(
        session, f"{OPEN_BASE}/Countries", params={"languageIsoCode": LANGUAGE}
    ) or []
    log.info("OpenHolidays: %d countries available", len(countries))

    rows: list[dict] = []
    windows = list(three_year_windows(YEAR_START, YEAR_END))

    for i, c in enumerate(countries, 1):
        code = c.get("isoCode")
        name = pick_name(c.get("name"))
        log.info("[School holidays %d/%d] %s (%s)", i, len(countries), name, code)

        for valid_from, valid_to in windows:
            data = get_json(
                session,
                f"{OPEN_BASE}/SchoolHolidays",
                params={
                    "countryIsoCode": code,
                    "languageIsoCode": LANGUAGE,
                    "validFrom": valid_from,
                    "validTo": valid_to,
                },
            )
            if not data:
                continue
            for h in data:
                base = {
                    "country_code": code,
                    "country_name": name,
                    "holiday_id": h.get("id", ""),
                    "name": pick_name(h.get("name")),
                    "start_date": h.get("startDate", ""),
                    "end_date": h.get("endDate", ""),
                    "type": h.get("type", ""),
                    "nationwide": h.get("nationwide", False),
                }
                subdivisions = h.get("subdivisions") or []
                if subdivisions:
                    for sub in subdivisions:
                        row = dict(base)
                        row["subdivision_code"] = sub.get("code", "")
                        row["subdivision_name"] = sub.get("shortName", "")
                        rows.append(row)
                else:
                    row = dict(base)
                    row["subdivision_code"] = ""
                    row["subdivision_name"] = ""
                    rows.append(row)
    return rows


# --------------------------------------------------------------------------- #
# CSV writing
# --------------------------------------------------------------------------- #
def write_csv(path: str, fieldnames: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    log.info("-> %s written (%d rows)", path, len(rows))


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    log.info("Time range: %d-%d, language: %s", YEAR_START, YEAR_END, LANGUAGE)
    session = build_session()

    public_rows = fetch_public_holidays(session)
    write_csv(PUBLIC_CSV, PUBLIC_FIELDS, public_rows)

    school_rows = fetch_school_holidays(session)
    write_csv(SCHOOL_CSV, SCHOOL_FIELDS, school_rows)

    log.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())