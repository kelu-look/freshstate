"""
Realistic evaluation — query actual retrieval systems and measure staleness.

This is the PRIMARY evaluation in the paper (exposed retrievers with full top-k).

Systems supported (no Bing key required):
  - brave:         Brave Search API — 2,000 req/month FREE, best quality
                   Sign up: https://api.search.brave.com/  → set BRAVE_API_KEY
  - ddg:           DuckDuckGo HTML scraping — zero cost, no key needed (rate-limited)
  - tavily:        Tavily API — 1,000 credits/month FREE, designed for LLM retrieval
                   Sign up: https://app.tavily.com/  → set TAVILY_API_KEY
  - bing:          Bing Web Search API (optional, better quota)
  - bing_no_fresh: Bing without freshness hint (ablation)
  - google:        Google Custom Search API (100 req/day free)

Recommended free setup for the paper:
  export BRAVE_API_KEY=...   # 2000 req/month, covers 200 examples × top-10

Usage:
    python evaluate_retrieval.py \
        --data data/apartments.jsonl data/products.jsonl \
        --system brave \
        --output results/eval_brave.jsonl \
        --fetch_pages
"""

import argparse
import json
import os
import time
from dataclasses import asdict
from pathlib import Path

import requests

from schema import FreshStateRecord
from metrics import RetrievalResult, QueryResult, label_result, aggregate
from wayback_client import fetch_live
from label import values_match


# ─────────────────────────────────────────────
#  Search API wrappers
# ─────────────────────────────────────────────

