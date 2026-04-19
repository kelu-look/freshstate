"""
Controlled snippet-swap experiment.

For each FreshState record, construct the 5 retrieval contexts (A/B/C/D1/D2)
and query a given LLM. Records the answer and source-following rate per condition.

Usage:
    python snippet_swap.py \
        --data data/apartments.jsonl \
        --model gpt-4o \
        --output results/snippet_swap_apartments.jsonl
"""

import argparse
import json
import os
import time
from dataclasses import dataclass, asdict
from typing import Optional
from openai import OpenAI

from schema import FreshStateRecord
from label import normalize_value, values_match


client = OpenAI()   # uses OPENAI_API_KEY env var


# ─────────────────────────────────────────────
#  Condition builders
# ─────────────────────────────────────────────

@dataclass
class RetrievalContext:
    condition: str          # A, B, C, D1, D2
    surfaced_preview: str   # text shown as snippet/preview
    page_content: str       # text of the linked page
    description: str        # human-readable label for the condition


def build_conditions(rec: FreshStateRecord) -> list[RetrievalContext]:
    """
    Build retrieval contexts for all 5 conditions from a FreshState record.
    Skips conditions where required fields are missing.
    """
    conditions = []

    fresh_snippet = rec.official_snippet_fresh or ""
    stale_snippet = rec.aggregator_snippet or rec.official_snippet_stale or ""
    fresh_page    = (rec.official_page_fresh or "")[:3000]   # truncate to 3k for LLM context
    stale_page    = (rec.official_page_stale or rec.aggregator_page or "")[:3000]

    if not fresh_snippet or not fresh_page:
        return []

    # Condition A: fresh preview + fresh page
    conditions.append(RetrievalContext(
        condition="A",
        surfaced_preview=fresh_snippet,
        page_content=fresh_page,
        description="Fresh preview + fresh page (best-case control)",
    ))

    # Condition B: stale preview + fresh page
    if stale_snippet:
        conditions.append(RetrievalContext(
            condition="B",
            surfaced_preview=stale_snippet,
            page_content=fresh_page,
            description="Stale preview + fresh page (tests preview-induced staleness)",
        ))

    # Condition C: fresh preview + stale page
    if stale_page:
        conditions.append(RetrievalContext(
            condition="C",
            surfaced_preview=fresh_snippet,
            page_content=stale_page,
            description="Fresh preview + stale page (tests page-induced staleness)",
        ))

    # Conditions D1/D2: rank order (stale preview vs. fresh preview, same fresh page)
    if stale_snippet:
        conditions.append(RetrievalContext(
            condition="D1",
            surfaced_preview=f"[Result 1] {stale_snippet}\n\n[Result 2] {fresh_snippet}",
            page_content=fresh_page,
            description="Stale above fresh (rank order: stale first)",
        ))
        conditions.append(RetrievalContext(
            condition="D2",
            surfaced_preview=f"[Result 1] {fresh_snippet}\n\n[Result 2] {stale_snippet}",
            page_content=fresh_page,
            description="Fresh above stale (rank order: fresh first)",
        ))

    return conditions


# ─────────────────────────────────────────────
#  LLM query
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are a helpful assistant that answers questions based on web search results.
You are given: (1) a surfaced search preview/snippet, and (2) the content of the linked page.
Answer the question directly and concisely. Do not say "I don't know" if the answer is present."""

def build_user_prompt(query: str, ctx: RetrievalContext) -> str:
    return f"""Question: {query}

Search preview:
{ctx.surfaced_preview}

Page content:
{ctx.page_content}

