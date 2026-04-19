"""
FreshState data collection pipeline.

Usage:
    python collect.py --seeds seeds/apartments.jsonl --domain apartment --output data/apartments.jsonl
    python collect.py --seeds seeds/products.jsonl --domain product --output data/products.jsonl

Seeds file format (one JSON per line):
    {
      "example_id": "apt_001",
      "official_url": "https://...",
      "query": "What is the current rent for the 1BR unit at ...",
      "change_type": "price_change",
      "T_before": "20260101",         <- YYYYMMDD, date to fetch Wayback snapshot before
      "answer_stale": "$1,750/mo",    <- optional, if known in advance
      "preferred_aggregators": ["zillow.com"]   <- optional
    }
"""

import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from schema import FreshStateRecord
from wayback_client import find_snapshot, fetch_snapshot, fetch_live
from extractors import extract_value, build_snippet
from find_aggregators import find_aggregator_url
from label import apply_labels


def load_seeds(path: str) -> list[dict]:
    seeds = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                seeds.append(json.loads(line))
    print(f"[collect] loaded {len(seeds)} seeds from {path}")
    return seeds


def collect_record(seed: dict, domain: str, sleep: float = 1.5) -> FreshStateRecord:
    rec = FreshStateRecord(
        example_id=seed["example_id"],
        domain=domain,
        query=seed["query"],
        change_type=seed.get("change_type", "price_change"),
        T_before=seed.get("T_before"),
        T_query=date.today().isoformat(),
        answer_stale=seed.get("answer_stale"),
        official_url=seed["official_url"],
    )

    # ── 1. Fetch official page (current / T_query) ──────────────────────
    print(f"[{rec.example_id}] fetching official live page: {rec.official_url}")
    live_html = fetch_live(rec.official_url)
    if live_html:
        rec.official_page_fresh = live_html[:50_000]   # cap at 50k chars
        value, span, conf = extract_value(live_html, domain, rec.change_type)
        rec.answer_current = value
        rec.answer_bearing_span_official = span
        rec.official_snippet_fresh = build_snippet(live_html, domain)
        print(f"[{rec.example_id}] current value: {value!r} (conf={conf:.2f})")
    else:
        print(f"[{rec.example_id}] WARNING: could not fetch official live page")

    time.sleep(sleep)

    # ── 2. Fetch historical snapshot (T_before) via Wayback Machine ─────
    if rec.T_before:
        before_date = rec.T_before.replace("-", "")   # ensure YYYYMMDD
        print(f"[{rec.example_id}] finding Wayback snapshot before {before_date}")
        result = find_snapshot(rec.official_url, before_date=before_date)
        if result:
            ts, snapshot_url = result
            rec.wayback_snapshot_url = snapshot_url
            rec.T_before = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
            print(f"[{rec.example_id}] found snapshot: {snapshot_url}")
            stale_html = fetch_snapshot(snapshot_url)
            if stale_html:
                rec.official_page_stale = stale_html[:50_000]
                stale_value, stale_span, _ = extract_value(stale_html, domain, rec.change_type)
                if stale_value and not rec.answer_stale:
                    rec.answer_stale = stale_value
                rec.official_snippet_stale = build_snippet(stale_html, domain)
                print(f"[{rec.example_id}] stale value: {stale_value!r}")
        else:
            print(f"[{rec.example_id}] WARNING: no Wayback snapshot found before {before_date}")

    time.sleep(sleep)

    # ── 3. Compute staleness lag ─────────────────────────────────────────
    if rec.T_before and rec.T_query:
        try:
            from datetime import date as _date
            d0 = _date.fromisoformat(rec.T_before)
            d1 = _date.fromisoformat(rec.T_query)
            rec.staleness_lag_days = (d1 - d0).days
        except Exception:
            pass

    # ── 4. Find aggregator page ──────────────────────────────────────────
    if live_html:
        print(f"[{rec.example_id}] searching for aggregator page")
        agg = find_aggregator_url(
            official_url=rec.official_url,
            official_html=live_html,
            domain=domain,
            preferred_aggregators=seed.get("preferred_aggregators"),
        )
        if agg:
            rec.aggregator_url = agg["url"]
            rec.aggregator_name = agg["aggregator_name"]
            rec.aggregator_snippet = agg["snippet"]
            print(f"[{rec.example_id}] aggregator: {rec.aggregator_url}")

            # Fetch aggregator page
            time.sleep(sleep)
            agg_html = fetch_live(rec.aggregator_url)
            if agg_html:
                rec.aggregator_page = agg_html[:50_000]
                agg_value, agg_span, _ = extract_value(agg_html, domain, rec.change_type)
                rec.aggregator_value = agg_value
                rec.answer_bearing_span_aggregator = agg_span
                if not rec.aggregator_snippet or len(rec.aggregator_snippet) < 20:
                    rec.aggregator_snippet = build_snippet(agg_html, domain)
                print(f"[{rec.example_id}] aggregator value: {agg_value!r}")
                rec.aggregator_is_stale = (
                    agg_value is not None
                    and rec.answer_current is not None
                    and agg_value != rec.answer_current
                )
        else:
            print(f"[{rec.example_id}] WARNING: no aggregator found")

    time.sleep(sleep)
    return rec


def main():
    parser = argparse.ArgumentParser(description="FreshState data collection")
    parser.add_argument("--seeds", required=True, help="Path to seeds JSONL file")
    parser.add_argument("--domain", required=True, choices=["apartment", "product"])
    parser.add_argument("--output", required=True, help="Path to output JSONL file")
    parser.add_argument("--sleep", type=float, default=1.5, help="Seconds between requests")
    parser.add_argument("--limit", type=int, default=None, help="Max records to collect (for testing)")
    args = parser.parse_args()

    seeds = load_seeds(args.seeds)
    if args.limit:
        seeds = seeds[:args.limit]

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    records = []

    for i, seed in enumerate(seeds):
        print(f"\n[{i+1}/{len(seeds)}] collecting {seed['example_id']}")
        try:
            rec = collect_record(seed, domain=args.domain, sleep=args.sleep)
            records.append(rec)
        except Exception as e:
            print(f"[ERROR] {seed['example_id']}: {e}")
            continue

    # Auto-label
    print("\n[label] applying auto-labels...")
    counts = apply_labels(records)
    print(f"[label] {counts}")

    # Write output
    with open(args.output, "w") as f:
        for rec in records:
            f.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")

    print(f"\n[done] wrote {len(records)} records to {args.output}")
    needs_review = counts.get("needs_human", 0)
    if needs_review > 0:
        print(f"[annotation] {needs_review} records flagged for human review")
        print("  → filter with: jq 'select(.collection_notes | startswith(\"[NEEDS REVIEW]\"))' output.jsonl")


if __name__ == "__main__":
    main()
