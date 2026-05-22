# FreshState data card

**Version:** post-cleanup (after the confidence-floor / regex-tightening pass).
**Monitoring windows:**

- Web domains (Craigslist apartments, GitHub releases): 2026-04-05 to 2026-04-19 (15 days)
- PyPI registry: 2026-05-08 to 2026-05-17 (10 days)

**License.** Project-authored source code and reproduction scripts are licensed under the MIT License (`LICENSE-CODE-MIT.txt`). FreshState-curated benchmark records, evaluation sets, state/metadata files, validation logs, result files, prompt templates, saved model-output records included as experimental artifacts, schema documentation, and README documentation are licensed under CC BY 4.0 (`LICENSE-DATA-CC-BY-4.0.txt`). Underlying Craigslist pages, GitHub release pages and repositories, PyPI registry/platform content, third-party webpage content, platform trademarks, and third-party software dependencies are not relicensed; see `LICENSE.md`.

## Field checklist (across all released JSONL files)

A reader who wants to reuse the data without reading the paper should
find these fields here:

| Field | Where it appears | Type | Notes |
| --- | --- | --- | --- |
| `url` / `official_url` | seeds, state, eval_task1, validation | string | Web URL or PyPI package URL (`https://pypi.org/project/{name}/`). Always populated. |
| `example_id` | seeds | string | Stable per-event identifier, e.g., `mon_apt_0017`, `mon_pypi_0001`. |
| `domain` | eval_task1, validation | enum | One of `apartment`, `software`, `pypi`. |
| `change_type` | seeds | enum | `price_change`, `spec_change`, or `expiration`. |
| `T_before` | seeds | YYYYMMDD string | Date of the prior (stale) value's extraction. |
| `answer_stale` | seeds | string | The value extracted at `T_before` (the value before the change). |
| `_detected_on` | seeds | YYYY-MM-DD string | Date the change was first detected. |
| `value` | state | string | Most recent extracted answer-bearing value. |
| `date` | state | YYYY-MM-DD string | Date of the most recent successful extraction. |
| `conf` | state | float ∈ [0, 1] | Extractor confidence; values below 0.5 are filtered at construction. |
| `snippet` | eval_task1 | string | The constructed snippet text (template-filled). |
| `snippet_value` | eval_task1 | string | The answer-bearing value placed inside the snippet. |
| `cached_at` | eval_task1 | YYYY-MM-DD string | When the snippet was supposedly cached. |
| `query_at` | eval_task1 | YYYY-MM-DD string | Query time (end of the relevant monitoring window). |
| `age_days` | eval_task1 | int | `query_at − cached_at`, in days. |
| `query` | eval_task1 | string | The natural-language question. |
| `label` | eval_task1 | enum | `stale` or `fresh`. **Ground truth.** |
| `verdict` | validation | enum | Human judgment: `correct`, `incorrect`, or `skip`. |
| `note` | validation | string | Failure-mode tag for `incorrect`/`skip` (e.g., `prerelease_picked`, `posting_expired`). |
| `http_status` | validation | int (or null) | HTTP status returned by the live re-fetch. |
| `extracted_value` | validation | string (or null) | Value the extractor returned on the re-fetch. |
| `baseline_value` / `baseline_date` | validation | string | The value/date stored in `state` at audit time. |

Every record in `seeds/*.jsonl`, `monitor_state_*.json`,
`data/eval_task1.jsonl`, and `validation/*.jsonl` is one JSON object
with the fields above (subset depending on file).

## Files

| Path | Records | Purpose |
| --- | ---: | --- |
| `seeds/apartment_monitored_v2.jsonl` | 75  | Apartment price-change events |
| `seeds/software_monitored.jsonl`     | 407 | GitHub release-version-change events |
| `seeds/pypi_monitored.jsonl`         | 214 | PyPI stable-version-change events |
| `monitor_state_apartment_v2.json`    | 4,144 | Latest extracted value per apartment URL |
| `monitor_state_software.json`        | 157 | Latest extracted value per software URL |
| `monitor_state_pypi.json`            | 979 | Latest PEP 440 stable per PyPI package |
| `data/eval_task1.jsonl`              | 602 | Labeled stale/fresh snippet pairs (Task 1, age-matched release, 3 domains) |
| `data/eval_task1_naive.jsonl`        | 602 | Ablation set: naive stale/fresh construction (Section 6) |
| `data/pypi_extraction_failures.jsonl`| 21  | PyPI packages excluded (no_stable_before_window) |

Total monitored entities: **4,301** web URLs + **979** registry packages.
Total change events: **696** (75 apartment + 407 software + 214 PyPI).

## `seeds/*.jsonl` schema

One JSON object per line, one object per detected change event:

```json
{
  "example_id":   "mon_apt_0017",
  "official_url": "https://sfbay.craigslist.org/...",
  "change_type":  "price_change",
  "T_before":     "20260405",
  "answer_stale": "$2,400",
  "_detected_on": "2026-04-08"
}
```

