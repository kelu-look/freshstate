"""
One-time setup for the FreshState 3-5 day monitoring run.

Run this once today. It will:
  1. Find ~300 stable apartment/product listing URLs via Wayback CDX
     (pages Wayback has seen for 30+ days = stable, not expired)
  2. Do an initial fetch to record current prices (baseline)
  3. Print the cron command to run monitor.py daily

Usage:
    python setup_monitor.py
    python setup_monitor.py --domains apartment product   # both domains
    python setup_monitor.py --n 200                       # fewer candidates
"""

import argparse
import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from wayback_client import CDX_API, fetch_live
from extractors import extract_value


HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FreshState-Research/1.0 academic)"}


# ─────────────────────────────────────────────
#  Find stable listing URLs via Wayback CDX
#  "stable" = seen by Wayback 30+ days ago AND still alive today
# ─────────────────────────────────────────────

STABLE_PATTERNS = {
    "apartment": [
        # Official apartment complex websites — trailing wildcards only (CDX limitation)
        "www.avaloncommunities.com/apartments/",
        "www.equityapartments.com/apartments/",
        "www.essexapartmenthomes.com/apartments/",
        "www.udr.com/apartments/",
        "www.camdenliving.com/apartments/",
        # Listing aggregators with tighter paths to avoid CDX timeout
        "www.apartments.com/los-angeles-ca/",
        "www.apartments.com/new-york-ny/",
        "www.apartments.com/chicago-il/",
        "www.rent.com/california/apartments/",
        "www.rent.com/new-york/apartments/",
    ],
    "product": [
        # Small retailers — trailing wildcards only (CDX limitation)
        "www.bhphotovideo.com/c/product/",
        "www.bhphotovideo.com/c/buy/",
        "www.adorama.com/products/",
        "www.newegg.com/p/",
        "shop.lego.com/en-us/product/",
        "www.rei.com/product/",
    ],
}


def get_stable_urls_via_cdx(
    pattern: str,
    min_age_days: int = 45,
    limit: int = 100,
    sleep: float = 1.5,
) -> list[str]:
    """
    Find URLs that Wayback crawled at least min_age_days ago.
    These are likely stable (not expired listings).
    """
    cutoff = (datetime.now() - timedelta(days=min_age_days)).strftime("%Y%m%d")
    params = {
        "url":       pattern,
        "output":    "json",
        "fl":        "original",
        "limit":     limit * 3,
        "filter":    "statuscode:200",
        "collapse":  "urlkey",
        "matchType": "prefix",
        "to":        cutoff,           # only URLs seen BEFORE cutoff = stable
    }
    try:
        resp = requests.get(CDX_API, params=params, timeout=20)
        resp.raise_for_status()
        rows = resp.json()
        urls = list({row[0] for row in rows[1:] if row[0]})
        time.sleep(sleep)
        return urls[:limit]
    except Exception as e:
        print(f"  [cdx] {pattern}: {e}")
        time.sleep(sleep)
        return []


