"""
FreshState metrics.

FreshDoc@k        — fraction of queries where at least 1 fresh result appears in top-k
StaleAboveFresh@k — fraction where a stale result outranks all fresh results in top-k
SnippetMismatch@k — fraction where the top-k snippet is stale but the linked page is fresh
AmbiguousRate     — fraction of examples that could not be cleanly scored
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class RetrievalResult:
    """One result from a search/retrieval system for one query."""
    rank: int                           # 1-indexed
    url: str
    snippet: str                        # text shown as preview to the model
    page_text: Optional[str] = None     # full fetched page text (None = not fetched)

    # Labels (filled by compare_to_record)
    snippet_is_stale: Optional[bool] = None
    page_is_stale: Optional[bool] = None
    snippet_mismatch: Optional[bool] = None  # stale snippet + fresh page


@dataclass
class QueryResult:
    """All retrieval results for one FreshState query."""
    example_id: str
    system: str
    results: list[RetrievalResult]   # ordered by rank

    # Final answer (for LLM systems)
    llm_answer: Optional[str] = None
    answer_outcome: Optional[str] = None   # "current" | "stale" | "unsupported"


# ─────────────────────────────────────────────
#  Labeling individual results
# ─────────────────────────────────────────────

from label import normalize_value, values_match
from schema import FreshStateRecord


def label_result(result: RetrievalResult, record: FreshStateRecord) -> RetrievalResult:
    """
    Fill snippet_is_stale, page_is_stale, snippet_mismatch for one result.
    Compares extracted text against record.answer_current and record.answer_stale.
    """
    from extractors import extract_value

    def text_contains_value(text: Optional[str], value: Optional[str]) -> bool:
        if not text or not value:
            return False
        return normalize_value(value) in normalize_value(text)

    current = record.answer_current
    stale   = record.answer_stale

    # Snippet label
    if current and text_contains_value(result.snippet, stale) \
       and not text_contains_value(result.snippet, current):
        result.snippet_is_stale = True
    elif current and text_contains_value(result.snippet, current):
        result.snippet_is_stale = False

    # Page label (if fetched)
    if result.page_text:
        if record.domain and record.change_type:
            page_val, _, _ = extract_value(result.page_text, record.domain, record.change_type)
        else:
            page_val = None

        if page_val:
            result.page_is_stale = not values_match(page_val, current)

    # Snippet mismatch: snippet stale, page fresh
    if result.snippet_is_stale is True and result.page_is_stale is False:
        result.snippet_mismatch = True
    elif result.snippet_is_stale is not None and result.page_is_stale is not None:
        result.snippet_mismatch = False

    return result


# ─────────────────────────────────────────────
#  Per-query metric computation
# ─────────────────────────────────────────────

def fresh_doc_at_k(query_result: QueryResult, k: int = 5) -> Optional[bool]:
    """True if at least 1 result in top-k has a fresh snippet."""
    top_k = [r for r in query_result.results if r.rank <= k]
    labeled = [r for r in top_k if r.snippet_is_stale is not None]
    if not labeled:
        return None
    return any(r.snippet_is_stale is False for r in labeled)


def stale_above_fresh_at_k(query_result: QueryResult, k: int = 5) -> Optional[bool]:
    """True if the highest-ranked result in top-k with a label is stale."""
    top_k = sorted(
        [r for r in query_result.results if r.rank <= k and r.snippet_is_stale is not None],
        key=lambda r: r.rank,
    )
    if not top_k:
        return None
    has_fresh = any(r.snippet_is_stale is False for r in top_k)
    if not has_fresh:
        return None   # can't compute if no fresh result exists
    top_ranked = top_k[0]
    return top_ranked.snippet_is_stale is True


def snippet_mismatch_at_k(query_result: QueryResult, k: int = 1) -> Optional[bool]:
    """True if top-k contains a result where snippet is stale but page is fresh."""
    top_k = [r for r in query_result.results if r.rank <= k]
    labeled = [r for r in top_k if r.snippet_mismatch is not None]
    if not labeled:
        return None
    return any(r.snippet_mismatch is True for r in labeled)


# ─────────────────────────────────────────────
#  Aggregate metrics over all queries
# ─────────────────────────────────────────────

@dataclass
class MetricSummary:
    system: str
    n_queries: int
    n_ambiguous: int

    fresh_doc_at_1:  Optional[float]
    fresh_doc_at_5:  Optional[float]
    stale_above_fresh_at_5: Optional[float]
    snippet_mismatch_at_1:  Optional[float]
    answer_stale_rate:  Optional[float]    # LLM systems only
    answer_current_acc: Optional[float]   # LLM systems only
    ambiguous_rate: float

    def __str__(self) -> str:
        def pct(v):
            return f"{v:.1%}" if v is not None else "N/A"
        return (
            f"System: {self.system} (n={self.n_queries})\n"
            f"  FreshDoc@1:          {pct(self.fresh_doc_at_1)}\n"
            f"  FreshDoc@5:          {pct(self.fresh_doc_at_5)}\n"
            f"  StaleAboveFresh@5:   {pct(self.stale_above_fresh_at_5)}\n"
            f"  SnippetMismatch@1:   {pct(self.snippet_mismatch_at_1)}\n"
            f"  AnswerStaleRate:     {pct(self.answer_stale_rate)}\n"
            f"  AnswerCurrentAcc:    {pct(self.answer_current_acc)}\n"
            f"  AmbiguousRate:       {pct(self.ambiguous_rate)}\n"
        )


def aggregate(query_results: list[QueryResult], system: str) -> MetricSummary:
    n = len(query_results)
    if n == 0:
        return MetricSummary(system=system, n_queries=0, n_ambiguous=0,
                             fresh_doc_at_1=None, fresh_doc_at_5=None,
                             stale_above_fresh_at_5=None, snippet_mismatch_at_1=None,
                             answer_stale_rate=None, answer_current_acc=None,
                             ambiguous_rate=0.0)

    def safe_mean(values):
        vs = [v for v in values if v is not None]
        return sum(vs) / len(vs) if vs else None

    fd1  = safe_mean([fresh_doc_at_k(q, k=1) for q in query_results])
    fd5  = safe_mean([fresh_doc_at_k(q, k=5) for q in query_results])
    saf5 = safe_mean([stale_above_fresh_at_k(q, k=5) for q in query_results])
    sm1  = safe_mean([snippet_mismatch_at_k(q, k=1) for q in query_results])

    answer_outcomes = [q.answer_outcome for q in query_results if q.answer_outcome]
    stale_rate  = answer_outcomes.count("stale")   / len(answer_outcomes) if answer_outcomes else None
    current_acc = answer_outcomes.count("current") / len(answer_outcomes) if answer_outcomes else None

    n_ambiguous = sum(
        1 for q in query_results
        if all(r.snippet_is_stale is None for r in q.results)
    )

    return MetricSummary(
        system=system,
        n_queries=n,
        n_ambiguous=n_ambiguous,
        fresh_doc_at_1=fd1,
        fresh_doc_at_5=fd5,
        stale_above_fresh_at_5=saf5,
        snippet_mismatch_at_1=sm1,
        answer_stale_rate=stale_rate,
        answer_current_acc=current_acc,
        ambiguous_rate=n_ambiguous / n,
    )
