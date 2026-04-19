"""
Given an official URL or entity name, find the aggregator page for the same entity.

Strategy:
  1. Extract entity name/address from the official page.
  2. Query a search API (Bing or SerpAPI) for the entity name + aggregator domain.
  3. Return the best matching aggregator URL.

Requires either:
  - BING_API_KEY env var (free tier: 1000 req/month)
  - SERPAPI_KEY env var (free tier: 100 req/month)

Falls back to DuckDuckGo HTML scraping if no API key is set (slower, less reliable).
"""

import os
import re
import time
import requests
from typing import Optional
from bs4 import BeautifulSoup


# Known aggregator domains per domain
AGGREGATORS = {
    "apartment": ["zillow.com", "trulia.com", "apartments.com", "realtor.com", "redfin.com"],
    "product":   ["amazon.com", "shopping.google.com", "walmart.com", "bestbuy.com"],
}


# ─────────────────────────────────────────────
#  Bing Search API
# ─────────────────────────────────────────────

def _search_bing(query: str, top_n: int = 5) -> list[dict]:
    """Return list of {title, url, snippet} from Bing Web Search API."""
    api_key = os.environ.get("BING_API_KEY")
    if not api_key:
        return []

    url = "https://api.bing.microsoft.com/v7.0/search"
    headers = {"Ocp-Apim-Subscription-Key": api_key}
    params = {"q": query, "count": top_n, "responseFilter": "Webpages"}

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        results = []
        for item in data.get("webPages", {}).get("value", []):
            results.append({
                "title": item.get("name", ""),
                "url": item.get("url", ""),
                "snippet": item.get("snippet", ""),
            })
        return results
    except Exception as e:
        print(f"[bing] search failed: {e}")
        return []


# ─────────────────────────────────────────────
#  SerpAPI
# ─────────────────────────────────────────────

def _search_serpapi(query: str, top_n: int = 5) -> list[dict]:
    """Return list of {title, url, snippet} from SerpAPI Google Search."""
    api_key = os.environ.get("SERPAPI_KEY")
    if not api_key:
        return []

    url = "https://serpapi.com/search"
    params = {"q": query, "api_key": api_key, "num": top_n, "engine": "google"}

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        results = []
        for item in data.get("organic_results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            })
        return results
    except Exception as e:
        print(f"[serpapi] search failed: {e}")
        return []


# ─────────────────────────────────────────────
#  Brave Search API (free tier — recommended)
# ─────────────────────────────────────────────

def _search_brave(query: str, top_n: int = 5) -> list[dict]:
    """2,000 free req/month. Sign up: https://api.search.brave.com/"""
    api_key = os.environ.get("BRAVE_API_KEY")
    if not api_key:
        return []
    try:
        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"Accept": "application/json", "X-Subscription-Token": api_key},
            params={"q": query, "count": top_n},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("description", "")}
            for r in data.get("web", {}).get("results", [])
        ]
    except Exception as e:
        print(f"[brave] search failed: {e}")
        return []


# ─────────────────────────────────────────────
#  DuckDuckGo fallback (HTML scraping, no API key)
# ─────────────────────────────────────────────

def _search_ddg(query: str, top_n: int = 5) -> list[dict]:
    """Scrape DuckDuckGo HTML results. No API key required but rate-limited."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; FreshState-Research/1.0)"}
    params = {"q": query, "kl": "us-en"}
    try:
        resp = requests.get("https://html.duckduckgo.com/html/", params=params,
                            headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for a in soup.select("a.result__a")[:top_n]:
            results.append({
                "title": a.get_text(),
                "url": a.get("href", ""),
                "snippet": "",
            })
        return results
    except Exception as e:
        print(f"[ddg] search failed: {e}")
        return []


# ─────────────────────────────────────────────
#  Entity name extraction from official page
# ─────────────────────────────────────────────

def extract_entity_name(html: str) -> Optional[str]:
    """
    Best-effort extraction of entity name (property name or product name)
    from official page HTML.
    """
    soup = BeautifulSoup(html, "html.parser")

    # OG title is usually the cleanest
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        return og["content"].strip()

    # Page title (strip site name suffix after " | " or " - ")
    title = soup.find("title")
    if title:
        text = title.get_text().strip()
        text = re.split(r"\s*[|\-–]\s*", text)[0].strip()
        return text

    # H1
    h1 = soup.find("h1")
    if h1:
        return h1.get_text().strip()[:100]

    return None


# ─────────────────────────────────────────────
#  Main: find aggregator URL
# ─────────────────────────────────────────────

def find_aggregator_url(
    official_url: str,
    official_html: str,
    domain: str,
    preferred_aggregators: Optional[list[str]] = None,
    sleep: float = 1.0,
) -> Optional[dict]:
    """
    Given an official page, find the best matching aggregator listing.

    Returns {url, aggregator_name, snippet} or None.
    """
    target_aggregators = preferred_aggregators or AGGREGATORS.get(domain, [])

    entity_name = extract_entity_name(official_html)
    if not entity_name:
        print(f"[aggregator] could not extract entity name from {official_url}")
        return None

    # Build search query: entity name + aggregator domain
    for agg_domain in target_aggregators:
        query = f'"{entity_name}" site:{agg_domain}'

        # Try search APIs in priority order (Brave is free and works well)
        results = _search_brave(query, top_n=3)
        if not results:
            results = _search_bing(query, top_n=3)
        if not results:
            results = _search_serpapi(query, top_n=3)
        if not results:
            time.sleep(sleep)
            results = _search_ddg(query, top_n=3)

        for r in results:
            url = r.get("url", "")
            if agg_domain in url:
                return {
                    "url": url,
                    "aggregator_name": agg_domain.split(".")[0].capitalize(),
                    "snippet": r.get("snippet", ""),
                }

        time.sleep(sleep)  # be polite between searches

    return None