| Field | Type | Description |
| --- | --- | --- |
| `example_id`   | string | Stable per-event ID. |
| `official_url` | string | The monitored URL. |
| `change_type`  | enum   | `price_change` or `spec_change`. |
| `T_before`     | string | YYYYMMDD date of the prior extraction. |
| `answer_stale` | string | The value extracted at `T_before`. |
| `_detected_on` | string | YYYY-MM-DD date when the change was detected. |

The current value (after the change) lives in the sidecar state file rather
than in the seed, so the snippet-swap diagnostic always compares against
the most recent live extraction.

## `monitor_state_*.json` schema

A JSON object mapping URL → most-recent extraction record:

```json
{
  "https://github.com/numpy/numpy/releases": {
    "value": "v2.1.3",
    "date":  "2026-04-19",
    "conf":  0.95
  }
}
```

| Field | Type | Description |
| --- | --- | --- |
| `value` | string | Most recent answer-bearing value extracted from the URL. |
| `date`  | string | YYYY-MM-DD of the most recent successful extraction. |
| `conf`  | float  | Extractor confidence ∈ [0, 1]; values < 0.5 are filtered. |

## `data/eval_task1.jsonl` schema (Task 1 labeled set)

One JSON object per line, 602 examples total (301 stale + 301 fresh,
balanced 50/50 per domain, age-matched mean 9.9 days both classes):

```json
{
  "url":           "https://github.com/...",
  "domain":        "software",
  "snippet":       "Latest release: v1.11.5. View all releases ...",
  "snippet_value": "v1.11.5",
  "cached_at":     "2026-04-10",
  "query_at":      "2026-04-19",
  "age_days":      9,
  "query":         "What is the latest release version of ...?",
  "label":         "stale"
}
```

| Field | Type | Description |
| --- | --- | --- |
| `url`           | string | Source URL the snippet purports to describe. |
| `domain`        | enum   | `apartment` or `software`. |
| `snippet`       | string | Template-generated snippet text. |
| `snippet_value` | string | The answer-bearing value the snippet contains. |
| `cached_at`     | string | YYYY-MM-DD timestamp the snippet was supposedly cached. |
| `query_at`      | string | YYYY-MM-DD timestamp the query is issued. |
| `age_days`      | int    | `query_at - cached_at` in days (1–14). |
| `query`         | string | The natural-language question. |
| `label`         | enum   | `stale` or `fresh`. Ground truth. |

## Construction notes (Task 1 set)

- **Stale positives** (301): one per deduplicated change event, with
  `snippet_value = v_old` and `cached_at = T_before`.
- **Fresh negatives** (301): drawn from URLs or packages that did **not** change in the
  monitoring window, with `cached_at` selected so that the age distribution
  exactly matches the stale-positive age distribution within domain.
- Two-sample KS test on the age distributions gives `D = 0`, `p = 1.0`
  (exact match), preventing age-shortcut classifiers.

The companion **naive ablation set** (`data/eval_task1_naive.jsonl`)
uses the same 301 change events but constructs both stale and fresh
on the *same* URL, with fresh always cached at query time. Under this
construction, age perfectly correlates with label, and a one-feature
age threshold achieves 100% balanced accuracy. The contrast with the
age-matched release (45.8%) is the empirical evidence that the
age-matching design is necessary, not merely cosmetic.

## Cleanup pass

The original monitor admitted low-confidence (`c = 0.4`) extractions for 38
software URLs; on a small number of repositories the GitHub release regex
matched page-chrome numbers such as "Fork 32.4k Star 50.7k". A cleanup pass
re-extracted with a tightened regex (requiring `v` prefix or
`major.minor.patch`) and a confidence floor `c >= 0.5`. Outcome:

| Stage | Count |
| --- | ---: |
| GitHub Search API candidates | 200 |
| Dropped at baseline (no parseable tag) | –8 |
| Baselined | 192 |
| Added during 15-day window | +2 |
| State at end of window | 194 |
| Audited as low-confidence | 38 |
| Rescued after re-extraction | +1 |
| Removed | –37 |
| **Final software pool** | **157** |

All numbers in this card, the released artifacts, and the paper are
**post-cleanup**.

## Intended uses

- Training and evaluating **stale-evidence detectors** (Task 1).
- Building and benchmarking **freshness-aware verifiers** (Task 2) and
  **rerankers** (Task 3).
- Stress-testing **RAG pipelines** with controlled fresh/stale snippet pairs.
- Extending FreshState to new domains via the documented extractor interface.

## Out-of-scope uses

- Identifying or tracking individual Craigslist posters (URLs only — no user
  metadata is collected).
- Evaluating retrieval relevance: FreshState labels temporal validity, not
  topical relevance.
- Long-horizon (months/years) freshness studies: the 15-day window captures
  short-term dynamics only.

## Collection ethics

- One HTTP request per URL per day, with 1-second rate limiting and an
  identifying `User-Agent`.
- No login walls, captchas, or anti-bot measures were circumvented.
- Only publicly visible answer-bearing values (prices, release tags) are
  recorded; no user-private data is collected.
- Sources where access was unavailable (e.g., Cloudflare-blocked
  CamelCamelCamel) were excluded.
