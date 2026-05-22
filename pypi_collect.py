"""
Retrospective PyPI change-event collector.

For each candidate package, fetch https://pypi.org/pypi/{name}/json (full
release history) and identify "latest stable" version changes inside a
recent N-day window.

"Latest stable" is the highest non-prerelease version (per PEP 440)
whose upload time is on or before the cutoff. We use packaging.version
for parsing.

Output (same schema as existing FreshState seeds):
  - seeds.jsonl    (one change event per line)
  - state.json     (URL -> latest extracted value, date, conf)
  - extraction_failures.jsonl  (packages with no parseable stable)
"""
import argparse
import datetime as dt
import json
import time
from collections import Counter
from pathlib import Path
from typing import Optional

import requests
from packaging.version import Version, InvalidVersion


PYPI_JSON = "https://pypi.org/pypi/{name}/json"
HEADERS = {
    "User-Agent": "FreshState-Research/1.0 (academic; pypi-feasibility-branch)",
    "Accept": "application/json",
}


def fetch_pypi(name: str, retries: int = 3, sleep: float = 0.5) -> Optional[dict]:
    for attempt in range(retries):
        try:
            r = requests.get(PYPI_JSON.format(name=name), headers=HEADERS, timeout=15)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == retries - 1:
                print(f"  [error] {name}: {e}")
                return None
            time.sleep(sleep * (attempt + 1))
    return None


def latest_stable_at(release_map: dict, cutoff: dt.date) -> tuple[Optional[str], Optional[dt.date]]:
    """Highest non-prerelease version whose first upload was on/before cutoff.
    Returns (version_string, upload_date) or (None, None)."""
    best = None  # (Version, date_str, raw_str)
    for raw, artifacts in release_map.items():
        if not artifacts:
            continue
        try:
            v = Version(raw)
        except InvalidVersion:
            continue
        if v.is_prerelease or v.is_devrelease:
            continue
        # earliest upload time among artifacts
        times = [a.get("upload_time_iso_8601") or a.get("upload_time")
                 for a in artifacts if a]
        times = [t for t in times if t]
        if not times:
            continue
        upload = min(times)
        try:
            uploaded = dt.date.fromisoformat(upload[:10])
        except ValueError:
            continue
        if uploaded > cutoff:
            continue
        if best is None or v > best[0]:
            best = (v, uploaded, raw)
    if best is None:
        return None, None
    return best[2], best[1]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--candidates", default="candidates/pypi_top_1000.txt")
    p.add_argument("--days", type=int, default=10,
                   help="Length of the retrospective monitoring window.")
    p.add_argument("--end_date", default=None,
                   help="YYYY-MM-DD final day of the window (default: today).")
    p.add_argument("--sleep", type=float, default=0.15,
                   help="Sleep between PyPI requests (PyPI rate-limits at 30 r/s).")
    p.add_argument("--seeds_out", default="seeds/pypi_monitored.jsonl")
    p.add_argument("--state_out", default="monitor_state_pypi.json")
    p.add_argument("--fail_out",  default="data/pypi_extraction_failures.jsonl")
    p.add_argument("--limit", type=int, default=None,
                   help="(For dev) cap the number of packages to query.")
    args = p.parse_args()

    candidates = [l.strip() for l in open(args.candidates) if l.strip()]
    if args.limit:
        candidates = candidates[: args.limit]

    end_date = (dt.date.fromisoformat(args.end_date) if args.end_date
                else dt.date.today())
    window_start = end_date - dt.timedelta(days=args.days - 1)
    print(f"[plan] {len(candidates)} packages, window {window_start} -> {end_date} ({args.days} days)")

    Path(args.seeds_out).parent.mkdir(parents=True, exist_ok=True)
    seeds = []
    state = {}
    failures = []
    failure_counter = Counter()
    stats = Counter()

    for i, name in enumerate(candidates, 1):
        if i % 50 == 0:
            print(f"  [{i}/{len(candidates)}] events={len(seeds)} failures={len(failures)}")
        meta = fetch_pypi(name)
        if not meta:
            failures.append({"name": name, "reason": "404_or_error"})
            failure_counter["404_or_error"] += 1
            time.sleep(args.sleep)
            continue
        releases = meta.get("releases") or {}
        if not releases:
            failures.append({"name": name, "reason": "no_releases"})
            failure_counter["no_releases"] += 1
            time.sleep(args.sleep)
            continue

        # Walk day-by-day through the window
        prev_day = window_start - dt.timedelta(days=1)
        v_prev, d_prev = latest_stable_at(releases, prev_day)
        if v_prev is None:
            failures.append({"name": name, "reason": "no_stable_before_window"})
            failure_counter["no_stable_before_window"] += 1
            time.sleep(args.sleep)
            continue

        # baseline for state
        url = f"https://pypi.org/project/{name}/"
        state[url] = {"value": v_prev, "date": prev_day.isoformat(), "conf": 0.99}

        events_for_this_pkg = 0
        for k in range(args.days):
            check_day = window_start + dt.timedelta(days=k)
            v_now, d_now = latest_stable_at(releases, check_day)
            if v_now is None:
                continue
            if v_now != v_prev:
                events_for_this_pkg += 1
                seed = {
                    "example_id":   f"mon_pypi_{len(seeds)+1:04d}",
                    "official_url": url,
                    "change_type":  "spec_change",
                    "T_before":     prev_day.strftime("%Y%m%d"),
                    "answer_stale": v_prev,
                    "_detected_on": check_day.isoformat(),
                }
                seeds.append(seed)
                v_prev = v_now
                prev_day = check_day
                state[url] = {"value": v_now, "date": check_day.isoformat(),
                              "conf": 0.99}

        if events_for_this_pkg == 0:
            stats["unchanged"] += 1
        else:
            stats["changed"] += 1
        time.sleep(args.sleep)

    # Write outputs
    with open(args.seeds_out, "w") as f:
        for s in seeds:
            f.write(json.dumps(s) + "\n")
    Path(args.state_out).write_text(json.dumps(state, indent=2))
    with open(args.fail_out, "w") as f:
        for fail in failures:
            f.write(json.dumps(fail) + "\n")

    print(f"\n[done]")
    print(f"  candidates queried:       {len(candidates)}")
    print(f"  with parseable baseline:  {len(state)}")
    print(f"  packages with change:     {stats['changed']}")
    print(f"  packages unchanged:       {stats['unchanged']}")
    print(f"  total change events:      {len(seeds)}")
    print(f"  extraction failures:      {len(failures)}  ({dict(failure_counter)})")
    print(f"\n  seeds:   {args.seeds_out}")
    print(f"  state:   {args.state_out}")
    print(f"  failures: {args.fail_out}")


if __name__ == "__main__":
    main()
