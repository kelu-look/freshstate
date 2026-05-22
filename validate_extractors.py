"""
Interactive manual validation for FreshState extractors.

For each sampled URL:
  1. refetch live HTML
  2. re-run the extractor
  3. open the URL in your default browser
  4. ask you (one keystroke) whether the extracted value matches the page
  5. log the answer + optional one-line failure note

Progress is saved after every sample, so you can quit (Ctrl-C or 'q')
and resume later with --resume.

At the end the script prints:
  - precision with 95% Wilson CI
  - a LaTeX table row ready to paste into the paper
  - a per-failure-mode breakdown

Usage examples:
    python validate_extractors.py --extractor price --n 100
    python validate_extractors.py --extractor github --n 100
    python validate_extractors.py --extractor expiration --n 50
    python validate_extractors.py --extractor price --n 100 --resume

After resuming a prior run, the script picks up where you left off.
"""

import argparse
import json
import math
import random
import sys
import time
import webbrowser
from collections import Counter
from datetime import datetime
from pathlib import Path

from wayback_client import fetch_live
from extractors import extract_price, extract_github_release

import requests


# ────────────────────────────────────────────────────────
#  Configurations per extractor
# ────────────────────────────────────────────────────────

EXTRACTOR_CONFIGS = {
    "price": {
        "state_path":   "monitor_state_apartment_v2.json",
        "extractor":    "extract_price",
        "label":        "Price (Craigslist)",
        "needs_browser": True,
        # Standardized failure-mode tags presented to the human judge
        # via a numbered menu when verdict == "incorrect" or "skip".
        "failure_tags": [
            "extracted_zip",
            "extracted_sqft",
            "wrong_unit",
            "parking_addon",
            "multi-price",
            "stale_amenity_price",
        ],
        "skip_tags": [
            "posting_expired",
            "blocked",
            "unreachable",
        ],
    },
    "github": {
        "state_path":   "monitor_state_software.json",
        "extractor":    "extract_github_release",
        "label":        "GitHub release tag",
        "needs_browser": True,
        "failure_tags": [
            "fork_or_star_count",
            "prerelease_picked",
            "calver_skipped",
            "not_top_release",
            "draft_release",
        ],
        "skip_tags": [
            "no_releases",
            "repo_moved",
            "repo_deleted",
            "blocked",
        ],
    },
    "expiration": {
        "state_path":   "monitor_state_apartment_v2.json",  # samples from apartment pool
        "extractor":    "expiration_check",
        "label":        "HTTP 4xx expiration",
        "needs_browser": True,
        "failure_tags": [
            "false_4xx",          # tool says expired but listing is live
            "expired_but_200",    # listing expired but HTTP 200 returned
            "expired_but_3xx",    # listing gone but redirected (rare)
        ],
        "skip_tags": [
            "blocked",
            "transient_error",
        ],
    },
}


# ────────────────────────────────────────────────────────
#  Wilson 95% CI
# ────────────────────────────────────────────────────────

def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


# ────────────────────────────────────────────────────────
#  Sample selection (deterministic by seed)
# ────────────────────────────────────────────────────────

def select_sample(state_path: str, n: int, seed: int = 42,
                  recent_first: bool = False) -> list[tuple[str, dict]]:
    state = json.loads(Path(state_path).read_text())
    items = list(state.items())
    rng = random.Random(seed)
    rng.shuffle(items)
    if recent_first:
        # Stable sort by recency (latest date first); ties keep the
        # deterministic shuffle order so the sample is still reproducible.
        items.sort(key=lambda kv: kv[1].get("date", ""), reverse=True)
    return items[:n]


# ────────────────────────────────────────────────────────
#  Per-sample probes
# ────────────────────────────────────────────────────────