def collect_candidates(domain: str, n: int = 300) -> list[str]:
    """Collect stable listing URLs for a domain."""
    patterns = STABLE_PATTERNS.get(domain, [])
    all_urls = []
    per_pattern = max(50, n // max(len(patterns), 1))

    print(f"\n[candidates:{domain}] fetching from {len(patterns)} patterns...")
    for pat in patterns:
        if len(all_urls) >= n:
            break
        urls = get_stable_urls_via_cdx(pat, limit=per_pattern)
        all_urls.extend(u for u in urls if u not in all_urls)
        print(f"  {pat[:60]}: +{len(urls)} urls (total {len(all_urls)})")

    # Deduplicate and clean
    seen = set()
    clean = []
    for u in all_urls:
        # Normalize: remove query strings for apartments
        base = u.split("?")[0].rstrip("/")
        if base not in seen and len(base) > 20:
            seen.add(base)
            clean.append(base)

    print(f"[candidates:{domain}] {len(clean)} stable URLs collected")
    return clean[:n]


# ─────────────────────────────────────────────
#  Initial baseline fetch
#  Record current value for each URL so monitor.py can detect changes
# ─────────────────────────────────────────────

def build_baseline(
    urls: list[str],
    domain: str,
    change_type: str,
    state_path: str,
    sleep: float = 1.2,
    max_fails: int = 20,
) -> dict:
    """
    Fetch each URL and record the current value.
    Writes to state_path (used by monitor.py).
    Returns the state dict.
    """
    existing = {}
    if Path(state_path).exists():
        with open(state_path) as f:
            existing = json.load(f)

    today = datetime.now().date().isoformat()
    state = dict(existing)
    fails = 0
    new_baselines = 0

    print(f"\n[baseline] fetching {len(urls)} URLs for initial state...")
    print(f"  (already have {len(existing)} in state, skipping those)")

    for i, url in enumerate(urls):
        if url in state:
            continue
        if fails >= max_fails:
            print(f"  [baseline] stopping after {max_fails} consecutive failures")
            break

        html = fetch_live(url)
        if not html:
            fails += 1
            time.sleep(sleep)
            continue
        fails = 0

        value, span, conf = extract_value(html, domain, change_type)
        if value and conf >= 0.5:
            state[url] = {"value": value, "date": today, "conf": conf}
            new_baselines += 1
            if new_baselines % 10 == 0:
                print(f"  [{i+1}/{len(urls)}] {new_baselines} baselines recorded...")
                # Save incrementally
                with open(state_path, "w") as f:
                    json.dump(state, f)

        time.sleep(sleep)

    with open(state_path, "w") as f:
        json.dump(state, f)

    print(f"[baseline] done: {new_baselines} new baselines, {len(state)} total in state")
    return state


# ─────────────────────────────────────────────
#  Main setup
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="FreshState monitor setup")
    parser.add_argument("--domains", nargs="*", default=["apartment"],
                        choices=["apartment", "product", "software"])
    parser.add_argument("--n",       type=int, default=300,
                        help="Target number of candidate URLs per domain")
    parser.add_argument("--skip_baseline", action="store_true",
                        help="Skip initial baseline fetch (faster, for re-running setup)")
    args = parser.parse_args()

    Path("candidates").mkdir(exist_ok=True)
    Path("seeds").mkdir(exist_ok=True)
    Path("data").mkdir(exist_ok=True)

    change_type = {
        "apartment": "price_change",
        "product":   "price_change",
        "software":  "spec_change",
    }

    setup_summary = []

    for domain in args.domains:
        ctype = change_type[domain]
        candidates_path = f"candidates/{domain}_stable.txt"
        state_path      = f"monitor_state_{domain}.json"
        seeds_path      = f"seeds/{domain}_monitored.jsonl"

        print(f"\n{'='*55}")
        print(f"Setting up {domain} domain")
        print(f"{'='*55}")

        # Step 1: Get stable URLs
        if Path(candidates_path).exists():
            with open(candidates_path) as f:
                urls = [l.strip() for l in f if l.strip()]
            print(f"[candidates] loaded {len(urls)} existing URLs from {candidates_path}")
        else:
            urls = collect_candidates(domain, n=args.n)
            with open(candidates_path, "w") as f:
                f.write("\n".join(urls) + "\n")
            print(f"[candidates] saved to {candidates_path}")

        if not urls:
            print(f"[warning] no URLs found for {domain} — skipping")
            continue

        # Step 2: Build baseline
        if not args.skip_baseline:
            state = build_baseline(
                urls, domain=domain, change_type=ctype,
                state_path=state_path,
            )
            priced = len(state)
        else:
            priced = len(json.load(open(state_path))) if Path(state_path).exists() else 0
            print(f"[baseline] skipped — {priced} URLs already in state")

        setup_summary.append({
            "domain":          domain,
            "candidates_path": candidates_path,
            "state_path":      state_path,
            "seeds_path":      seeds_path,
            "n_candidates":    len(urls),
            "n_baselined":     priced,
        })

    # Print daily run command
    print(f"\n{'='*55}")
    print("SETUP COMPLETE")
    print(f"{'='*55}\n")

    for s in setup_summary:
        print(f"Domain: {s['domain']}")
        print(f"  {s['n_candidates']} candidates, {s['n_baselined']} with baseline prices\n")

    print("── Run this command once per day (or add to cron) ──────────")
    for s in setup_summary:
        print(f"python monitor.py \\")
        print(f"    --candidates {s['candidates_path']} \\")
        print(f"    --domain {s['domain']} \\")
        print(f"    --state {s['state_path']} \\")
        print(f"    --seeds {s['seeds_path']}")
        print()

    print("── Add to cron (run at 9am daily) ──────────────────────────")
    cwd = os.getcwd()
    for s in setup_summary:
        cmd = (
            f"0 9 * * * cd {cwd} && python monitor.py "
            f"--candidates {s['candidates_path']} "
            f"--domain {s['domain']} "
            f"--state {s['state_path']} "
            f"--seeds {s['seeds_path']} "
            f">> logs/monitor_{s['domain']}.log 2>&1"
        )
        print(cmd)
    print()
    print("── Check progress at any time ──────────────────────────────")
    print("python check_progress.py")


if __name__ == "__main__":
    main()