Answer the question based on the above. Be specific."""


def query_llm(query: str, ctx: RetrievalContext, model: str, retries: int = 3) -> Optional[str]:
    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_user_prompt(query, ctx)},
                ],
                temperature=0.0,
                max_tokens=150,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            if attempt == retries - 1:
                print(f"[llm] failed: {e}")
                return None
            time.sleep(2 ** attempt)
    return None


# ─────────────────────────────────────────────
#  Scoring
# ─────────────────────────────────────────────

def score_answer(
    answer: Optional[str],
    answer_current: Optional[str],
    answer_stale: Optional[str],
) -> dict:
    """
    Classify the LLM answer as:
      current (correct), stale (wrong but matches prior state), unsupported (neither)
    """
    if answer is None:
        return {"outcome": "unsupported", "current_acc": 0, "stale_rate": 0}

    ans_norm = normalize_value(answer)
    if answer_current and ans_norm and values_match(answer, answer_current):
        return {"outcome": "current", "current_acc": 1, "stale_rate": 0}
    if answer_stale and ans_norm and values_match(answer, answer_stale):
        return {"outcome": "stale", "current_acc": 0, "stale_rate": 1}
    return {"outcome": "unsupported", "current_acc": 0, "stale_rate": 0}


def source_following_rate(answer: Optional[str], preview: str, page: str) -> dict:
    """
    Compute lexical overlap of answer with surfaced preview vs. page content.
    Returns {follows_preview, follows_page} as booleans (rough heuristic).
    """
    if not answer:
        return {"follows_preview": False, "follows_page": False}
    ans = answer.lower()
    preview_words = set(preview.lower().split())
    page_words = set(page.lower().split())
    ans_words = set(ans.split())
    overlap_preview = len(ans_words & preview_words) / max(len(ans_words), 1)
    overlap_page = len(ans_words & page_words) / max(len(ans_words), 1)
    return {
        "follows_preview": overlap_preview > overlap_page,
        "follows_page": overlap_page >= overlap_preview,
    }


# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────

def run_experiment(records: list[FreshStateRecord], model: str, sleep: float = 0.5) -> list[dict]:
    results = []

    for i, rec in enumerate(records):
        print(f"\n[{i+1}/{len(records)}] {rec.example_id}")
        conditions = build_conditions(rec)
        if not conditions:
            print(f"  skipped: missing fields")
            continue

        for ctx in conditions:
            print(f"  condition {ctx.condition}: {ctx.description}")
            answer = query_llm(rec.query, ctx, model=model)
            scores = score_answer(answer, rec.answer_current, rec.answer_stale)
            sfr = source_following_rate(answer, ctx.surfaced_preview, ctx.page_content)

            result = {
                "example_id": rec.example_id,
                "domain": rec.domain,
                "condition": ctx.condition,
                "condition_description": ctx.description,
                "query": rec.query,
                "answer": answer,
                "answer_current": rec.answer_current,
                "answer_stale": rec.answer_stale,
                **scores,
                **sfr,
            }
            results.append(result)
            print(f"    answer={answer!r} → {scores['outcome']}")
            time.sleep(sleep)

    return results


def main():
    parser = argparse.ArgumentParser(description="FreshState snippet-swap experiment")
    parser.add_argument("--data", required=True, help="Path to collected records JSONL")
    parser.add_argument("--model", default="gpt-4o", help="OpenAI model to use")
    parser.add_argument("--output", required=True, help="Path to results JSONL")
    parser.add_argument("--limit", type=int, default=None, help="Max records (for testing)")
    parser.add_argument("--sleep", type=float, default=0.5)
    args = parser.parse_args()

    # Load records
    records = []
    with open(args.data) as f:
        for line in f:
            line = line.strip()
            if line:
                d = json.loads(line)
                rec = FreshStateRecord(**{k: v for k, v in d.items()
                                         if k in FreshStateRecord.__dataclass_fields__})
                records.append(rec)

    # Filter to stale examples only (these are the interesting ones)
    stale_records = [r for r in records if r.aggregator_is_stale]
    print(f"[experiment] {len(stale_records)} stale records (of {len(records)} total)")
    if args.limit:
        stale_records = stale_records[:args.limit]

    results = run_experiment(stale_records, model=args.model, sleep=args.sleep)

    with open(args.output, "w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Print summary table
    print("\n── Snippet-Swap Results ──")
    from collections import defaultdict
    by_condition = defaultdict(list)
    for r in results:
        by_condition[r["condition"]].append(r)

    print(f"{'Cond':<6} {'N':>4} {'CurrAcc':>8} {'StaleRate':>10} {'FollowsPreview':>15}")
    for cond in ["A", "B", "C", "D1", "D2"]:
        rows = by_condition[cond]
        if not rows:
            continue
        n = len(rows)
        curr_acc = sum(r["current_acc"] for r in rows) / n
        stale_rate = sum(r["stale_rate"] for r in rows) / n
        follows_prev = sum(r["follows_preview"] for r in rows) / n
        print(f"{cond:<6} {n:>4} {curr_acc:>8.2%} {stale_rate:>10.2%} {follows_prev:>15.2%}")

    print(f"\n[done] wrote {len(results)} results to {args.output}")


if __name__ == "__main__":
    main()