def probe_extractor(url: str, kind: str) -> dict:
    """Refetch and re-extract. Returns dict with status, value, http_status, error."""
    out = {"url": url, "kind": kind}
    headers = {"User-Agent": "FreshState-Validate/1.0 (academic)"}
    try:
        resp = requests.get(url, timeout=20, headers=headers, allow_redirects=True)
        out["http_status"] = resp.status_code
    except Exception as e:
        out["http_status"] = None
        out["error"] = str(e)
        return out

    if kind == "expiration":
        # Expiration = any terminal 4xx response indicating the original
        # evidence is no longer retrievable (matches the production
        # monitor.py, which relies on requests.raise_for_status -> None
        # HTML). Validation surfaced that Craigslist commonly serves
        # 404 for removed listings, not 410, so the HTTP-410-only
        # definition was too narrow.
        sc = resp.status_code
        is_4xx = bool(sc) and 400 <= sc < 500
        out["expired"]     = is_4xx
        out["status_code"] = sc                   # retained as metadata
        out["extracted_value"] = (
            f"EXPIRED (HTTP {sc})" if is_4xx else f"NOT EXPIRED (HTTP {sc})"
        )
        out["html_length"] = len(resp.text) if resp.text else 0
        return out

    if resp.status_code != 200:
        out["extracted_value"] = None
        out["error"] = f"HTTP {resp.status_code}"
        return out

    if kind == "price":
        v, span, conf = extract_price(resp.text)
    elif kind == "github":
        v, span, conf = extract_github_release(resp.text)
    else:
        v, span, conf = (None, None, 0.0)

    out["extracted_value"] = v
    out["span"]            = span[:200] if span else None
    out["confidence"]      = conf
    return out


# ────────────────────────────────────────────────────────
#  Interactive prompt
# ────────────────────────────────────────────────────────

PROMPT_LEGEND = """
  Options:
    y  ENTER  - correct (extracted value matches page)
    n         - INCORRECT (you'll pick a failure-mode tag)
    s         - skip (not applicable: URL down, paywall, captcha, etc.)
    b         - back (undo previous judgment, re-show that URL)
    q         - quit (progress is saved)
"""


def _pick_tag(tags: list[str], prompt: str) -> str:
    """Show numbered list of tags; user picks number or types free text."""
    print(f"  {prompt}")
    for i, t in enumerate(tags, 1):
        print(f"    {i}. {t}")
    print(f"    0. (other — type free-text note)")
    raw = input("  pick: ").strip()
    if raw.isdigit():
        i = int(raw)
        if 1 <= i <= len(tags):
            return tags[i - 1]
        if i == 0:
            return input("  free-text note: ").strip()
    # If they typed free text directly, use it
    return raw


def ask_user(probe: dict, kind: str, cfg: dict) -> dict | None:
    """Returns dict with verdict and optional note, or None if user quits."""
    print("─" * 72)
    print(f"URL:        {probe['url']}")
    if probe.get("http_status") is not None:
        print(f"HTTP:       {probe['http_status']}")
    if probe.get("error"):
        print(f"Fetch err:  {probe['error']}")
    if kind == "expiration":
        print(f"Decision:   {probe.get('extracted_value')}")
        print("  Question: does the LIVE page confirm this expiration decision?")
        print("            y = decision is correct; n = decision is wrong")
    else:
        print(f"Extracted:  {probe.get('extracted_value')!r}")
        if probe.get("span"):
            print(f"Context:    {probe['span'][:140]}")
        print("  Question: does the extracted value match the value visible on the page?")
    print(PROMPT_LEGEND.strip())
    while True:
        ans = input("  [y/n/s/b/q]: ").strip().lower()
        if ans in ("", "y", "yes"):
            return {"verdict": "correct", "note": ""}
        if ans in ("n", "no"):
            note = _pick_tag(cfg["failure_tags"], "failure mode:")
            return {"verdict": "incorrect", "note": note}
        if ans == "s":
            note = _pick_tag(cfg["skip_tags"], "skip reason:")
            return {"verdict": "skip", "note": note}
        if ans == "b":
            return {"verdict": "__back__", "note": ""}
        if ans == "q":
            return None
        print("  (please type y / n / s / b / q)")


# ────────────────────────────────────────────────────────
#  Progress file (resumable)
# ────────────────────────────────────────────────────────

