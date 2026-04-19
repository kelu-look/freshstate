"""
Snippet-swap experiment for prospective monitor seeds.

For each detected change event, tests whether LLMs echo stale values
when given stale context (simulating an outdated search snippet).

Three conditions per seed:
  A (Fresh context):  snippet contains the CURRENT value
  B (Stale context):  snippet contains the OLD value
  C (No context):     question only, no snippet (parametric baseline)

Supports OpenAI and Anthropic backends.

Usage:
    # Dry run (show prompts, no API calls)
    python run_experiment.py --dry-run

    # Run with GPT-4o
    python run_experiment.py --model gpt-4o --output results/experiment_gpt4o.jsonl

    # Run with Claude
    python run_experiment.py --model claude-sonnet-4-20250514 --output results/experiment_claude.jsonl

    # Limit to N seeds for testing
    python run_experiment.py --model gpt-4o --limit 5 --output results/test.jsonl
"""

import argparse
import json
import re
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional


# ─────────────────────────────────────────────
#  Load seeds + state → build experiment records
# ─────────────────────────────────────────────

def load_experiment_records(
    seed_paths: list[str],
    state_paths: list[str],
) -> list[dict]:
    """
    Merge monitor seeds with state files to get (answer_stale, answer_current) pairs.
    Only includes seeds where current value differs from stale value.
    """
    # Load all state files into one dict
    state = {}
    for sp in state_paths:
        if Path(sp).exists():
            with open(sp) as f:
                s = json.load(f)
                state.update(s)

    # Load seeds
    seeds = []
    for path in seed_paths:
        if not Path(path).exists():
            continue
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    seeds.append(json.loads(line))

    # Build experiment records
    records = []
    seen_urls = set()
    for seed in seeds:
        url = seed["official_url"]
        if url in seen_urls:
            continue  # deduplicate (same URL may have multiple change events)
        seen_urls.add(url)

        answer_stale = seed.get("answer_stale")
        if not answer_stale:
            continue

        # Get current value from state
        if url not in state:
            continue
        answer_current = state[url].get("value")
        if not answer_current or answer_current == answer_stale:
            continue  # no change or same value

        # Determine domain and build a natural question
        change_type = seed.get("change_type", "")
        if change_type == "price_change":
            domain = "apartment"
            question = f"What is the current monthly rent for this listing: {url} ?"
            snippet_template = "This apartment is listed at {value} per month."
        elif change_type == "spec_change":
            domain = "software"
            # Extract repo name from URL
            parts = url.replace("https://github.com/", "").split("/")
            repo_name = "/".join(parts[:2]) if len(parts) >= 2 else url
            question = f"What is the latest release version of {repo_name}?"
            snippet_template = "Latest release: {value}. View all releases and changelogs."
        else:
            domain = "other"
            question = seed.get("query", f"What is the current value at {url}?")
            snippet_template = "Current value: {value}."

        records.append({
            "example_id": seed["example_id"],
            "url": url,
            "domain": domain,
            "question": question,
            "answer_stale": answer_stale,
            "answer_current": answer_current,
            "snippet_template": snippet_template,
            "T_before": seed.get("T_before"),
            "detected_on": seed.get("_detected_on"),
        })

    return records


# ─────────────────────────────────────────────
#  Prompt construction
# ─────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are a helpful assistant that answers questions using web search results. "
    "Answer concisely with the specific value requested. "
    "If the search result contains the answer, use it."
)

SYSTEM_PROMPT_NO_CONTEXT = (
    "You are a helpful assistant. Answer the question concisely with the specific "
    "value requested. If you don't know, say so."
)


def build_prompt_with_context(question: str, snippet: str) -> str:
    return (
        f"Web search result:\n{snippet}\n\n"
        f"Question: {question}\n"
        f"Answer with just the value (e.g., '$2,500/mo' or 'v1.2.3')."
    )


def build_prompt_no_context(question: str) -> str:
    return (
        f"Question: {question}\n"
        f"Answer with just the value (e.g., '$2,500/mo' or 'v1.2.3'). "
        f"If you don't know, say 'unknown'."
    )


def build_conditions(rec: dict) -> list[dict]:
    """Build the 3 experimental conditions for a record."""
    tmpl = rec["snippet_template"]
    fresh_snippet = tmpl.format(value=rec["answer_current"])
    stale_snippet = tmpl.format(value=rec["answer_stale"])

    return [
        {
            "condition": "A",
            "label": "fresh_context",
            "system": SYSTEM_PROMPT,
            "prompt": build_prompt_with_context(rec["question"], fresh_snippet),
            "snippet_shown": fresh_snippet,
        },
        {
            "condition": "B",
            "label": "stale_context",
            "system": SYSTEM_PROMPT,
            "prompt": build_prompt_with_context(rec["question"], stale_snippet),
            "snippet_shown": stale_snippet,
        },
        {
            "condition": "C",
            "label": "no_context",
            "system": SYSTEM_PROMPT_NO_CONTEXT,
            "prompt": build_prompt_no_context(rec["question"]),
            "snippet_shown": "",
        },
    ]


