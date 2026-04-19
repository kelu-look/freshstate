"""
Prospective monitor — watches candidate URLs daily and creates seeds automatically.

Run this once a day (cron or manual). When a change is detected,
a seed record is written automatically to the seeds directory.

Usage:
    # First run: initializes the state file
    python monitor.py --candidates candidates/zillow_sf.txt --domain apartment --state monitor_state.json

    # Subsequent runs (daily): detects changes, writes seeds
    python monitor.py --candidates candidates/zillow_sf.txt --domain apartment --state monitor_state.json --seeds seeds/monitored.jsonl
"""

import argparse
import json
import time
from datetime import date
from pathlib import Path

from wayback_client import fetch_live
from extractors import extract_value


def load_state(path: str) -> dict:
    if Path(path).exists():
        with open(path) as f:
            return json.load(f)
    return {}


def save_state(state: dict, path: str):
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="FreshState daily change monitor")
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--domain", required=True, choices=["apartment", "product", "software"])
    parser.add_argument("--change_type", default=None, help="Override change type (default: auto from domain)")
    parser.add_argument("--state", default="monitor_state.json", help="State file (persists last-seen values)")
    parser.add_argument("--seeds", default="seeds/monitored.jsonl", help="Output seeds file")
    parser.add_argument("--sleep", type=float, default=1.0)
    args = parser.parse_args()

    # Default change_type per domain
    if args.change_type is None:
        args.change_type = {"apartment": "price_change",
                            "product":   "price_change",
                            "software":  "spec_change"}[args.domain]

    with open(args.candidates) as f:
        candidates = [l.strip() for l in f if l.strip()]

    state = load_state(args.state)
    Path(args.seeds).parent.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()
    new_seeds = 0
    checked = 0

    with open(args.seeds, "a") as seeds_out:
        for url in candidates:
            current_html = fetch_live(url)
            if not current_html:
                time.sleep(args.sleep)
                continue

            value, span, conf = extract_value(current_html, args.domain, args.change_type)
            checked += 1

            if url in state:
                prev = state[url]
                if value and value != prev["value"]:
                    # Change detected
                    new_seeds += 1
                    example_id = f"mon_{args.domain[:3]}_{new_seeds:04d}"
                    seed = {
                        "example_id":   example_id,
                        "official_url": url,
                        "query":        f"What is the current {args.change_type.replace('_', ' ')} for {url}?",
                        "change_type":  args.change_type,
                        "T_before":     prev["date"].replace("-", ""),
                        "answer_stale": prev["value"],
                        "_detected_on": today,
                    }
                    seeds_out.write(json.dumps(seed) + "\n")
                    seeds_out.flush()
                    print(f"  ✓ CHANGE: {url[:60]} | {prev['value']!r} → {value!r}")

            # Update state
            if value:
                state[url] = {"value": value, "date": today, "conf": conf}

            time.sleep(args.sleep)

    save_state(state, args.state)
    print(f"[monitor] checked {checked} URLs, found {new_seeds} new changes → {args.seeds}")
    print(f"[monitor] state saved to {args.state} ({len(state)} URLs tracked)")


if __name__ == "__main__":
    main()
