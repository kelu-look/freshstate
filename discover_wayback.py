"""
Retrospective change discovery using Wayback Machine.

You DON'T need to know which pages changed in advance.
This script finds pages that already changed by diffing consecutive snapshots.

Algorithm:
  1. Take a list of candidate URLs (apartment listings, product pages)
     — these are easy to find in bulk from any search/scrape
  2. For each URL, fetch two Wayback snapshots ~30 days apart
  3. Extract the answer-bearing value from each snapshot
  4. If values differ → valid example → write a seed record

Usage:
    # Generate candidate URLs first (see get_candidates.py)
    python discover_wayback.py \
        --candidates candidates/zillow_urls.txt \
        --domain apartment \
        --change_type price_change \
        --output seeds/apartments_discovered.jsonl \
        --days_apart 30 \
        --limit 500
"""

import argparse
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

from wayback_client import find_snapshot, fetch_snapshot
from extractors import extract_value


def date_to_cdx(d: datetime) -> str:
    return d.strftime("%Y%m%d")


def discover_change(
    url: str,
    domain: str,
    change_type: str,
    days_apart: int = 30,
    reference_date: datetime = None,
) -> dict | None:
    """
    Check if a URL has a different value in two Wayback snapshots ~days_apart apart.

    Returns a seed dict if a change is found, None otherwise.
    """
    if reference_date is None:
        reference_date = datetime.now()

    # T_recent: snapshot from ~7 days ago (more likely to have been crawled)
    t_recent_end   = date_to_cdx(reference_date - timedelta(days=7))
    t_recent_start = date_to_cdx(reference_date - timedelta(days=21))

    # T_old: snapshot from ~(days_apart + 7) days ago
    t_old_end   = date_to_cdx(reference_date - timedelta(days=days_apart))
    t_old_start = date_to_cdx(reference_date - timedelta(days=days_apart + 30))

    # Find recent snapshot
    recent = find_snapshot(url, before_date=t_recent_end, after_date=t_recent_start)
    if not recent:
        return None
    recent_ts, recent_snap_url = recent

    # Find older snapshot
    old = find_snapshot(url, before_date=t_old_end, after_date=t_old_start)
    if not old:
        return None
    old_ts, old_snap_url = old

    # Fetch both
    recent_html = fetch_snapshot(recent_snap_url)
    if not recent_html:
        return None
    time.sleep(1.0)

    old_html = fetch_snapshot(old_snap_url)
    if not old_html:
        return None

    # Extract values
    recent_value, _, recent_conf = extract_value(recent_html, domain, change_type)
    old_value, _, old_conf = extract_value(old_html, domain, change_type)

    # Both must be extractable
    if not recent_value or not old_value:
        return None

    # Must differ
    if recent_value == old_value:
        return None

    # Found a change
    old_date = f"{old_ts[:4]}-{old_ts[4:6]}-{old_ts[6:8]}"
    recent_date = f"{recent_ts[:4]}-{recent_ts[4:6]}-{recent_ts[6:8]}"

    return {
        "official_url":    url,
        "change_type":     change_type,
        "T_before":        date_to_cdx(datetime.strptime(old_date, "%Y-%m-%d")),
        "answer_stale":    old_value,
        "answer_current":  recent_value,    # from recent Wayback snapshot (use as proxy)
        "wayback_old":     old_snap_url,
        "wayback_recent":  recent_snap_url,
        "days_apart":      days_apart,
        "confidence":      min(recent_conf, old_conf),
        "_old_date":       old_date,
        "_recent_date":    recent_date,
    }


def make_query(url: str, domain: str, change_type: str, value: str) -> str:
    """Generate a natural-language current-seeking query for a seed."""
    if domain == "apartment":
        if change_type == "price_change":
            return f"What is the current monthly rent for the apartment at {url}?"
        elif change_type == "availability_change":
            return f"Is the apartment at {url} currently available?"
    elif domain == "product":
        if change_type == "price_change":
            return f"What is the current price of the product at {url}?"
        elif change_type == "spec_change":
            return f"What is the current version of the software at {url}?"
    return f"What is the current {change_type.replace('_', ' ')} shown at {url}?"


def main():
    parser = argparse.ArgumentParser(description="Retrospective change discovery via Wayback Machine")
    parser.add_argument("--candidates", required=True, help="Text file with one URL per line")
    parser.add_argument("--domain", required=True, choices=["apartment", "product"])
    parser.add_argument("--change_type", default="price_change",
                        choices=["price_change", "availability_change", "spec_change"])
    parser.add_argument("--output", required=True, help="Output seeds JSONL")
    parser.add_argument("--days_apart", type=int, default=30,
                        help="How far apart the two snapshots should be (default: 30 days)")
    parser.add_argument("--limit", type=int, default=None, help="Max candidates to check")
    parser.add_argument("--sleep", type=float, default=2.0, help="Seconds between candidates")
    parser.add_argument("--target", type=int, default=100,
                        help="Stop after finding this many changed pages")
    args = parser.parse_args()

    # Load candidate URLs
    with open(args.candidates) as f:
        candidates = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    if args.limit:
        candidates = candidates[:args.limit]
    print(f"[discover] checking {len(candidates)} candidate URLs (target: {args.target} changes)")

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    found = 0
    checked = 0

    with open(args.output, "w") as out:
        for i, url in enumerate(candidates):
            if found >= args.target:
                print(f"[discover] reached target of {args.target} changes, stopping")
                break

            print(f"[{i+1}/{len(candidates)}] checking {url[:80]}...")
            checked += 1

            result = discover_change(
                url, domain=args.domain,
                change_type=args.change_type,
                days_apart=args.days_apart,
            )

            if result:
                found += 1
                example_id = f"{args.domain[:3]}_{found:04d}"
                seed = {
                    "example_id":  example_id,
                    "official_url": result["official_url"],
                    "query":        make_query(url, args.domain, args.change_type,
                                               result["answer_stale"]),
                    "change_type":  result["change_type"],
                    "T_before":     result["T_before"],
                    "answer_stale": result["answer_stale"],
                    "_answer_current_proxy": result["answer_current"],
                    "_wayback_old":    result["wayback_old"],
                    "_wayback_recent": result["wayback_recent"],
                    "_confidence":     result["confidence"],
                }
                out.write(json.dumps(seed, ensure_ascii=False) + "\n")
                out.flush()
                print(f"  ✓ CHANGE FOUND [{found}]: {result['answer_stale']!r} → {result['answer_current']!r}")
            else:
                print(f"  — no change detected")

            time.sleep(args.sleep)

    print(f"\n[discover] checked {checked} candidates, found {found} changes")
    print(f"[discover] seeds written to {args.output}")
    hit_rate = found / checked if checked > 0 else 0
    print(f"[discover] hit rate: {hit_rate:.1%}")
    if hit_rate < 0.05:
        print("[discover] TIP: hit rate is low — try a more dynamic domain or shorter days_apart")
