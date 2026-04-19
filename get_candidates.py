"""
Generate bulk candidate URLs — pages that MIGHT change, for retrospective discovery.

You don't need to know WHICH ones changed. Just get URLs in bulk.
discover_wayback.py will find the changed ones automatically.

Sources:
  apartments:
    - Zillow search results (URL scrape, no login needed)
    - Apartments.com search results
    - Craigslist housing listings

  products:
    - Amazon category pages
    - CamelCamelCamel top price drops (already filtered to changed!)
    - Google Shopping feeds

Usage:
    python get_candidates.py --source zillow --query "San Francisco 1BR" --output candidates/zillow_sf.txt
    python get_candidates.py --source camelcamel --category "Electronics" --output candidates/amazon_electronics.txt
    python get_candidates.py --source craigslist --city "sfbay" --output candidates/craigslist_sf.txt
"""

import argparse
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup


HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FreshState-Research/1.0 academic)"}


# ─────────────────────────────────────────────
#  CamelCamelCamel — price drops (best source for products)
#  Already filtered: these are pages where price RECENTLY changed
# ─────────────────────────────────────────────

def get_camelcamel_drops(category: str = "Electronics", limit: int = 200) -> list[str]:
    """
    Scrape CamelCamelCamel recent price drops → Amazon product URLs.
    These pages are GUARANTEED to have recently changed prices.
    """
    base = "https://camelcamelcamel.com"
    category_slugs = {
        "Electronics":    "electronics",
        "Computers":      "computers",
        "Books":          "books",
        "Toys":           "toys",
        "Kitchen":        "kitchen",
        "Sports":         "sports",
        "Tools":          "tools",
        "Office":         "office-products",
    }
    slug = category_slugs.get(category, category.lower().replace(" ", "-"))
    url = f"{base}/top-price-drops/{slug}?currency=USD&percentOff=5"

    urls = []
    page = 1
    while len(urls) < limit:
        resp = requests.get(f"{url}&page={page}", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        links = soup.select("a[href*='/product/']")
        if not links:
            break
        for link in links:
            asin_match = re.search(r"/product/([A-Z0-9]{10})", link.get("href", ""))
            if asin_match:
                asin = asin_match.group(1)
                amazon_url = f"https://www.amazon.com/dp/{asin}"
                if amazon_url not in urls:
                    urls.append(amazon_url)
        page += 1
        time.sleep(1.0)

    print(f"[camelcamel] found {len(urls)} URLs in {category}")
    return urls[:limit]


# ─────────────────────────────────────────────
#  Zillow search results
# ─────────────────────────────────────────────

def get_zillow_listings(query: str = "San Francisco CA", limit: int = 200) -> list[str]:
    """
    Get Zillow listing URLs from search results.
    Note: Zillow has aggressive bot detection — use their official API if available,
    or use Wayback Machine snapshots of Zillow search pages instead.

    This function uses the Wayback CDX to find Zillow listing URLs
    that Wayback has already crawled (avoids bot detection).
    """
    from wayback_client import CDX_API

    city_slug = query.lower().replace(" ", "-").replace(",", "").replace("--", "-")
    search_url = f"zillow.com/homes/{city_slug}*"

    params = {
        "url":      search_url,
        "output":   "json",
        "fl":       "original",
        "limit":    limit * 3,          # fetch extra, filter below
        "filter":   "statuscode:200",
        "collapse": "urlkey",
        "matchType": "prefix",
    }

    try:
        resp = requests.get(CDX_API, params=params, timeout=20)
        rows = resp.json()
        if len(rows) < 2:
            print(f"[zillow] no results from Wayback CDX for {search_url}")
            return []

        urls = []
        for row in rows[1:]:    # skip header
            url = row[0]
            # Filter to individual listing pages (not search/filters)
            if re.search(r"zillow\.com/homes/for_(?:sale|rent)/\d+", url) or \
               re.search(r"zillow\.com/[a-z]+-[a-z]+-[a-z]+/\d+_zpid", url):
                if url not in urls:
                    urls.append(url)
            if len(urls) >= limit:
                break

        print(f"[zillow] found {len(urls)} listing URLs from Wayback CDX")
        return urls

    except Exception as e:
        print(f"[zillow] CDX query failed: {e}")
        return []


# ─────────────────────────────────────────────
#  Apartments.com
# ─────────────────────────────────────────────

def get_apartments_com_listings(city: str = "san-francisco-ca", limit: int = 200) -> list[str]:
    """
    Get apartment listing URLs from Wayback CDX (apartments.com).
    """
    from wayback_client import CDX_API

    search_url = f"apartments.com/{city}/*"
    params = {
        "url":      search_url,
        "output":   "json",
        "fl":       "original",
        "limit":    limit * 3,
        "filter":   "statuscode:200",
        "collapse": "urlkey",
        "matchType": "prefix",
    }

    try:
        resp = requests.get(CDX_API, params=params, timeout=20)
        rows = resp.json()
        urls = []
        for row in rows[1:]:
            url = row[0]
            # Filter to individual apartment pages (have a unit identifier)
            if re.search(r"apartments\.com/[^/]+/[^/]+-[0-9]+/", url):
                if url not in urls:
                    urls.append(url)
            if len(urls) >= limit:
                break
        print(f"[apartments.com] found {len(urls)} listing URLs from Wayback CDX")
        return urls
    except Exception as e:
        print(f"[apartments.com] CDX query failed: {e}")
        return []


# ─────────────────────────────────────────────
#  Craigslist housing
# ─────────────────────────────────────────────

def get_craigslist_listings(city: str = "sfbay", limit: int = 200) -> list[str]:
    """
    Scrape Craigslist housing listings (apartments for rent).
    These change very frequently — good hit rate for discovery.
    """
    base = f"https://{city}.craigslist.org"
    search = f"{base}/search/apa"

    urls = []
    start = 0
    while len(urls) < limit:
        resp = requests.get(f"{search}?s={start}", headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        links = soup.select("li.cl-static-search-result a")
        if not links:
            break
        for a in links:
            href = a.get("href", "")
            if "/d/" in href and href.endswith(".html"):
                full = base + href if href.startswith("/") else href
                if full not in urls:
                    urls.append(full)
        start += 120
        time.sleep(1.5)

    print(f"[craigslist] found {len(urls)} listing URLs")
    return urls[:limit]


# ─────────────────────────────────────────────
#  Apartments.com — stable complex-level pages
#  Each URL is a permanent page for an apartment complex.
#  The page content (unit prices, availability) changes weekly.
# ─────────────────────────────────────────────

def get_property_mgmt_pages(limit: int = 400) -> list[str]:
    """
    Scrape property management company websites for stable apartment pages.
    These are server-rendered, long-lived URLs with structured pricing.
    Companies: Avalon Communities, Essex Apartment Homes, Camden Living, UDR.
    """
    # Each entry: (search/sitemap URL, link selector, URL filter regex)
    sources = [
        (
            "https://www.avaloncommunities.com/apartments/",
            "a[href*='/apartments/']",
            r"https://www\.avaloncommunities\.com/[a-z\-]+/apartments/[a-z\-]+/?$",
        ),
        (
            "https://www.essexapartmenthomes.com/apartments/",
            "a[href*='/apartments/']",
            r"https://www\.essexapartmenthomes\.com/.+/apartments/.+",
        ),
        (
            "https://www.camdenliving.com/apartments/",
            "a[href*='/apartments/']",
            r"https://www\.camdenliving\.com/.+/apartments/.+",
        ),
        (
            "https://www.udr.com/apartments/",
            "a[href*='/apartments/']",
            r"https://www\.udr\.com/.+/apartments/.+",
        ),
        (
            "https://www.lincolnapts.com/apartments/",
            "a[href*='/apartments/']",
            r"https://www\.lincolnapts\.com/.+",
        ),
        (
            "https://www.equityapartments.com/apartments/",
            "a[href*='/apartments/']",
            r"https://www\.equityapartments\.com/.+/apartments/.+",
        ),
    ]

    urls = []
    for (search_url, selector, pattern) in sources:
        if len(urls) >= limit:
            break
        try:
            resp = requests.get(search_url, headers=HEADERS, timeout=20)
            if resp.status_code != 200:
                print(f"  [property-mgmt] {search_url}: status {resp.status_code}")
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            added = 0
            for a in soup.select(selector):
                href = a.get("href", "").strip()
                if not href.startswith("http"):
                    base = "/".join(search_url.split("/")[:3])
                    href = base + href
                if re.match(pattern, href) and href not in urls:
                    urls.append(href)
                    added += 1
            print(f"  [property-mgmt] {search_url.split('/')[2]}: +{added} (total {len(urls)})")
            time.sleep(2.0)
        except Exception as e:
            print(f"  [property-mgmt] {search_url}: {e}")

    print(f"[property-mgmt] collected {len(urls)} stable apartment URLs")
    return urls[:limit]


# ─────────────────────────────────────────────
#  B&H Photo — stable product pages
#  Product URLs persist indefinitely; prices change regularly.
# ─────────────────────────────────────────────

def get_rei_products(categories: list[str] = None, limit: int = 300) -> list[str]:
    """
    Scrape REI.com category pages for stable product URLs.
    REI product pages are long-lived and prices change with sales/promotions.
    """
    if categories is None:
        categories = [
            "camping-tents", "sleeping-bags-and-pads", "hiking-boots",
            "backpacks-bags/hiking-backpacks", "cycling/bikes",
            "climbing/climbing-shoes", "kayaks-and-paddling/kayaks",
        ]

    base = "https://www.rei.com"
    rei_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/122.0.0.0 Safari/537.36",
    }
    urls = []

    for cat in categories:
        if len(urls) >= limit:
            break
        try:
            resp = requests.get(f"{base}/c/{cat}", headers=rei_headers, timeout=30)
            if resp.status_code != 200:
                print(f"  [rei/{cat}] status {resp.status_code}")
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.select("a[href*='/product/']"):
                href = a.get("href", "").strip()
                if not href.startswith("http"):
                    href = base + href
                # Canonical REI product URL: /product/NNNNNN/name
                m = re.match(r"(https://www\.rei\.com/product/\d+/[^/?#]+)", href)
                if m and m.group(1) not in urls:
                    urls.append(m.group(1))
            print(f"  [rei/{cat}] {len(urls)} total so far")
            time.sleep(2.0)
        except Exception as e:
            print(f"  [rei/{cat}]: {e}")

    print(f"[rei] collected {len(urls)} stable product URLs")
    return urls[:limit]


# ─────────────────────────────────────────────
#  GitHub Releases — software version pages
#  Each repo's /releases/latest page redirects to the current version.
#  Using /releases (listing page) gives a stable URL whose content changes on each release.
# ─────────────────────────────────────────────

def get_github_releases(limit: int = 200) -> list[str]:
    """
    Collect GitHub repository release pages for active open-source projects.
    The /releases page is stable but its content (latest version, date) changes on each release.
    Uses GitHub's public search API — no auth token needed for modest usage.
    """
    api = "https://api.github.com/search/repositories"
    gh_headers = {
        "User-Agent": "FreshState-Research/1.0 (academic benchmark)",
        "Accept": "application/vnd.github+json",
    }

    queries = [
        "language:python stars:>1000 pushed:>2025-01-01",
        "language:javascript stars:>1000 pushed:>2025-01-01",
        "language:go stars:>500 pushed:>2025-01-01",
        "language:rust stars:>500 pushed:>2025-01-01",
    ]

    urls = []
    for q in queries:
        if len(urls) >= limit:
            break
        try:
            resp = requests.get(api,
                params={"q": q, "sort": "updated", "per_page": 50},
                headers=gh_headers, timeout=10)
            if resp.status_code == 403:
                print(f"  [github] rate limited on query: {q}")
                break
            for repo in resp.json().get("items", []):
                full_name = repo.get("full_name", "")
                if full_name:
                    url = f"https://github.com/{full_name}/releases"
                    if url not in urls:
                        urls.append(url)
            time.sleep(1.0)
        except Exception as e:
            print(f"  [github] query failed: {e}")

    print(f"[github] collected {len(urls)} release pages")
    return urls[:limit]


# ─────────────────────────────────────────────
#  Wikipedia Recent Changes (for fact-based domains)
# ─────────────────────────────────────────────

def get_wikipedia_recent_changes(limit: int = 200, namespaces: str = "0") -> list[str]:
    """
    Get Wikipedia pages that changed recently (via MediaWiki API).
    Good for: sports records, population figures, company valuations, etc.
    Every URL here is GUARANTEED to have changed recently.
    """
    api = "https://en.wikipedia.org/w/api.php"
    params = {
        "action":   "query",
        "list":     "recentchanges",
        "rctype":   "edit",
        "rclimit":  min(limit, 500),
        "rcprop":   "title|timestamp|sizes",
        "rcnamespace": namespaces,
        "format":   "json",
    }
    try:
        headers = {"User-Agent": "FreshState-Research/1.0 (academic benchmark; https://github.com/freshstate)"}
        resp = requests.get(api, params=params, timeout=10, headers=headers)
        data = resp.json()
        urls = []
        for rc in data.get("query", {}).get("recentchanges", []):
            title = rc["title"].replace(" ", "_")
            urls.append(f"https://en.wikipedia.org/wiki/{title}")
        print(f"[wikipedia] found {len(urls)} recently changed pages")
        return urls
    except Exception as e:
        print(f"[wikipedia] API failed: {e}")
        return []


# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────

SOURCES = {
    "camelcamel":       "products with recent Amazon price drops (best product source)",
    "zillow":           "Zillow apartment listings (via Wayback CDX)",
    "apartments":       "Apartments.com listings (via Wayback CDX)",
    "property-mgmt":    "Property management co. pages (Avalon/Essex/Camden) — stable, structured prices",
    "craigslist":       "Craigslist housing listings (very dynamic, high expiration)",
    "rei":              "REI.com product pages — stable URLs, changing prices (recommended)",
    "github-releases":  "GitHub release pages — stable URLs, version string changes on each release",
    "wikipedia":        "Wikipedia pages changed today (for fact-based domains)",
}


def main():
    parser = argparse.ArgumentParser(description="Get candidate URLs for FreshState discovery")
    parser.add_argument("--source", required=True, choices=list(SOURCES.keys()),
                        help="\n".join(f"  {k}: {v}" for k, v in SOURCES.items()))
    parser.add_argument("--query",    default="San Francisco CA", help="City/query (zillow)")
    parser.add_argument("--city",     default="sfbay",            help="Craigslist city slug")
    parser.add_argument("--category", default="Electronics",      help="CamelCamelCamel category")
    parser.add_argument("--output",   required=True,              help="Output text file (one URL per line)")
    parser.add_argument("--limit",    type=int, default=300,      help="Max URLs to collect")
    args = parser.parse_args()

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)

    if args.source == "camelcamel":
        urls = get_camelcamel_drops(args.category, args.limit)
    elif args.source == "zillow":
        urls = get_zillow_listings(args.query, args.limit)
    elif args.source == "apartments":
        city_slug = args.query.lower().replace(" ", "-").replace(", ", "-").replace(",", "")
        urls = get_apartments_com_listings(city_slug, args.limit)
    elif args.source == "property-mgmt":
        urls = get_property_mgmt_pages(limit=args.limit)
    elif args.source == "craigslist":
        urls = get_craigslist_listings(args.city, args.limit)
    elif args.source == "rei":
        urls = get_rei_products(limit=args.limit)
    elif args.source == "github-releases":
        urls = get_github_releases(limit=args.limit)
    elif args.source == "wikipedia":
        urls = get_wikipedia_recent_changes(args.limit)
    else:
        urls = []

    with open(args.output, "w") as f:
        for url in urls:
            f.write(url + "\n")

    print(f"[done] wrote {len(urls)} candidate URLs to {args.output}")


if __name__ == "__main__":
    main()
