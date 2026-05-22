"""
Task 1 baseline: LLM verifier.

Two modes:
  --legacy-pairs    Build pairs from change events (original snippet-swap setup).
  default           Read data/eval_task1.jsonl (the Task 1 labeled set).

The verifier asks an LLM YES/NO/UNSURE on whether a (URL, snippet) pair is
still accurate today, *without* a live fetch.
"""

import argparse
import json
import random
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from run_experiment import load_experiment_records, query_llm


SYSTEM_PROMPT = (
    "You are a freshness verifier. Given a search result snippet and the "
    "URL it came from, decide whether the snippet is likely still accurate "
    "today. Answer with exactly one word: YES, NO, or UNSURE."
)


def build_verifier_prompt(url: str, snippet: str) -> str:
    return (
        f"URL: {url}\n"
        f"Snippet: {snippet}\n\n"
        f"Is this snippet likely still accurate today? Answer YES, NO, or UNSURE."
    )


def parse_verdict(answer: Optional[str]) -> str:
    if not answer:
        return "error"
    a = answer.strip().lower().replace(".", "").replace(",", "").strip()
    if a.startswith("yes"): return "yes"
    if a.startswith("no"):  return "no"
    if "unsure" in a or "don't know" in a or "cannot" in a: return "unsure"
    if " yes " in f" {a} ": return "yes"
    if " no " in f" {a} ":  return "no"
    return "unsure"


def build_pairs_legacy(records, n_per_class, seed=42):
    rng = random.Random(seed); rng.shuffle(records)
    take = records[:n_per_class]
    pairs = []
    for rec in take:
        tmpl = rec["snippet_template"]
        pairs.append({
            "example_id": rec["example_id"], "url": rec["url"], "domain": rec["domain"],
            "snippet": tmpl.format(value=rec["answer_current"]), "ground_truth": "fresh",
        })
        pairs.append({
            "example_id": rec["example_id"], "url": rec["url"], "domain": rec["domain"],
            "snippet": tmpl.format(value=rec["answer_stale"]), "ground_truth": "stale",
        })
    return pairs


def load_pairs_from_eval_set(path):
    pairs = []
    for line in open(path):
        e = json.loads(line)
        pairs.append({
            "example_id":   e["url"],
            "url":          e["url"],
            "domain":       e["domain"],
            "snippet":      e["snippet"],
            "ground_truth": e["label"],
        })
    return pairs


def evaluate(pairs, model, sleep_sec, dry_run):
    results = []
    for i, p in enumerate(pairs):
        prompt = build_verifier_prompt(p["url"], p["snippet"])
        if dry_run:
            verdict = "yes" if i % 2 == 0 else "no"
            answer = "(dry run)"
        else:
            answer = query_llm(SYSTEM_PROMPT, prompt, model)
            verdict = parse_verdict(answer)
            time.sleep(sleep_sec)
        pred = "fresh" if verdict == "yes" else ("stale" if verdict == "no" else "unsure")
        correct = int(pred == p["ground_truth"])
        results.append({**p, "model": model, "answer": answer, "verdict": verdict,
                        "pred": pred, "correct": correct,
                        "timestamp": datetime.now().isoformat()})
        if not dry_run:
            print(f"  [{i+1}/{len(pairs)}] {p['ground_truth']:>5} -> {verdict:>6} ({pred})")
    return results


def report(results):
    by_class = defaultdict(list)
    by_domain = defaultdict(lambda: defaultdict(list))
    for r in results:
        score = r["correct"] if r["verdict"] != "unsure" else 0.5
        by_class[r["ground_truth"]].append(score)
        by_domain[r["domain"]][r["ground_truth"]].append(score)
    bal_acc = ((sum(by_class["fresh"]) / max(len(by_class["fresh"]), 1)) +
               (sum(by_class["stale"]) / max(len(by_class["stale"]), 1))) / 2
    print("\n" + "=" * 50 + "\nLLM VERIFIER RESULTS\n" + "=" * 50)
    print(f"N pairs:           {len(results)}")
    print(f"Fresh acc:         {sum(by_class['fresh'])/max(len(by_class['fresh']),1)*100:.1f}%")
    print(f"Stale acc:         {sum(by_class['stale'])/max(len(by_class['stale']),1)*100:.1f}%")
    print(f"Balanced accuracy: {bal_acc*100:.1f}%")
    for domain, cls_scores in by_domain.items():
        fa = sum(cls_scores["fresh"]) / max(len(cls_scores["fresh"]), 1)
        sa = sum(cls_scores["stale"]) / max(len(cls_scores["stale"]), 1)
        print(f"  {domain:<10} fresh={fa*100:5.1f}% stale={sa*100:5.1f}% bal={(fa+sa)/2*100:5.1f}%")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--output", default="results/verifier.jsonl")
    parser.add_argument("--sleep", type=float, default=0.3)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--eval-set", default="data/eval_task1.jsonl",
                        help="Task 1 labeled set; overrides legacy mode.")
    parser.add_argument("--legacy-pairs", action="store_true",
                        help="Use legacy snippet-swap-derived 100-pair sample.")
    parser.add_argument("--n", type=int, default=50,
                        help="(legacy mode only) events to sample -> 2*n pairs")
    parser.add_argument("--seeds", nargs="*", default=[
        "seeds/apartment_monitored_v2.jsonl", "seeds/software_monitored.jsonl"])
    parser.add_argument("--states", nargs="*", default=[
        "monitor_state_apartment_v2.json", "monitor_state_software.json"])
    args = parser.parse_args()

    if args.legacy_pairs:
        records = load_experiment_records(args.seeds, args.states)
        print(f"[verifier] (legacy) {len(records)} change events")
        pairs = build_pairs_legacy(records, n_per_class=args.n)
    else:
        pairs = load_pairs_from_eval_set(args.eval_set)
        print(f"[verifier] loaded {len(pairs)} pairs from {args.eval_set}")

    results = evaluate(pairs, args.model, args.sleep, args.dry_run)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if not args.dry_run:
        report(results)
    print(f"\n[done] wrote {len(results)} results to {args.output}")


if __name__ == "__main__":
    main()
