"""
Construct the Task 1 (stale-evidence detection) labeled evaluation set.

Each example: (url, snippet, cached_at, query_at, domain, label)
  label = 'stale' or 'fresh'

Stale positives: one per change event (T_before, value=v_old).
Fresh negatives: drawn from URLs that did NOT change in the window,
                 with cached_at sampled to match the stale age distribution.

This makes age, domain, and metadata features non-trivial: in the
older snippet-swap setup, fresh snippets always had cached_at=today,
so age alone would attain ~100% accuracy.

Output: data/eval_task1.jsonl  (one example per line)
"""
import argparse
import datetime as dt
import json
import random
from pathlib import Path


SNIPPET_TMPL = {
    "apartment": "This apartment is listed at {value} per month.",
    "software":  "Latest release: {value}. View all releases and changelogs.",
    "pypi":      "Latest release: {value}. View on PyPI.",
}

QUERY_TMPL = {
    "apartment": "What is the current monthly rent for this listing: {url} ?",
    "software":  "What is the latest release version of {repo}?",
    "pypi":      "What is the latest stable version of {repo} on PyPI?",
}

# Per-domain monitoring window end. Apartments + GitHub were collected in
# April 2026; PyPI was added retrospectively in a later 10-day window.
WINDOW_END_BY_DOMAIN = {
    "apartment": dt.date(2026, 4, 19),
    "software":  dt.date(2026, 4, 19),
    "pypi":      dt.date(2026, 5, 17),
}
WINDOW_END = WINDOW_END_BY_DOMAIN["apartment"]   # kept for backwards compat


def _parse_yyyymmdd(s: str) -> dt.date:
    return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def _parse_iso(s: str) -> dt.date:
    return dt.date(int(s[:4]), int(s[5:7]), int(s[8:10]))


def _repo(url: str) -> str:
    if url.startswith("https://github.com/"):
        parts = url.replace("https://github.com/", "").split("/")
        return "/".join(parts[:2]) if len(parts) >= 2 else url
    if url.startswith("https://pypi.org/project/"):
        return url.replace("https://pypi.org/project/", "").rstrip("/")
    return url


def load_unique_change_events(seed_paths, state_paths):
    """Same dedup as run_experiment.py: first event per URL, both values known and distinct."""
    state = {}
    for sp in state_paths:
        if Path(sp).exists():
            state.update(json.loads(Path(sp).read_text()))

    seeds = []
    for path in seed_paths:
        if not Path(path).exists():
            continue
        for line in open(path):
            line = line.strip()
            if line:
                seeds.append(json.loads(line))

    seen = set()
    events = []
    for s in seeds:
        u = s["official_url"]
        if u in seen:
            continue
        seen.add(u)
        if u not in state:
            continue
        v_new = state[u].get("value")
        v_old = s.get("answer_stale")
        if not v_new or not v_old or v_new == v_old:
            continue
        if s.get("change_type") == "price_change":
            domain = "apartment"
        elif u.startswith("https://pypi.org/project/"):
            domain = "pypi"
        else:
            domain = "software"
        events.append({
            "url": u,
            "domain": domain,
            "v_old": v_old,
            "v_new": v_new,
            "T_before": s["T_before"],
        })
    return events, state


def build_examples_naive(events, state, rng):
    """Naive construction (ablation): one stale + one fresh per event,
    both on the SAME URL/package. Stale has cached_at=T_before;
    fresh has cached_at=query_time. Age perfectly correlates with
    label within each domain. Used only to validate that FreshState's
    age-matched construction is necessary (\\S{sec:evalset})."""
    examples = []
    for e in events:
        d = e["domain"]
        win_end = WINDOW_END_BY_DOMAIN[d]
        cached_stale = _parse_yyyymmdd(e["T_before"])
        age_days = (win_end - cached_stale).days
        examples.append({
            "url":           e["url"],
            "domain":        d,
            "snippet":       SNIPPET_TMPL[d].format(value=e["v_old"]),
            "snippet_value": e["v_old"],
            "cached_at":     cached_stale.isoformat(),
            "query_at":      win_end.isoformat(),
            "age_days":      age_days,
            "query":         QUERY_TMPL[d].format(
                                 url=e["url"], repo=_repo(e["url"])),
            "label":         "stale",
        })
        examples.append({
            "url":           e["url"],
            "domain":        d,
            "snippet":       SNIPPET_TMPL[d].format(value=e["v_new"]),
            "snippet_value": e["v_new"],
            "cached_at":     win_end.isoformat(),
            "query_at":      win_end.isoformat(),
            "age_days":      0,
            "query":         QUERY_TMPL[d].format(
                                 url=e["url"], repo=_repo(e["url"])),
            "label":         "fresh",
        })
    return examples


