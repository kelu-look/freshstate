"""
Wayback Machine client.

Two operations:
  1. find_snapshot(url, before_date) -> (timestamp, snapshot_url)
     Find the closest archived snapshot before a given date.

  2. fetch_snapshot(url, timestamp) -> html text
     Fetch the archived HTML at a given timestamp.
"""

import time
import requests
from datetime import datetime
from typing import Optional


CDX_API = "https://web.archive.org/cdx/search/cdx"
WAYBACK_BASE = "https://web.archive.org/web"


def find_snapshot(
    url: str,
    before_date: str,          # "YYYYMMDD"
    after_date: Optional[str] = None,   # "YYYYMMDD", optional lower bound
    retries: int = 3,
    sleep: float = 1.0,
) -> Optional[tuple[str, str]]:
    """
    Return (timestamp, snapshot_url) of the closest available snapshot
    of `url` before `before_date`.

    Returns None if no snapshot is found.
    """
    params = {
        "url": url,
        "output": "json",
        "limit": 5,
        "to": before_date,
        "fl": "timestamp,original,statuscode",
        "filter": "statuscode:200",
        "collapse": "timestamp:8",    # one per day
    }
    if after_date:
        params["from"] = after_date

    for attempt in range(retries):
        try:
            resp = requests.get(CDX_API, params=params, timeout=15)
            resp.raise_for_status()
            rows = resp.json()
            # rows[0] is the header ["timestamp", "original", "statuscode"]
            if len(rows) < 2:
                return None
            # Take the most recent snapshot before before_date
            ts, original, status = rows[-1]
            snapshot_url = f"{WAYBACK_BASE}/{ts}/{original}"
            return ts, snapshot_url
        except Exception as e:
            if attempt == retries - 1:
                print(f"[wayback] find_snapshot failed for {url}: {e}")
                return None
            time.sleep(sleep * (attempt + 1))
    return None


def fetch_snapshot(snapshot_url: str, retries: int = 3, sleep: float = 2.0) -> Optional[str]:
    """
    Fetch the raw HTML of a Wayback Machine snapshot URL.
    Returns text content or None on failure.
    """
    headers = {"User-Agent": "FreshState-Research/1.0 (academic benchmark collection)"}
    for attempt in range(retries):
        try:
            resp = requests.get(snapshot_url, timeout=30, headers=headers)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            if attempt == retries - 1:
                print(f"[wayback] fetch_snapshot failed for {snapshot_url}: {e}")
                return None
            time.sleep(sleep * (attempt + 1))
    return None


def fetch_live(url: str, retries: int = 3, sleep: float = 1.5) -> Optional[str]:
    """
    Fetch the current live page. Returns text or None.
    """
    headers = {"User-Agent": "FreshState-Research/1.0 (academic benchmark collection)"}
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=20, headers=headers)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            if attempt == retries - 1:
                print(f"[live] fetch failed for {url}: {e}")
                return None
            time.sleep(sleep * (attempt + 1))
    return None
