"""
FreshState dataset schema.
One record = one example in the benchmark.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, Literal
import json


ChangeType = Literal[
    "price_change",
    "availability_change",
    "spec_change",
    "contact_change",
    "other",
]

QueryIntent = Literal["current-seeking", "archival", "underspecified"]

Label = Literal["Stale", "Fresh", "Valid-Old", "Ambiguous"]

Domain = Literal["apartment", "product"]


@dataclass
class FreshStateRecord:
    # --- Identity ---
    example_id: str
    domain: Domain
    query: str
    query_intent: QueryIntent = "current-seeking"

    # --- Temporal evidence ---
    change_type: Optional[ChangeType] = None
    T_before: Optional[str] = None          # ISO date of prior snapshot
    T_change: Optional[str] = None          # ISO date change appeared on official source
    T_query: Optional[str] = None           # ISO date query was issued
    staleness_lag_days: Optional[int] = None

    # --- Ground truth ---
    answer_current: Optional[str] = None    # official state at T_query (gold label)
    answer_stale: Optional[str] = None      # official state at T_before

    # --- Official source ---
    official_url: Optional[str] = None
    official_snippet_fresh: Optional[str] = None   # snippet from official at T_query
    official_snippet_stale: Optional[str] = None   # snippet from official at T_before
    official_page_fresh: Optional[str] = None      # full page text at T_query
    official_page_stale: Optional[str] = None      # archived page text at T_before

    # --- Aggregator source ---
    aggregator_url: Optional[str] = None
    aggregator_name: Optional[str] = None
    aggregator_snippet: Optional[str] = None
    aggregator_page: Optional[str] = None
    aggregator_value: Optional[str] = None
    aggregator_is_stale: Optional[bool] = None

    # --- Annotation ---
    label: Optional[Label] = None
    answer_bearing_span_official: Optional[str] = None
    answer_bearing_span_aggregator: Optional[str] = None
    annotator_agreement: Optional[float] = None
    adjudicated: bool = False

    # --- Collection metadata ---
    wayback_snapshot_url: Optional[str] = None
    collection_notes: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)
