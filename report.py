"""
Generate paper tables from evaluation results.

Usage:
    python report.py \
        --data data/apartments.jsonl data/products.jsonl \
        --results results/eval_bing.jsonl results/eval_bing_no_fresh.jsonl \
        --swap results/snippet_swap_apartments.jsonl results/snippet_swap_products.jsonl \
        --output tables/

Outputs:
    tables/table1_dataset_stats.txt
    tables/table2_main_eval.txt
    tables/table3_snippet_swap.txt
    tables/table4_mitigations.txt   (if mitigation results provided)
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path


def pct(v, denom):
    if denom == 0:
        return "—"
    return f"{v/denom:.1%}"


def mean_pct(values):
    vs = [v for v in values if v is not None]
    if not vs:
        return "—"
    return f"{sum(vs)/len(vs):.1%}"


# ─────────────────────────────────────────────
#  Table 1 — Dataset Statistics
# ─────────────────────────────────────────────

def table1_dataset_stats(record_paths: list[str]) -> str:
    records = []
    for path in record_paths:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))

    by_domain = defaultdict(list)
    for r in records:
        by_domain[r.get("domain", "unknown")].append(r)

    lines = []
    lines.append("Table 1: FreshState Dataset Statistics")
    lines.append("=" * 60)
    lines.append(f"{'Domain':<15} {'N':>6} {'Stale%':>8} {'Ambig%':>8} {'Lag(med)':>10} {'Change Types'}")
    lines.append("-" * 60)

    total = len(records)
    total_stale = 0

    for domain, recs in sorted(by_domain.items()):
        n = len(recs)
        stale = sum(1 for r in recs if r.get("aggregator_is_stale") is True)
        ambig = sum(1 for r in recs if r.get("label") == "Ambiguous")
        lags  = [r["staleness_lag_days"] for r in recs if r.get("staleness_lag_days")]
        med_lag = sorted(lags)[len(lags)//2] if lags else 0
        change_types = defaultdict(int)
        for r in recs:
            ct = r.get("change_type", "unknown")
            change_types[ct] += 1
        ct_str = ", ".join(f"{k}({v})" for k, v in sorted(change_types.items()))
        lines.append(f"{domain:<15} {n:>6} {pct(stale,n):>8} {pct(ambig,n):>8} {med_lag:>10} {ct_str}")
        total_stale += stale

    lines.append("-" * 60)
    lines.append(f"{'Total':<15} {total:>6} {pct(total_stale,total):>8}")
    return "\n".join(lines)


# ─────────────────────────────────────────────
#  Table 2 — Main Retrieval Evaluation
# ─────────────────────────────────────────────

def load_eval_results(paths: list[str]) -> dict[str, list[dict]]:
    """Returns {system: [query_result_dicts]}"""
    by_system = defaultdict(list)
    for path in paths:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    by_system[r["system"]].append(r)
    return by_system


def compute_fresh_doc_at_k(query_results: list[dict], k: int) -> float | None:
    vals = []
    for qr in query_results:
        top_k = [r for r in qr["results"] if r["rank"] <= k and r.get("snippet_is_stale") is not None]
        if not top_k:
            continue
        vals.append(any(r["snippet_is_stale"] is False for r in top_k))
    return sum(vals) / len(vals) if vals else None


def compute_stale_above_fresh(query_results: list[dict], k: int = 5) -> float | None:
    vals = []
    for qr in query_results:
        top_k = sorted(
            [r for r in qr["results"] if r["rank"] <= k and r.get("snippet_is_stale") is not None],
            key=lambda r: r["rank"]
        )
        has_fresh = any(r["snippet_is_stale"] is False for r in top_k)
        if not top_k or not has_fresh:
            continue
        vals.append(top_k[0]["snippet_is_stale"] is True)
    return sum(vals) / len(vals) if vals else None


def compute_snippet_mismatch(query_results: list[dict], k: int = 1) -> float | None:
    vals = []
    for qr in query_results:
        top_k = [r for r in qr["results"] if r["rank"] <= k and r.get("snippet_mismatch") is not None]
        if not top_k:
            continue
        vals.append(any(r["snippet_mismatch"] is True for r in top_k))
    return sum(vals) / len(vals) if vals else None


def table2_main_eval(result_paths: list[str]) -> str:
    by_system = load_eval_results(result_paths)

    lines = []
    lines.append("Table 2: Main Retrieval Evaluation")
    lines.append("=" * 80)
    lines.append(f"{'System':<20} {'N':>5} {'FreshDoc@1':>12} {'FreshDoc@5':>12} "
                 f"{'StaleAbove@5':>14} {'SnipMismatch@1':>16}")
    lines.append("-" * 80)

    for system, qrs in sorted(by_system.items()):
        n   = len(qrs)
        fd1 = compute_fresh_doc_at_k(qrs, k=1)
        fd5 = compute_fresh_doc_at_k(qrs, k=5)
        saf = compute_stale_above_fresh(qrs, k=5)
        sm1 = compute_snippet_mismatch(qrs, k=1)
        lines.append(
            f"{system:<20} {n:>5} "
            f"{mean_pct([fd1]):>12} {mean_pct([fd5]):>12} "
            f"{mean_pct([saf]):>14} {mean_pct([sm1]):>16}"
        )

    lines.append("-" * 80)
    lines.append("FreshDoc@k: ≥1 fresh result in top-k  |  StaleAbove@5: stale outranks fresh")
    lines.append("SnipMismatch@1: snippet stale, page fresh (requires --fetch_pages)")
    return "\n".join(lines)


# ─────────────────────────────────────────────
#  Table 3 — Snippet-Swap Experiment
# ─────────────────────────────────────────────

def table3_snippet_swap(swap_paths: list[str]) -> str:
    rows = []
    for path in swap_paths:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))

    by_cond = defaultdict(list)
    for r in rows:
        by_cond[r["condition"]].append(r)

    cond_desc = {
        "A":  "Fresh preview + fresh page (control)",
        "B":  "Stale preview + fresh page",
        "C":  "Fresh preview + stale page",
        "D1": "Stale above fresh (rank order)",
        "D2": "Fresh above stale (rank order)",
    }

    lines = []
    lines.append("Table 3: Controlled Snippet-Swap Experiment")
    lines.append("=" * 85)
    lines.append(f"{'Cond':<5} {'N':>5} {'CurrAcc':>9} {'StaleRate':>11} "
                 f"{'FollowsPreview':>15}  Condition")
    lines.append("-" * 85)

    baseline_stale = None
    for cond in ["A", "B", "C", "D1", "D2"]:
        rs = by_cond.get(cond, [])
        if not rs:
            continue
        n           = len(rs)
        curr_acc    = sum(r["current_acc"]  for r in rs) / n
        stale_rate  = sum(r["stale_rate"]   for r in rs) / n
        foll_prev   = sum(r.get("follows_preview", 0) for r in rs) / n

        if cond == "A":
            baseline_stale = stale_rate

        # Mark conditions that are notably worse than baseline
        flag = ""
        if baseline_stale is not None and cond != "A":
            if stale_rate > baseline_stale + 0.10:
                flag = " ◄"

        desc = cond_desc.get(cond, "")
        lines.append(
            f"{cond:<5} {n:>5} {curr_acc:>9.1%} {stale_rate:>11.1%} "
            f"{foll_prev:>15.1%}  {desc}{flag}"
        )

    lines.append("-" * 85)
    lines.append("◄ = stale rate >10pp higher than condition A baseline")
    lines.append("H1: B > A on stale rate confirms preview-induced staleness")
    lines.append("H2: D1 > D2 on stale rate confirms rank-order effect")
    return "\n".join(lines)


# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate FreshState paper tables")
    parser.add_argument("--data",    nargs="*", default=[], help="Collected records JSONL")
    parser.add_argument("--results", nargs="*", default=[], help="Retrieval eval results JSONL")
    parser.add_argument("--swap",    nargs="*", default=[], help="Snippet-swap results JSONL")
    parser.add_argument("--output",  default="tables/",    help="Output directory")
    args = parser.parse_args()

    Path(args.output).mkdir(parents=True, exist_ok=True)

    if args.data:
        t1 = table1_dataset_stats(args.data)
        path = Path(args.output) / "table1_dataset_stats.txt"
        path.write_text(t1)
        print(t1)
        print()

    if args.results:
        t2 = table2_main_eval(args.results)
        path = Path(args.output) / "table2_main_eval.txt"
        path.write_text(t2)
        print(t2)
        print()

    if args.swap:
        t3 = table3_snippet_swap(args.swap)
        path = Path(args.output) / "table3_snippet_swap.txt"
        path.write_text(t3)
        print(t3)
        print()

    print(f"[report] tables written to {args.output}")


if __name__ == "__main__":
    main()