# ─────────────────────────────────────────────
#  LLM backends
# ─────────────────────────────────────────────

def query_openai(system: str, prompt: str, model: str) -> Optional[str]:
    from openai import OpenAI
    client = OpenAI()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=100,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"  [openai error] {e}")
        return None


def query_anthropic(system: str, prompt: str, model: str) -> Optional[str]:
    import anthropic
    client = anthropic.Anthropic()
    try:
        resp = client.messages.create(
            model=model,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=100,
        )
        return resp.content[0].text.strip()
    except Exception as e:
        print(f"  [anthropic error] {e}")
        return None


def query_llm(system: str, prompt: str, model: str) -> Optional[str]:
    if model.startswith("claude"):
        return query_anthropic(system, prompt, model)
    else:
        return query_openai(system, prompt, model)


# ─────────────────────────────────────────────
#  Scoring
# ─────────────────────────────────────────────

def normalize(v: str) -> str:
    """Normalize a value for comparison."""
    v = v.lower().strip()
    v = re.sub(r"[,$\s]", "", v)
    v = v.replace("permonth", "/mo").replace("/month", "/mo")
    # Strip leading "v" for version comparisons
    if re.match(r"^v\d", v):
        v = v[1:]
    return v


def score_answer(answer: Optional[str], answer_current: str, answer_stale: str) -> dict:
    """Classify LLM answer as current, stale, abstain, or other."""
    if not answer:
        return {"outcome": "error", "is_current": 0, "is_stale": 0, "is_abstain": 0}

    ans = answer.lower()

    # Check for abstention
    abstain_phrases = ["unknown", "i don't know", "i cannot", "not sure",
                       "don't have", "unable to", "no information", "cannot determine"]
    if any(p in ans for p in abstain_phrases):
        return {"outcome": "abstain", "is_current": 0, "is_stale": 0, "is_abstain": 1}

    ans_norm = normalize(ans)
    current_norm = normalize(answer_current)
    stale_norm = normalize(answer_stale)

    if current_norm in ans_norm or ans_norm in current_norm:
        return {"outcome": "current", "is_current": 1, "is_stale": 0, "is_abstain": 0}
    if stale_norm in ans_norm or ans_norm in stale_norm:
        return {"outcome": "stale", "is_current": 0, "is_stale": 1, "is_abstain": 0}

    # Try numeric comparison for prices
    try:
        nums_in_answer = re.findall(r"[\d,]+\.?\d*", ans)
        current_num = float(re.sub(r"[^\d.]", "", answer_current))
        stale_num = float(re.sub(r"[^\d.]", "", answer_stale))
        for n in nums_in_answer:
            val = float(n.replace(",", ""))
            if abs(val - current_num) < 1:
                return {"outcome": "current", "is_current": 1, "is_stale": 0, "is_abstain": 0}
            if abs(val - stale_num) < 1:
                return {"outcome": "stale", "is_current": 0, "is_stale": 1, "is_abstain": 0}
    except (ValueError, IndexError):
        pass

    return {"outcome": "other", "is_current": 0, "is_stale": 0, "is_abstain": 0}


# ─────────────────────────────────────────────
#  Main experiment loop
# ─────────────────────────────────────────────

