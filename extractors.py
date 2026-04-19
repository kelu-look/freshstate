"""
Domain-specific extractors.

Each extractor takes raw HTML and returns:
  - value: the answer-bearing value (price, availability, version, etc.)
  - span: the exact text span that contains the value
  - confidence: float 0-1

Add a new extractor for each domain/source combination.
"""

import re
from typing import Optional
from bs4 import BeautifulSoup


# ─────────────────────────────────────────────
#  Shared helpers
# ─────────────────────────────────────────────

def _clean(text: str) -> str:
    return " ".join(text.split())


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


# ─────────────────────────────────────────────
#  Price extraction (generic)
# ─────────────────────────────────────────────

PRICE_RE = re.compile(
    r"\$\s?[\d,]+(?:\.\d{2})?(?:\s?(?:/\s?mo(?:nth)?|per\s+month))?",
    re.IGNORECASE,
)

def extract_price(html: str) -> tuple[Optional[str], Optional[str], float]:
    """
    Return (normalized_price, surrounding_span, confidence).
    Tries structured selectors first, falls back to regex.
    """
    soup = _soup(html)

    # --- Try structured selectors (common listing sites) ---
    selectors = [
        "[data-testid='price']",
        ".price",
        ".listing-price",
        "#price",
        "[class*='price']",
        "[itemprop='price']",
        "span[class*='Price']",
        "div[class*='Price']",
    ]
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            text = _clean(el.get_text())
            m = PRICE_RE.search(text)
            if m:
                return _normalize_price(m.group()), text[:200], 0.9

    # --- Fallback: full-text regex ---
    text = _clean(soup.get_text(" "))
    matches = PRICE_RE.findall(text)
    if matches:
        # Return the first match and a 100-char window around it
        m = PRICE_RE.search(text)
        start = max(0, m.start() - 50)
        span = text[start:m.end() + 50]
        return _normalize_price(m.group()), span, 0.6

    return None, None, 0.0


def _normalize_price(raw: str) -> str:
    """Strip whitespace, keep $X,XXX or $X,XXX/mo format."""
    return re.sub(r"\s+", "", raw).lower().replace("permonth", "/mo").replace("/month", "/mo")


# ─────────────────────────────────────────────
#  Availability extraction (apartments)
# ─────────────────────────────────────────────

AVAIL_PATTERNS = [
    (re.compile(r"available\s+(?:now|immediately)", re.I), "available_now"),
    (re.compile(r"available\s+(\w+\s+\d+,?\s*\d{4}|\d{1,2}/\d{1,2}/\d{4})", re.I), "available_date"),
    (re.compile(r"(?:no longer|not)\s+available", re.I), "unavailable"),
    (re.compile(r"rented|leased|off\s+market", re.I), "off_market"),
    (re.compile(r"move[- ]in\s+(?:date\s*:?\s*)?(\w+\s+\d+,?\s*\d{4})", re.I), "available_date"),
]

def extract_availability(html: str) -> tuple[Optional[str], Optional[str], float]:
    """
    Return (availability_label, surrounding_span, confidence).
    """
    soup = _soup(html)
    text = _clean(soup.get_text(" "))

    # Try structured selectors first
    for sel in ["[data-testid='availability']", ".availability", "[class*='availab']"]:
        el = soup.select_one(sel)
        if el:
            t = _clean(el.get_text())
            for pattern, label in AVAIL_PATTERNS:
                if pattern.search(t):
                    return label, t[:200], 0.9

    # Fallback to full text
    for pattern, label in AVAIL_PATTERNS:
        m = pattern.search(text)
        if m:
            start = max(0, m.start() - 40)
            span = text[start:m.end() + 40]
            return label, span, 0.65

    return None, None, 0.0


# ─────────────────────────────────────────────
#  Product spec extraction (version strings, etc.)
# ─────────────────────────────────────────────

VERSION_RE = re.compile(
    r"v?(\d+\.\d+(?:\.\d+)*(?:[-_.]\w+)?)",
    re.IGNORECASE,
)