def build_examples(events, state, rng):
    """Build matched stale/fresh pairs.
    Stale positives: one per event.
    Fresh negatives: one per event, drawn from unchanged URLs in same domain,
                     with cached_at chosen to match the stale age."""
    changed = {e["url"] for e in events}
    unchanged_by_domain = {"apartment": [], "software": [], "pypi": []}
    for u, meta in state.items():
        if u in changed:
            continue
        if u.startswith("https://github.com/"):
            unchanged_by_domain["software"].append((u, meta))
        elif u.startswith("https://pypi.org/project/"):
            unchanged_by_domain["pypi"].append((u, meta))
        else:
            unchanged_by_domain["apartment"].append((u, meta))

    for d in unchanged_by_domain:
        rng.shuffle(unchanged_by_domain[d])
    cursor = {d: 0 for d in unchanged_by_domain}

    examples = []
    for e in events:
        d = e["domain"]
        win_end = WINDOW_END_BY_DOMAIN[d]
        # STALE positive
        cached_stale = _parse_yyyymmdd(e["T_before"])
        age_days = (win_end - cached_stale).days
        examples.append({
            "url":        e["url"],
            "domain":     d,
            "snippet":    SNIPPET_TMPL[d].format(value=e["v_old"]),
            "snippet_value": e["v_old"],
            "cached_at":  cached_stale.isoformat(),
            "query_at":   win_end.isoformat(),
            "age_days":   age_days,
            "query":      QUERY_TMPL[d].format(
                              url=e["url"], repo=_repo(e["url"])),
            "label":      "stale",
        })
        # FRESH negative — sample unchanged URL from same domain,
        # cached_at chosen so age matches the stale positive (within-domain).
        pool = unchanged_by_domain[d]
        if not pool:
            continue
        idx = cursor[d] % len(pool)
        cursor[d] += 1
        u_neg, meta_neg = pool[idx]
        cached_fresh = win_end - dt.timedelta(days=age_days)
        examples.append({
            "url":        u_neg,
            "domain":     d,
            "snippet":    SNIPPET_TMPL[d].format(value=meta_neg["value"]),
            "snippet_value": meta_neg["value"],
            "cached_at":  cached_fresh.isoformat(),
            "query_at":   win_end.isoformat(),
            "age_days":   age_days,
            "query":      QUERY_TMPL[d].format(
                              url=u_neg, repo=_repo(u_neg)),
            "label":      "fresh",
        })
    return examples


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", nargs="*", default=[
        "seeds/apartment_monitored_v2.jsonl",
        "seeds/software_monitored.jsonl",
        "seeds/pypi_monitored.jsonl",
    ])
    p.add_argument("--states", nargs="*", default=[
        "monitor_state_apartment_v2.json",
        "monitor_state_software.json",
        "monitor_state_pypi.json",
    ])
    p.add_argument("--output", default="data/eval_task1.jsonl")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--naive", action="store_true",
                   help="Ablation: build the naive eval set (same URL for "
                        "both stale and fresh; fresh always cached_at=today). "
                        "Age perfectly correlates with label.")
    args = p.parse_args()

    events, state = load_unique_change_events(args.seeds, args.states)
    print(f"[eval-set] {len(events)} unique change events")
    from collections import Counter
    by_dom = Counter(e["domain"] for e in events)
    print(f"          by domain: {dict(by_dom)}")

    rng = random.Random(args.seed)
    examples = (build_examples_naive(events, state, rng)
                if args.naive
                else build_examples(events, state, rng))

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    print(f"[eval-set] {len(examples)} examples written to {args.output}")
    # Verify balance
    from collections import Counter
    print("          label counts:", Counter(e["label"] for e in examples))
    print("          domain x label:",
          Counter((e["domain"], e["label"]) for e in examples))
    ages_stale = [e["age_days"] for e in examples if e["label"] == "stale"]
    ages_fresh = [e["age_days"] for e in examples if e["label"] == "fresh"]
    print(f"          age (stale): mean={sum(ages_stale)/len(ages_stale):.1f} days")
    print(f"          age (fresh): mean={sum(ages_fresh)/len(ages_fresh):.1f} days")


if __name__ == "__main__":
    main()
