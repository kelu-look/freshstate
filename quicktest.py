"""
Zero-API-key smoke test for the FreshState core idea.

Uses GitHub release pages — best domain for zero-API testing because:
  - Version appears in page title AND SERP snippets ("Release v1.2.3 · owner/repo · GitHub")
  - Wayback Machine crawls GitHub heavily (no Cloudflare issues)
  - Popular repos release frequently (weekly or monthly)
  - Version extraction is reliable from the page title

Three-step test:
  1. Wayback diff:  find repos where the latest release changed between two snapshots
  2. Live check:    confirm current release on the live page
  3. DDG check:     does DDG snippet show the old or new release?

Zero API keys required. Just: pip install requests beautifulsoup4

Run:
    python quicktest.py                        # test default repos
    python quicktest.py --target 3             # stop after 3 confirmed changes
    python quicktest.py --days_apart 90        # wider Wayback window
    python quicktest.py --repos astral-sh/ruff pallets/flask   # custom repos
"""

import argparse
import re
import time
import urllib.parse
from dataclasses import dataclass
from typing import Optional

import requests
from bs4 import BeautifulSoup

from wayback_client import find_snapshot, fetch_snapshot, fetch_live


HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FreshState-Research/1.0 academic)"}

# Popular repos with frequent releases — Wayback has dense coverage for all of these
DEFAULT_REPOS = [
    "astral-sh/ruff",       # weekly releases
    "pallets/flask",
    "encode/httpx",
    "tiangolo/fastapi",
    "pydantic/pydantic",
    "openai/openai-python",
    "psf/requests",
    "pytest-dev/pytest",
    "psf/black",
    "django/django",
    "redis/redis-py",
    "celery/celery",
    "huggingface/transformers",
    "langchain-ai/langchain",
    "BerriAI/litellm",
]

VERSION_RE = re.compile(r"\bv?(\d+\.\d+(?:\.\d+)*(?:[-._]\w+)?)\b")


# ─────────────────────────────────────────────
#  Version extraction from GitHub releases page
# ─────────────────────────────────────────────

def extract_github_release(html: str) -> Optional[str]:
    """
    Extract the latest release version from a GitHub /releases page.
    The version appears in:
      - page <title>: "Releases · owner/repo · GitHub" (no version here)
      - first release h2: "v1.2.3" or "Release 1.2.3"
      - og:title of /releases/latest: "Release v1.2.3 · owner/repo · GitHub"
    """
    soup = BeautifulSoup(html, "html.parser")

    # og:title is most reliable for /releases/latest
    og = soup.find("meta", attrs={"property": "og:title"})
    if og:
        m = VERSION_RE.search(og.get("content", ""))
        if m:
            return m.group(1)

    # First h2 on /releases page (most recent release tag)
    for h2 in soup.find_all(["h2", "h1"]):
        text = h2.get_text().strip()
        m = VERSION_RE.search(text)
        if m:
            return m.group(1)

    # Page title as last resort
    title = soup.find("title")
    if title:
        m = VERSION_RE.search(title.get_text())
        if m:
            return m.group(1)

    return None


# ─────────────────────────────────────────────
#  Wayback diff for GitHub releases
# ─────────────────────────────────────────────

def find_release_change(repo: str, days_apart: int = 60) -> Optional[dict]:
    """
    Compare two Wayback snapshots of a GitHub releases/latest page.
    Returns {old_value, new_value, old_date, new_date} if the release changed.
    """
    from datetime import datetime, timedelta

    # Use /releases/latest — Wayback captures it frequently, og:title has version
    url = f"https://github.com/{repo}/releases/latest"

    now = datetime.now()
    recent_end   = now.strftime("%Y%m%d")
    recent_start = (now - timedelta(days=20)).strftime("%Y%m%d")
    old_end      = (now - timedelta(days=days_apart)).strftime("%Y%m%d")
    old_start    = (now - timedelta(days=days_apart + 45)).strftime("%Y%m%d")

    recent = find_snapshot(url, before_date=recent_end,  after_date=recent_start)
    if not recent:
        return None
    old = find_snapshot(url, before_date=old_end, after_date=old_start)
    if not old:
        return None

    recent_ts, recent_snap = recent
    old_ts,    old_snap    = old

    time.sleep(1.5)
    recent_html = fetch_snapshot(recent_snap)
    if not recent_html:
        return None
    time.sleep(1.5)
    old_html = fetch_snapshot(old_snap)
    if not old_html:
        return None

    recent_ver = extract_github_release(recent_html)
    old_ver    = extract_github_release(old_html)

    if not recent_ver or not old_ver:
        return None
    if recent_ver == old_ver:
        return None

    return {
        "old_value":    old_ver,
        "new_value":    recent_ver,
        "old_snap_url": old_snap,
        "new_snap_url": recent_snap,
        "old_date":     f"{old_ts[:4]}-{old_ts[4:6]}-{old_ts[6:8]}",
        "new_date":     f"{recent_ts[:4]}-{recent_ts[4:6]}-{recent_ts[6:8]}",
    }


# ─────────────────────────────────────────────
#  DDG search
# ─────────────────────────────────────────────

def ddg_search(query: str, n: int = 5) -> list[dict]:
    """DuckDuckGo HTML search — no API key."""
    try:
        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query, "kl": "us-en"},
            headers=HEADERS,
            timeout=15,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for i, (a, s) in enumerate(
            zip(soup.select("a.result__a"), soup.select("a.result__snippet")), start=1
        ):
            url = a.get("href", "")
            if "uddg=" in url:
                url = urllib.parse.unquote(url.split("uddg=")[-1].split("&")[0])
            results.append({"rank": i, "url": url, "snippet": s.get_text().strip()})
            if i >= n:
                break
        return results
    except Exception as e:
        print(f"  [ddg] {e}")
        return []