def run_experiment(
    records: list[dict],
    model: str,
    sleep_sec: float = 0.5,
    dry_run: bool = False,
) -> list[dict]:
    results = []

    for i, rec in enumerate(records):
        print(f"\n[{i+1}/{len(records)}] {rec['example_id']} ({rec['domain']})")
        print(f"  URL: {rec['url'][:70]}")
        print(f"  stale={rec['answer_stale']!r} → current={rec['answer_current']!r}")

        conditions = build_conditions(rec)

        for cond in conditions:
            if dry_run:
                print(f"  [{cond['condition']}] {cond['label']}")
                print(f"      snippet: {cond['snippet_shown'][:80]}")
                print(f"      prompt: {cond['prompt'][:100]}...")
                result = {
                    "example_id": rec["example_id"],
                    "domain": rec["domain"],
                    "condition": cond["condition"],
                    "condition_label": cond["label"],
                    "answer_stale": rec["answer_stale"],
                    "answer_current": rec["answer_current"],
                    "llm_answer": "(dry run)",
                    "outcome": "dry_run",
                    "is_current": 0, "is_stale": 0, "is_abstain": 0,
                    "model": model,
                }
            else:
                answer = query_llm(cond["system"], cond["prompt"], model)
                scores = score_answer(answer, rec["answer_current"], rec["answer_stale"])
                print(f"  [{cond['condition']}] {cond['label']}: {answer!r} → {scores['outcome']}")

                result = {
                    "example_id": rec["example_id"],
                    "domain": rec["domain"],
                    "url": rec["url"],
                    "condition": cond["condition"],
                    "condition_label": cond["label"],
                    "snippet_shown": cond["snippet_shown"],
                    "question": rec["question"],
                    "answer_stale": rec["answer_stale"],
                    "answer_current": rec["answer_current"],
                    "llm_answer": answer,
                    **scores,
                    "model": model,
                    "timestamp": datetime.now().isoformat(),
                }
                time.sleep(sleep_sec)

            results.append(result)

    return results


def print_summary(results: list[dict]):
    """Print summary table grouped by condition and domain."""
    by_cond = defaultdict(list)
    by_domain_cond = defaultdict(list)

    for r in results:
        if r["outcome"] == "dry_run":
            continue
        by_cond[r["condition"]].append(r)
        by_domain_cond[(r["domain"], r["condition"])].append(r)

    print("\n" + "=" * 70)
    print("OVERALL RESULTS")
    print("=" * 70)
    print(f"{'Condition':<22} {'N':>4} {'Current%':>9} {'Stale%':>8} {'Abstain%':>9} {'Other%':>8}")
    print("-" * 70)

    for cond, label in [("A", "Fresh context"), ("B", "Stale context"), ("C", "No context")]:
        rows = by_cond[cond]
        if not rows:
            continue
        n = len(rows)
        curr = sum(r["is_current"] for r in rows) / n * 100
        stale = sum(r["is_stale"] for r in rows) / n * 100
        abst = sum(r["is_abstain"] for r in rows) / n * 100
        other = 100 - curr - stale - abst
        print(f"{cond} ({label}){'':<4} {n:>4} {curr:>8.1f}% {stale:>7.1f}% {abst:>8.1f}% {other:>7.1f}%")

    # Per-domain breakdown
    domains = sorted(set(r["domain"] for r in results if r["outcome"] != "dry_run"))
    for domain in domains:
        print(f"\n── {domain.upper()} ──")
        print(f"{'Condition':<22} {'N':>4} {'Current%':>9} {'Stale%':>8} {'Abstain%':>9}")
        print("-" * 55)
        for cond, label in [("A", "Fresh context"), ("B", "Stale context"), ("C", "No context")]:
            rows = by_domain_cond[(domain, cond)]
            if not rows:
                continue
            n = len(rows)
            curr = sum(r["is_current"] for r in rows) / n * 100
            stale = sum(r["is_stale"] for r in rows) / n * 100
            abst = sum(r["is_abstain"] for r in rows) / n * 100
            print(f"{cond} ({label}){'':<4} {n:>4} {curr:>8.1f}% {stale:>7.1f}% {abst:>8.1f}%")


def main():
    parser = argparse.ArgumentParser(description="FreshState snippet-swap experiment")
    parser.add_argument("--model", default="gpt-4o",
                        help="Model name (gpt-4o, claude-sonnet-4-20250514, etc.)")
    parser.add_argument("--output", default="results/experiment.jsonl",
                        help="Output results file")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max number of seeds to test")
    parser.add_argument("--sleep", type=float, default=0.5,
                        help="Sleep between API calls")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show prompts without calling LLM APIs")
    parser.add_argument("--seeds", nargs="*", default=[
        "seeds/apartment_monitored_v2.jsonl",
        "seeds/software_monitored.jsonl",
    ])
    parser.add_argument("--states", nargs="*", default=[
        "monitor_state_apartment_v2.json",
        "monitor_state_software.json",
    ])
    args = parser.parse_args()

    # Load and merge
    records = load_experiment_records(args.seeds, args.states)
    print(f"[experiment] {len(records)} usable change events loaded")

    if args.limit:
        records = records[:args.limit]
        print(f"[experiment] limited to {args.limit} records")

    if not records:
        print("[experiment] no records to test — need seeds with stale/current value pairs")
        return

    # Run
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    results = run_experiment(records, model=args.model, sleep_sec=args.sleep,
                             dry_run=args.dry_run)

    # Save results
    with open(args.output, "w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print_summary(results)
    print(f"\n[done] {len(results)} results written to {args.output}")


if __name__ == "__main__":
    main()