def search_bing(query: str, top_k: int = 10) -> list[dict]:
    """Query Bing Web Search API. Returns list of {rank, url, snippet}."""
    api_key = os.environ.get("BING_API_KEY")
    if not api_key:
        raise EnvironmentError("BING_API_KEY not set")

    resp = requests.get(
        "https://api.bing.microsoft.com/v7.0/search",
        headers={"Ocp-Apim-Subscription-Key": api_key},
        params={"q": query, "count": top_k, "responseFilter": "Webpages",
                "freshness": "Week"},   # ask Bing to prefer recent results
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    results = []
    for i, item in enumerate(data.get("webPages", {}).get("value", []), start=1):
        results.append({
            "rank":    i,
            "url":     item.get("url", ""),
            "snippet": item.get("snippet", ""),
            "date_published": item.get("datePublished", ""),
        })
    return results


def search_bing_no_freshness(query: str, top_k: int = 10) -> list[dict]:
    """Same as search_bing but without freshness hint — for ablation."""
    api_key = os.environ.get("BING_API_KEY")
    if not api_key:
        raise EnvironmentError("BING_API_KEY not set")

    resp = requests.get(
        "https://api.bing.microsoft.com/v7.0/search",
        headers={"Ocp-Apim-Subscription-Key": api_key},
        params={"q": query, "count": top_k, "responseFilter": "Webpages"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    results = []
    for i, item in enumerate(data.get("webPages", {}).get("value", []), start=1):
        results.append({
            "rank":    i,
            "url":     item.get("url", ""),
            "snippet": item.get("snippet", ""),
            "date_published": item.get("datePublished", ""),
        })
    return results


def search_google(query: str, top_k: int = 10) -> list[dict]:
    """Query Google Custom Search API. Returns list of {rank, url, snippet}."""
    api_key = os.environ.get("GOOGLE_API_KEY")
    cx      = os.environ.get("GOOGLE_CX")
    if not api_key or not cx:
        raise EnvironmentError("GOOGLE_API_KEY or GOOGLE_CX not set")

    results = []
    # Google Custom Search returns max 10 per request
    for start in range(1, min(top_k, 10) + 1, 10):
        resp = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": api_key, "cx": cx, "q": query,
                    "num": min(10, top_k - len(results)), "start": start},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("items", []):
            results.append({
                "rank":    len(results) + 1,
                "url":     item.get("link", ""),
                "snippet": item.get("snippet", ""),
                "date_published": item.get("pagemap", {}).get("metatags", [{}])[0].get("article:published_time", ""),
            })
        if len(results) >= top_k:
            break
        time.sleep(0.5)

    return results[:top_k]


def search_brave(query: str, top_k: int = 10) -> list[dict]:
    """
    Brave Search API — 2,000 free req/month, no credit card.
    Sign up: https://api.search.brave.com/
    """
    api_key = os.environ.get("BRAVE_API_KEY")
    if not api_key:
        raise EnvironmentError("BRAVE_API_KEY not set — sign up free at https://api.search.brave.com/")

    resp = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": api_key,
        },
        params={"q": query, "count": min(top_k, 20), "freshness": "pw"},  # pw = past week
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    results = []
    for i, item in enumerate(data.get("web", {}).get("results", []), start=1):
        results.append({
            "rank":           i,
            "url":            item.get("url", ""),
            "snippet":        item.get("description", ""),
            "date_published": item.get("page_age", ""),
        })
    return results[:top_k]


def search_ddg(query: str, top_k: int = 10) -> list[dict]:
    """
    DuckDuckGo HTML scraping — completely free, no key, no signup.
    Rate-limited: add sleep between calls (already handled by evaluate_query).
    Returns fewer results than API-based methods (~5 reliable results).
    """
    from bs4 import BeautifulSoup

    headers = {"User-Agent": "Mozilla/5.0 (compatible; FreshState-Research/1.0 academic)"}
    resp = requests.get(
        "https://html.duckduckgo.com/html/",
        params={"q": query, "kl": "us-en"},
        headers=headers,
        timeout=15,
    )
    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for i, (link, snippet_el) in enumerate(
        zip(soup.select("a.result__a"), soup.select("a.result__snippet")), start=1
    ):
        url = link.get("href", "")
        # DDG wraps URLs in redirects — extract real URL
        import urllib.parse
        if "uddg=" in url:
            url = urllib.parse.unquote(url.split("uddg=")[-1].split("&")[0])
        results.append({
            "rank":           i,
            "url":            url,
            "snippet":        snippet_el.get_text().strip() if snippet_el else "",
            "date_published": "",
        })
        if i >= top_k:
            break
    return results


def search_tavily(query: str, top_k: int = 10) -> list[dict]:
    """
    Tavily API — 1,000 free credits/month, designed for LLM/RAG retrieval.
    Sign up: https://app.tavily.com/
    """
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise EnvironmentError("TAVILY_API_KEY not set — sign up free at https://app.tavily.com/")

    resp = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key":       api_key,
            "query":         query,
            "max_results":   min(top_k, 10),
            "search_depth":  "basic",
            "include_raw_content": False,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    results = []
    for i, item in enumerate(data.get("results", []), start=1):
        results.append({
            "rank":           i,
            "url":            item.get("url", ""),
            "snippet":        item.get("content", ""),
            "date_published": item.get("published_date", ""),
        })
    return results[:top_k]


SEARCH_FNS = {
    "brave":            search_brave,           # FREE — recommended
    "ddg":              search_ddg,             # FREE — no key needed
    "tavily":           search_tavily,          # FREE tier
    "bing":             search_bing,
    "bing_no_fresh":    search_bing_no_freshness,
    "google":           search_google,
}


# ─────────────────────────────────────────────
#  Evaluate one query
# ─────────────────────────────────────────────

def evaluate_query(
    record: FreshStateRecord,
    system: str,
    top_k: int = 10,
    fetch_pages: bool = False,
    fetch_top_n: int = 3,
    sleep: float = 1.0,
) -> QueryResult:
    search_fn = SEARCH_FNS[system]

    raw_results = search_fn(record.query, top_k=top_k)
    time.sleep(sleep)

    retrieval_results = []
    for r in raw_results:
        rr = RetrievalResult(rank=r["rank"], url=r["url"], snippet=r["snippet"])

        # Fetch full page for top-N (enables SnippetMismatch metric)
        if fetch_pages and r["rank"] <= fetch_top_n:
            page_text = fetch_live(r["url"])
            rr.page_text = page_text[:10_000] if page_text else None
            time.sleep(sleep * 0.5)

        label_result(rr, record)
        retrieval_results.append(rr)

    return QueryResult(
        example_id=record.example_id,
        system=system,
        results=retrieval_results,
    )


# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────

def load_records(paths: list[str]) -> list[FreshStateRecord]:
    records = []
    for path in paths:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                rec = FreshStateRecord(**{k: v for k, v in d.items()
                                         if k in FreshStateRecord.__dataclass_fields__})
                # Only include examples with verified stale aggregator
                if rec.answer_current and rec.answer_stale and rec.aggregator_is_stale:
                    records.append(rec)
    return records


def main():
    parser = argparse.ArgumentParser(description="FreshState realistic retrieval evaluation")
    parser.add_argument("--data", nargs="+", required=True, help="Collected records JSONL file(s)")
    parser.add_argument("--system", required=True, choices=list(SEARCH_FNS.keys()))
    parser.add_argument("--output", required=True, help="Results JSONL output path")
    parser.add_argument("--top_k", type=int, default=10)
    parser.add_argument("--fetch_pages", action="store_true",
                        help="Fetch full page for top-3 results (needed for SnippetMismatch)")
    parser.add_argument("--fetch_top_n", type=int, default=3)
    parser.add_argument("--sleep", type=float, default=1.0)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    records = load_records(args.data)
    print(f"[eval] loaded {len(records)} stale records from {args.data}")
    if args.limit:
        records = records[:args.limit]

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    query_results = []

    with open(args.output, "w") as out:
        for i, rec in enumerate(records):
            print(f"[{i+1}/{len(records)}] {rec.example_id}: {rec.query[:60]}...")
            try:
                qr = evaluate_query(
                    rec,
                    system=args.system,
                    top_k=args.top_k,
                    fetch_pages=args.fetch_pages,
                    fetch_top_n=args.fetch_top_n,
                    sleep=args.sleep,
                )
                query_results.append(qr)

                # Serialize
                row = {
                    "example_id": qr.example_id,
                    "system":     qr.system,
                    "results":    [asdict(r) for r in qr.results],
                    "llm_answer": qr.llm_answer,
                    "answer_outcome": qr.answer_outcome,
                }
                out.write(json.dumps(row) + "\n")
                out.flush()

            except Exception as e:
                print(f"  ERROR: {e}")
                continue

    # Print summary
    summary = aggregate(query_results, system=args.system)
    print(f"\n── {args.system} ──")
    print(summary)
    print(f"[done] wrote {len(query_results)} results to {args.output}")


if __name__ == "__main__":
    main()