def load_progress(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.open()]


def save_progress(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ────────────────────────────────────────────────────────
#  Reporting
# ────────────────────────────────────────────────────────

def report(rows: list[dict], label: str) -> None:
    judged = [r for r in rows if r["verdict"] in ("correct", "incorrect")]
    skipped = [r for r in rows if r["verdict"] == "skip"]
    n = len(judged)
    correct = sum(1 for r in judged if r["verdict"] == "correct")
    lo, hi = wilson_ci(correct, n) if n else (0, 0)

    print()
    print("=" * 72)
    print(f"VALIDATION REPORT  —  {label}")
    print("=" * 72)
    print(f"  Judged:        {n}")
    print(f"  Correct:       {correct}")
    print(f"  Incorrect:     {n - correct}")
    print(f"  Skipped:       {len(skipped)}")
    if n:
        print(f"  Precision:     {correct/n*100:.1f}% "
              f"(95% Wilson CI [{lo*100:.1f}, {hi*100:.1f}])")
    if n - correct:
        print("\n  Failure-mode notes:")
        notes = Counter((r.get("note") or "(no note)")
                        for r in judged if r["verdict"] == "incorrect")
        for k, v in notes.most_common():
            print(f"    {v:2d}x  {k}")
    if skipped:
        print("\n  Skip reasons:")
        skip_notes = Counter((r.get("note") or "(no note)") for r in skipped)
        for k, v in skip_notes.most_common():
            print(f"    {v:2d}x  {k}")

    # LaTeX row for paper
    if n:
        print("\n  LaTeX row for tab:validation:")
        print(f"    {label:<24} & {n} & {correct} & "
              f"{correct/n*100:.0f}\\% [{lo*100:.1f}, {hi*100:.1f}] \\\\")


# ────────────────────────────────────────────────────────
#  Main
# ────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Interactive extractor validation.")
    p.add_argument("--extractor", required=True,
                   choices=list(EXTRACTOR_CONFIGS.keys()),
                   help="Which extractor to validate.")
    p.add_argument("--n", type=int, default=100, help="Sample size.")
    p.add_argument("--seed", type=int, default=42, help="Sampling seed (deterministic).")
    p.add_argument("--output", default=None,
                   help="Progress file (default: validation/<extractor>.jsonl)")
    p.add_argument("--resume", action="store_true",
                   help="Resume from a previous run, skip already-judged URLs.")
    p.add_argument("--no-browser", action="store_true",
                   help="Don't open URLs in browser.")
    p.add_argument("--rate-limit", type=float, default=1.0,
                   help="Sleep seconds between HTTP fetches.")
    p.add_argument("--redo", nargs="+", default=None,
                   help="Re-judge specific URL(s) that were already saved. "
                        "Drops their previous entry and re-presents them.")
    p.add_argument("--live-only", action="store_true",
                   help="Pre-fetch each URL and auto-skip non-2xx responses "
                        "without prompting; you only judge live pages. "
                        "Also prioritises URLs with the most recent baseline "
                        "date to maximise live-hit rate.")
    p.add_argument("--target-judged", type=int, default=None,
                   help="With --live-only: stop once this many live URLs have "
                        "been judged in the current session (default: --n).")
    args = p.parse_args()

    cfg = EXTRACTOR_CONFIGS[args.extractor]
    out_path = Path(args.output or f"validation/{args.extractor}.jsonl")

    done_rows = load_progress(out_path) if args.resume else []
    # --redo: pull selected URLs out of done_rows so they get re-judged
    if args.redo:
        redo_set = set(args.redo)
        kept = [r for r in done_rows if r["url"] not in redo_set]
        removed = [r["url"] for r in done_rows if r["url"] in redo_set]
        print(f"[redo] re-judging {len(removed)} URL(s): {removed}")
        done_rows = kept

    done_urls = {r["url"] for r in done_rows}
    if done_rows:
        print(f"[resume] {len(done_rows)} samples already judged in {out_path}")

    sample = select_sample(cfg["state_path"], args.n, args.seed,
                           recent_first=args.live_only)
    # Include redo URLs at the front of to_judge even if not in the deterministic sample
    sample_urls = {u for (u, _) in sample}
    if args.redo:
        # Need baseline metadata for redo URLs (fall back to live state load)
        state = json.loads(Path(cfg["state_path"]).read_text())
        redo_pairs = [(u, state.get(u, {})) for u in args.redo if u not in sample_urls]
        if redo_pairs:
            print(f"[redo] adding {len(redo_pairs)} redo URL(s) not in the random sample")
        to_judge = redo_pairs + [(u, m) for (u, m) in sample if u not in done_urls]
    else:
        to_judge = [(u, m) for (u, m) in sample if u not in done_urls]

    if not to_judge:
        print("[done] no remaining samples — printing report on existing data")
        report(done_rows, cfg["label"])
        return

    print(f"[plan] {len(to_judge)} URLs to judge "
          f"(total target {args.n}, already done {len(done_rows)})")

    rows = list(done_rows)
    i = 0
    auto_skipped = 0
    judged_this_session = 0
    target_judged = args.target_judged or args.n
    try:
        while i < len(to_judge):
            url, meta = to_judge[i]
            print(f"\n[{i+1}/{len(to_judge)}] (overall {len(rows)+1}/{args.n})")
            print(f"  baseline state: value={meta.get('value')!r} date={meta.get('date')}")
            probe = probe_extractor(url, args.extractor)

            # --live-only: auto-skip non-2xx without prompting
            if args.live_only and probe.get("http_status") not in (200, 201):
                auto_skipped += 1
                sc = probe.get("http_status")
                note = ("posting_expired" if sc and 400 <= sc < 500
                        else f"non_2xx_{sc}")
                print(f"  [auto-skip] HTTP {sc} -> {note} "
                      f"(skipped {auto_skipped} so far)")
                rows.append({
                    **probe,
                    "baseline_value": meta.get("value"),
                    "baseline_date":  meta.get("date"),
                    "verdict":        "skip",
                    "note":           note,
                    "ts":             datetime.now().isoformat(timespec="seconds"),
                    "auto":           True,
                })
                save_progress(out_path, rows)
                time.sleep(args.rate_limit)
                i += 1
                continue

            if not args.no_browser and cfg["needs_browser"]:
                webbrowser.open(url)
            ans = ask_user(probe, args.extractor, cfg)
            if ans is None:
                print("\n[quit] saving progress and exiting.")
                break
            if ans["verdict"] == "__back__":
                if not rows:
                    print("  (nothing to undo — no prior judgments in this session)")
                    continue
                last = rows.pop()
                save_progress(out_path, rows)
                print(f"  [undo] removed last judgment for {last['url']}")
                print(f"         was: {last['verdict']!r}  note={last.get('note', '')!r}")
                # Re-judge by inserting last URL at current position and stepping back
                to_judge.insert(i, (last["url"], {
                    "value": last.get("baseline_value"),
                    "date":  last.get("baseline_date"),
                }))
                continue  # i stays — same index, now points to the re-inserted URL
            rows.append({
                **probe,
                "baseline_value": meta.get("value"),
                "baseline_date":  meta.get("date"),
                "verdict":        ans["verdict"],
                "note":           ans["note"],
                "ts":             datetime.now().isoformat(timespec="seconds"),
            })
            save_progress(out_path, rows)
            if ans["verdict"] in ("correct", "incorrect"):
                judged_this_session += 1
                if args.live_only and judged_this_session >= target_judged:
                    print(f"\n[done] hit target of {target_judged} live-judged samples"
                          f" (auto-skipped {auto_skipped} dead URLs)")
                    break
            time.sleep(args.rate_limit)
            i += 1
    except KeyboardInterrupt:
        print("\n[interrupt] saving progress and exiting.")

    save_progress(out_path, rows)
    print(f"\n[saved] {len(rows)} rows in {out_path}")
    report(rows, cfg["label"])


if __name__ == "__main__":
    main()