def extract_version(html: str) -> tuple[Optional[str], Optional[str], float]:
    """
    Return (version_string, surrounding_span, confidence).
    """
    soup = _soup(html)

    for sel in [".version", "[class*='version']", "[data-testid='version']", "#version"]:
        el = soup.select_one(sel)
        if el:
            text = _clean(el.get_text())
            m = VERSION_RE.search(text)
            if m:
                return m.group(), text[:200], 0.9

    text = _clean(soup.get_text(" "))
    m = VERSION_RE.search(text)
    if m:
        start = max(0, m.start() - 30)
        span = text[start:m.end() + 30]
        return m.group(), span, 0.5

    return None, None, 0.0


# ─────────────────────────────────────────────
#  Snippet builder (first 300 chars of answer-bearing region)
# ─────────────────────────────────────────────

def build_snippet(html: str, domain: str) -> str:
    """
    Build a short snippet (like a SERP preview) from a page.
    Tries to center on the answer-bearing span.
    """
    soup = _soup(html)

    # Try meta description first (often what search engines use as snippet)
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        return _clean(meta["content"])[:300]

    # Try OG description
    og = soup.find("meta", attrs={"property": "og:description"})
    if og and og.get("content"):
        return _clean(og["content"])[:300]

    # Extract around the answer-bearing span
    if domain == "apartment":
        value, span, _ = extract_price(html)
        if not value:
            value, span, _ = extract_availability(html)
    elif domain == "product":
        value, span, _ = extract_price(html)
        if not value:
            value, span, _ = extract_version(html)
    else:
        span = None

    if span:
        return span[:300]

    # Last resort: first 300 chars of body text
    text = _clean(soup.get_text(" "))
    return text[:300]


# ─────────────────────────────────────────────
#  GitHub releases extractor
#  Targets the /releases listing page, extracts the latest tag name.
# ─────────────────────────────────────────────

GITHUB_TAG_RE = re.compile(r"v?\d+\.\d+(?:\.\d+)*(?:[-_.]\w+)?", re.IGNORECASE)

def extract_github_release(html: str) -> tuple[Optional[str], Optional[str], float]:
    """
    Extract the latest release tag from a GitHub /releases page.
    Returns (tag_string, surrounding_span, confidence).
    """
    soup = _soup(html)

    # Primary: <h2 class="..."> inside the first release entry, or <a> with /releases/tag/
    for sel in [
        "a[href*='/releases/tag/']",
        "h2.f1 a",
        "[class*='release-header'] a",
    ]:
        el = soup.select_one(sel)
        if el:
            text = _clean(el.get_text())
            if GITHUB_TAG_RE.search(text):
                return text.strip(), text[:100], 0.95

    # Fallback: scan all tag-shaped links
    for a in soup.select("a[href*='/releases/tag/']"):
        text = _clean(a.get_text())
        if GITHUB_TAG_RE.search(text):
            return text.strip(), text[:100], 0.85

    # Last resort: first version-like string in page text
    text = _clean(soup.get_text(" "))
    m = GITHUB_TAG_RE.search(text)
    if m:
        start = max(0, m.start() - 20)
        span = text[start: m.end() + 20]
        return m.group(), span, 0.4

    return None, None, 0.0


# ─────────────────────────────────────────────
#  Dispatch
# ─────────────────────────────────────────────

def extract_value(html: str, domain: str, change_type: str) -> tuple[Optional[str], Optional[str], float]:
    """
    Main dispatch: extract the answer-bearing value given domain + change_type.
    Returns (value, span, confidence).
    """
    if change_type == "price_change":
        return extract_price(html)
    elif change_type == "availability_change":
        return extract_availability(html)
    elif change_type == "spec_change":
        # Try GitHub release extractor first, fall back to generic version
        value, span, conf = extract_github_release(html)
        if value:
            return value, span, conf
        return extract_version(html)
    else:
        # Try price first as default
        value, span, conf = extract_price(html)
        if value:
            return value, span, conf
        return extract_availability(html)
