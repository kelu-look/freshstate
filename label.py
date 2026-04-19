"""
Labeling logic for FreshState records.

Auto-labels based on value comparison.
Flags ambiguous cases for human adjudication.
"""

from typing import Optional
from schema import FreshStateRecord, Label


def normalize_value(v: Optional[str]) -> Optional[str]:
    """Lower-case, strip whitespace and currency symbols for comparison."""
    if v is None:
        return None
    return v.strip().lower().replace(",", "").replace("$", "").replace(" ", "")


def values_match(a: Optional[str], b: Optional[str], tolerance: float = 0.01) -> bool:
    """
    Return True if two values are equivalent.
    For prices, allows ±tolerance fractional difference.
    For strings, requires exact match after normalization.
    """
    a, b = normalize_value(a), normalize_value(b)
    if a is None or b is None:
        return False
    if a == b:
        return True
    # Try numeric comparison for prices
    try:
        fa, fb = float(a.replace("/mo", "")), float(b.replace("/mo", ""))
        return abs(fa - fb) / max(abs(fa), 1e-9) <= tolerance
    except ValueError:
        return False


def auto_label(record: FreshStateRecord) -> tuple[Label, float, str]:
    """
    Auto-label a FreshState record based on extracted values.

    Returns (label, confidence, reason).

    Logic:
    - If aggregator_value matches answer_current → Fresh (aggregator is up to date)
    - If aggregator_value matches answer_stale → Stale (aggregator is behind)
    - If aggregator_value is None → Ambiguous (could not extract)
    - If neither matches → Ambiguous (unexpected value)
    """
    if record.aggregator_value is None:
        return "Ambiguous", 0.0, "could not extract aggregator value"

    if record.answer_current is None:
        return "Ambiguous", 0.0, "no ground truth current value"

    if values_match(record.aggregator_value, record.answer_current):
        return "Fresh", 0.9, f"aggregator matches current: {record.aggregator_value}"

    if record.answer_stale and values_match(record.aggregator_value, record.answer_stale):
        return "Stale", 0.9, f"aggregator matches stale: {record.aggregator_value}"

    # Partial match or unknown value
    return "Ambiguous", 0.3, (
        f"aggregator={record.aggregator_value!r} "
        f"current={record.answer_current!r} "
        f"stale={record.answer_stale!r}"
    )


def needs_human_review(label: Label, confidence: float) -> bool:
    """Flag records that should go to human annotators."""
    return label == "Ambiguous" or confidence < 0.7


def apply_labels(records: list[FreshStateRecord]) -> dict:
    """
    Apply auto-labeling to all records.
    Returns a summary dict with counts.
    """
    counts = {"Fresh": 0, "Stale": 0, "Ambiguous": 0, "Valid-Old": 0, "needs_human": 0}

    for rec in records:
        label, confidence, reason = auto_label(rec)
        rec.label = label
        rec.annotator_agreement = confidence

        if needs_human_review(label, confidence):
            counts["needs_human"] += 1
            rec.collection_notes = f"[NEEDS REVIEW] {reason}"

        counts[label] += 1

    return counts
