"""
fetch_and_process.py

Downloads the latest UK Register of Licensed Sponsors CSV from GOV.UK,
strips it down to just the fields the search widget needs, and writes a
compact JSON file for the site to fetch directly.

Uses the GOV.UK Content API rather than scraping the HTML page, since the
CSV's own filename and URL change every time the Home Office republishes
it. The Content API always points at whatever the current attachment is,
so this script never needs updating just because GOV.UK renamed a file.
"""

import csv
import io
import json
import sys
from datetime import datetime, timezone

import requests

CONTENT_API_URL = "https://www.gov.uk/api/content/government/publications/register-of-licensed-sponsors-workers"
OUTPUT_PATH = "sponsors.json"


def get_latest_csv_url_and_date() -> tuple[str, str]:
    resp = requests.get(CONTENT_API_URL, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    attachments = data["details"].get("attachments", [])
    csv_attachments = [a for a in attachments if a.get("content_type") == "text/csv"]
    if not csv_attachments:
        raise RuntimeError(
            "No CSV attachment found on the GOV.UK publication page. "
            "The page layout may have changed, check manually."
        )
    csv_attachments.sort(key=lambda a: a.get("updated_at", ""), reverse=True)
    csv_url = csv_attachments[0]["url"]
    last_updated = data.get("public_updated_at", datetime.now(timezone.utc).isoformat())
    return csv_url, last_updated


def download_and_parse_csv(csv_url: str) -> list[dict]:
    resp = requests.get(csv_url, timeout=120)
    resp.raise_for_status()
    # The register is UTF-8 with a BOM, utf-8-sig strips it cleanly.
    text = resp.content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    return list(reader)


def find_column(fieldnames: list[str], candidates: list[str]) -> str:
    """
    The Home Office has changed these column headers before without
    warning, so match case-insensitively against a few known variants
    rather than one hardcoded string, and fail loudly with a clear error
    if none match, rather than silently writing an empty column.
    """
    lower_map = {f.lower().strip(): f for f in fieldnames}
    for candidate in candidates:
        if candidate.lower() in lower_map:
            return lower_map[candidate.lower()]
    raise RuntimeError(
        f"Could not find a matching column for {candidates} in {fieldnames}. "
        "GOV.UK may have renamed a column, check the raw CSV headers manually."
    )


def build_compact_records(rows: list[dict]) -> list[list[str]]:
    if not rows:
        return []

    fieldnames = list(rows[0].keys())
    name_col = find_column(fieldnames, ["Organisation Name", "Organisation"])
    town_col = find_column(fieldnames, ["Town/City", "Town", "City"])
    county_col = find_column(fieldnames, ["County"])
    route_col = find_column(fieldnames, ["Route"])
    rating_col = find_column(fieldnames, ["Type & Rating", "Rating"])

    records = []
    for row in rows:
        records.append([
            (row.get(name_col) or "").strip(),
            (row.get(town_col) or "").strip(),
            (row.get(county_col) or "").strip(),
            (row.get(route_col) or "").strip(),
            (row.get(rating_col) or "").strip(),
        ])
    return records


def main():
    csv_url, last_updated = get_latest_csv_url_and_date()
    print(f"Fetching CSV from: {csv_url}")
    rows = download_and_parse_csv(csv_url)
    print(f"Parsed {len(rows)} rows")

    records = build_compact_records(rows)

    output = {
        "last_updated": last_updated,
        "source": csv_url,
        "count": len(records),
        "columns": ["name", "town", "county", "route", "rating"],
        "records": records,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, separators=(",", ":"))

    print(f"Wrote {len(records)} records to {OUTPUT_PATH}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)
        sys.exit(1)
