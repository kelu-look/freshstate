"""
Recompute expiration-extractor precision under the corrected definition
(any 4xx = expired) using the labels already gathered in
validation/expiration.jsonl.
"""
import json
import math
from collections import Counter


def wilson_ci(k, n, z=1.96):
    if n == 0: return (0.0, 0.0)
    p = k / n
    denom = 1 + z*z/n
    c = (p + z*z/(2*n)) / denom
    m = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / denom
    return (max(0.0, c - m), min(1.0, c + m))


def derive_ground_truth(row):
    s = row.get("http_status")
    old_decision = "EXPIRED" if s == 410 else "NOT_EXPIRED"
    if row["verdict"] == "correct":
        return old_decision
    if row["verdict"] == "incorrect":
        note = row.get("note", "")
        if note in ("expired_but_404", "expired_but_200", "expired_but_3xx"):
            return "EXPIRED"
        if note == "false_410":
            return "NOT_EXPIRED"
    return None


def main():
    rows = [json.loads(l) for l in open("validation/expiration.jsonl")]
    print(f"Loaded {len(rows)} validated samples.")

    old_correct = 0
    new_correct = 0
    judged = 0
    status_dist = Counter()
    for r in rows:
        gt = derive_ground_truth(r)
        if gt is None:
            continue
        judged += 1
        s = r.get("http_status")
        status_dist[s] += 1
        old_decision = "EXPIRED" if s == 410 else "NOT_EXPIRED"
        new_decision = "EXPIRED" if s and 400 <= s < 500 else "NOT_EXPIRED"
        if old_decision == gt: old_correct += 1
        if new_decision == gt: new_correct += 1

    print(f"\nJudged samples used: {judged}")
    print(f"\nHTTP status distribution in sample:")
    for s, n in sorted(status_dist.items()):
        print(f"  {s}: {n}")

    olo, ohi = wilson_ci(old_correct, judged)
    nlo, nhi = wilson_ci(new_correct, judged)
    print()
    print("=" * 72)
    print("  EXPIRATION EXTRACTOR PRECISION (rescored from existing labels)")
    print("=" * 72)
    print(f"  Original definition (HTTP 410 only):")
    print(f"    {old_correct}/{judged} = {old_correct/judged*100:.1f}% "
          f"[95% CI {olo*100:.1f}, {ohi*100:.1f}]")
    print()
    print(f"  Corrected definition (any HTTP 4xx, matching production monitor):")
    print(f"    {new_correct}/{judged} = {new_correct/judged*100:.1f}% "
          f"[95% CI {nlo*100:.1f}, {nhi*100:.1f}]")


if __name__ == "__main__":
    main()