def snippet_contains(snippet: str, value: str) -> bool:
    if not snippet or not value:
        return False
    # Match "v1.2.3" or "1.2.3" in snippet
    v = value.lstrip("v")
    return v in snippet or ("v" + v) in snippet


# ─────────────────────────────────────────────
#  Result
# ─────────────────────────────────────────────

@dataclass
class TestResult:
    repo:        str
    url:         str
    old_value:   str
    new_value:   str
    old_date:    str
    new_date:    str
    live_value:  Optional[str]
    ddg_results: list[dict]

    def staleness_verdict(self) -> str:
        for r in self.ddg_results:
            s = r["snippet"]
            if snippet_contains(s, self.old_value) and not snippet_contains(s, self.new_value):
                return f"STALE  rank {r['rank']} shows old {self.old_value!r}"
            if snippet_contains(s, self.new_value):
                return f"FRESH  rank {r['rank']} shows new {self.new_value!r}"
        return "UNCLEAR"


def print_result(r: TestResult, i: int):
    verdict = r.staleness_verdict()
    tag = verdict.split()[0]   # STALE / FRESH / UNCLEAR
    print(f"\n  [{i}] {r.repo}")
    print(f"       Wayback: {r.old_value!r} -> {r.new_value!r}  ({r.old_date} -> {r.new_date})")
    print(f"       Live now: {r.live_value or 'not fetched'}")
    print(f"       DDG:     [{tag}] {verdict}")
    for dr in r.ddg_results[:3]:
        flag = ""
        if snippet_contains(dr["snippet"], r.old_value) and not snippet_contains(dr["snippet"], r.new_value):
            flag = " <-- STALE"
        elif snippet_contains(dr["snippet"], r.new_value):
            flag = " <-- fresh"
        print(f"         rank {dr['rank']}: \"{dr['snippet'][:95]}\"{flag}")


def print_summary(results: list[TestResult]):
    stale   = sum(1 for r in results if r.staleness_verdict().startswith("STALE"))
    fresh   = sum(1 for r in results if r.staleness_verdict().startswith("FRESH"))
    unclear = len(results) - stale - fresh
    n       = len(results)

    print(f"\n{'='*65}")
    print(f"SUMMARY  ({n} repos with verified release changes)")
    print(f"  [STALE]   DDG snippet shows old release:  {stale}/{n}")
    print(f"  [FRESH]   DDG snippet shows new release:  {fresh}/{n}")
    print(f"  [UNCLEAR] Release not found in snippets:  {unclear}/{n}")
    print(f"{'='*65}")

    if stale > 0:
        print("\nIDEA CONFIRMED: DDG surfaces stale release versions even after the repo updated.")
        print("This is exactly the FreshState signal at the snippet/retrieval layer.")
    elif fresh > 0:
        print("\nDDG is up-to-date for this sample — search index caught up already.")
        print("The Wayback mechanism still works for dataset construction.")
        print("For stronger staleness signal: run monitor.py and catch changes within 24h.")
    else:
        print("\nVersion not found in DDG snippets.")
        print("GitHub release snippets vary — try repos with tagged version releases.")


# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="FreshState zero-API smoke test (GitHub releases)")
    parser.add_argument("--repos",      nargs="*", default=DEFAULT_REPOS)
    parser.add_argument("--target",     type=int,  default=5)
    parser.add_argument("--days_apart", type=int,  default=60)
    args = parser.parse_args()

    print("FreshState smoke test — zero API keys")
    print(f"Domain:  GitHub latest releases")
    print(f"Repos:   {args.repos[:5]}{'...' if len(args.repos) > 5 else ''}")
    print(f"Window:  {args.days_apart} days apart | target: {args.target} changes")
    print()

    results = []
    checked = 0

    for repo in args.repos:
        if len(results) >= args.target:
            break
        checked += 1
        url = f"https://github.com/{repo}/releases/latest"
        print(f"[{checked}/{len(args.repos)}] {repo}")

        change = find_release_change(repo, days_apart=args.days_apart)
        if not change:
            print(f"  — no release change found in Wayback window")
            time.sleep(1.0)
            continue

        print(f"  CHANGE: {change['old_value']} -> {change['new_value']}"
              f"  ({change['old_date']} -> {change['new_date']})")

        # Verify against live page
        time.sleep(1.5)
        live_html = fetch_live(url)
        live_ver = extract_github_release(live_html) if live_html else None
        if live_ver:
            print(f"  Live:   {live_ver}")

        # DDG: GitHub release snippets often show "Release v1.2.3 · owner/repo · GitHub"
        repo_name = repo.split("/")[-1]
        query = f"{repo_name} github release"
        time.sleep(2.5)
        ddg = ddg_search(query, n=5)

        results.append(TestResult(
            repo=repo, url=url,
            old_value=change["old_value"], new_value=change["new_value"],
            old_date=change["old_date"],   new_date=change["new_date"],
            live_value=live_ver,
            ddg_results=ddg,
        ))
        time.sleep(2.0)

    print(f"\nchecked {checked} repos, found {len(results)} with verified release changes\n")

    if not results:
        print("No changes found. Try --days_apart 120 or a different set of repos.")
        return

    for i, r in enumerate(results, 1):
        print_result(r, i)

    print_summary(results)


if __name__ == "__main__":
    main()
