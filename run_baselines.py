"""
Task 1 (stale-evidence detection) baselines.

Loads data/eval_task1.jsonl and evaluates:
  - random           uniform random
  - age_threshold    tuned threshold on age_days
  - domain_prior     stale rate per-domain learned on train
  - logistic_reg     LR over [age, domain, age*domain]
  - llm_verifier     reads results/verifier_gpt4o_mini.jsonl if present
  - extractor_oracle 100% by construction (live fetch + extractor)

Uses 5-fold stratified CV; reports balanced accuracy and macro-F1.
AUROC computed where the baseline returns a continuous score.
"""
import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Callable

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import (
    balanced_accuracy_score, f1_score, roc_auc_score
)


def load_examples(path: str) -> list[dict]:
    return [json.loads(l) for l in open(path)]


def encode(examples: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Features: age_days + one-hot per domain + age*domain interactions.
    Works for any number of distinct domain labels."""
    domains = sorted({e["domain"] for e in examples})
    X, y = [], []
    for e in examples:
        feat = [e["age_days"]]
        for d in domains:
            ind = 1.0 if e["domain"] == d else 0.0
            feat.append(ind)
            feat.append(e["age_days"] * ind)
        X.append(feat)
        y.append(1 if e["label"] == "stale" else 0)
    return np.asarray(X, dtype=np.float64), np.asarray(y, dtype=np.int64)


def cv_metrics(name: str, examples: list[dict],
               fit_predict: Callable, n_splits: int = 5, seed: int = 42) -> dict:
    """fit_predict(train_examples, test_examples) -> (y_pred, y_score)."""
    X_dummy = np.zeros((len(examples), 1))
    y = np.asarray([1 if e["label"] == "stale" else 0 for e in examples])
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)

    bal_accs, f1s, aucs = [], [], []
    for tr_idx, te_idx in skf.split(X_dummy, y):
        tr = [examples[i] for i in tr_idx]
        te = [examples[i] for i in te_idx]
        y_te = np.asarray([1 if e["label"] == "stale" else 0 for e in te])
        y_pred, y_score = fit_predict(tr, te)
        bal_accs.append(balanced_accuracy_score(y_te, y_pred))
        f1s.append(f1_score(y_te, y_pred, average="macro"))
        if y_score is not None and len(set(y_te)) == 2:
            aucs.append(roc_auc_score(y_te, y_score))

    return {
        "name":     name,
        "bal_acc":  (statistics.mean(bal_accs), statistics.stdev(bal_accs) if len(bal_accs) > 1 else 0.0),
        "macro_f1": (statistics.mean(f1s), statistics.stdev(f1s) if len(f1s) > 1 else 0.0),
        "auroc":    (statistics.mean(aucs), statistics.stdev(aucs) if len(aucs) > 1 else 0.0) if aucs else None,
    }


# ─── baselines ────────────────────────────────────────────────────────

def random_baseline(tr, te):
    rng = np.random.RandomState(0)
    pred = rng.randint(0, 2, size=len(te))
    score = rng.random(size=len(te))
    return pred, score


def age_threshold(tr, te):
    """Sweep threshold on training set, pick threshold maximizing balanced acc."""
    ages_tr = np.array([e["age_days"] for e in tr])
    y_tr = np.array([1 if e["label"] == "stale" else 0 for e in tr])
    best_thr, best_bacc = 0, -1
    for thr in sorted(set(ages_tr.tolist())):
        pred_tr = (ages_tr > thr).astype(int)
        b = balanced_accuracy_score(y_tr, pred_tr)
        if b > best_bacc:
            best_bacc, best_thr = b, thr
    ages_te = np.array([e["age_days"] for e in te])
    pred = (ages_te > best_thr).astype(int)
    # Score = age (higher = more stale)
    return pred, ages_te.astype(float)


def domain_prior(tr, te):
    """Stale rate per-domain from training set."""
    rates = {}
    for d in {e["domain"] for e in tr} | {e["domain"] for e in te}:
        sub = [e for e in tr if e["domain"] == d]
        rates[d] = (sum(1 for e in sub if e["label"] == "stale") / len(sub)
                    if sub else 0.5)
    score = np.array([rates.get(e["domain"], 0.5) for e in te])
    pred = (score > 0.5).astype(int)
    return pred, score


def logistic_reg(tr, te):
    # Shared domain vocabulary so train/test feature matrices align
    domains = sorted({e["domain"] for e in tr + te})
    Xtr, ytr = _encode_with_domains(tr, domains)
    Xte, _   = _encode_with_domains(te, domains)
    clf = LogisticRegression(max_iter=1000)
    clf.fit(Xtr, ytr)
    pred = clf.predict(Xte)
    score = clf.predict_proba(Xte)[:, 1]
    return pred, score


def _encode_with_domains(examples, domains):
    X, y = [], []
    for e in examples:
        feat = [e["age_days"]]
        for d in domains:
            ind = 1.0 if e["domain"] == d else 0.0
            feat.append(ind)
            feat.append(e["age_days"] * ind)
        X.append(feat)
        y.append(1 if e["label"] == "stale" else 0)
    return np.asarray(X, dtype=np.float64), np.asarray(y, dtype=np.int64)


def llm_verifier_eval(examples, verifier_results_path: str):
    """Score from results/verifier_gpt4o_mini.jsonl. The verifier was run on a
    different 100-pair sample; we re-evaluate as a fixed predictor."""
    if not Path(verifier_results_path).exists():
        return None
    rows = [json.loads(l) for l in open(verifier_results_path)]
    # outcome: pred ∈ {fresh, stale, unsure}; map unsure to 0.5
    y_true, y_pred, y_score = [], [], []
    for r in rows:
        y_true.append(1 if r["ground_truth"] == "stale" else 0)
        if r["pred"] == "stale":
            y_pred.append(1); y_score.append(1.0)
        elif r["pred"] == "fresh":
            y_pred.append(0); y_score.append(0.0)
        else:
            y_pred.append(1 if 0.5 > 0.5 else 0)  # tie -> fresh
            y_score.append(0.5)
    y_true, y_pred, y_score = map(np.asarray, (y_true, y_pred, y_score))
    return {
        "name":     "llm_verifier",
        "bal_acc":  (balanced_accuracy_score(y_true, y_pred), 0.0),
        "macro_f1": (f1_score(y_true, y_pred, average="macro"), 0.0),
        "auroc":    (roc_auc_score(y_true, y_score), 0.0),
        "n":        len(rows),
    }


def report_row(r: dict) -> str:
    def fmt(t):
        if t is None: return "  ---  "
        m, s = t
        return f"{m*100:5.1f} ± {s*100:4.1f}"
    auc = fmt(r["auroc"]) if r["auroc"] else "  ---  "
    return f"  {r['name']:<18} BalAcc={fmt(r['bal_acc'])}   MacroF1={fmt(r['macro_f1'])}   AUROC={auc}"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--eval_set", default="data/eval_task1.jsonl")
    p.add_argument("--verifier_results", default="results/verifier_task1.jsonl",
                   help="LLM verifier predictions (one JSON record per pair).")
    p.add_argument("--output", default="results/baselines.json")
    args = p.parse_args()

    examples = load_examples(args.eval_set)
    print(f"[baselines] {len(examples)} examples loaded ({Counter(e['label'] for e in examples)})")

    results = []
    for name, fn in [
        ("random",       random_baseline),
        ("age_threshold", age_threshold),
        ("domain_prior", domain_prior),
        ("logistic_reg", logistic_reg),
    ]:
        r = cv_metrics(name, examples, fn)
        results.append(r)
        print(report_row(r))

    # LLM verifier — uses the pre-run results file
    llm = llm_verifier_eval(examples, args.verifier_results)
    if llm is not None:
        results.append(llm)
        print(report_row(llm))

    # Extractor oracle — by construction
    results.append({
        "name": "extractor_oracle",
        "bal_acc": (1.0, 0.0),
        "macro_f1": (1.0, 0.0),
        "auroc": (1.0, 0.0),
        "note": "Domain-specific ceiling: requires live fetch + working extractor.",
    })
    print(report_row(results[-1]))

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n[baselines] results written to {args.output}")


if __name__ == "__main__":
    main()
