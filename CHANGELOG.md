# Changelog

This file tracks public, citable FreshState releases. The canonical
frozen artifact corresponding to each release is the Zenodo deposit; this
GitHub repository is the living project workspace and may evolve after a
release. Commits to this repository do **not** change an already-published
Zenodo deposit; substantive changes are issued as a new Zenodo version.

## v2.0 — 2026-05-27 (canonical, current)

**Title:** *FreshState: An Endpoint-Validated, Age-Matched Benchmark for
Stale Evidence in Web-Augmented Language Models*.

**Canonical Zenodo deposit:**

- DOI: https://doi.org/10.5281/zenodo.20416346
- Filename: `freshstate_artifact_v2_optionD_final_publishable.zip`
- Verified SHA-256:
  `e43036b3665afee2974379a549047bde8994395c6a4fc91e2332ec92bec00506`

### Released composition

- **N = 524 = 262 stale + 262 fresh.**
- Apartment 59/59; software 63/63; PyPI 140/140.
- Exact within-domain age matching: mean age 9.77 days in both classes;
  Kolmogorov–Smirnov D = 0, p = 1.0.
- Zero within-domain stale/fresh source overlap, in addition to
  within-class source uniqueness.

### Three corrections relative to v1

1. **Endpoint-supported fresh candidates at cached and query times.**
   Fresh negatives must satisfy domain-appropriate endpoint support at
   both the cached and the query times, using only ZIP-resident
   provenance (apartment first-observed manifest; software API-canonical
   reconstruction; PyPI structured registry-history reconstruction).
2. **Within-domain source uniqueness on both stale and fresh sides.**
   Each URL/package appears at most once per (domain, label), with zero
   within-domain stale/fresh source overlap.
3. **API-canonical software endpoint validation replacing noisy
   HTML-extractor value assignment.** Final software values are defined
   as `canonical_stable_tag(releases, D)` over a bundled GitHub Releases
   API snapshot under the cutoff `T ≤ D 23:59:59 UTC`. Of the 102
   HTML-flagged software stale candidates: 91 retained as API-canonical
   stale; 10 reclassified as API-canonical fresh; 1 excluded as
   unreconstructable.

### Final query-at-aligned LLM verifier (GPT-4o-mini, temperature 0)

The Task 1 LLM verifier prompt was updated to a **query-at-aligned**
template that passes all permitted Task 1 inputs (domain, query, source
URL, cached snippet, `cached_at`, `query_at`) and asks whether the
cached snippet was accurate **on `query_at`**, without live retrieval.
Each cached prediction records
`prompt_version: "queryat_aligned_v1"`.

- BalAcc 50.8 / Macro-F1 50.7 / AUROC 50.8 (near chance).
- Firm-answer analysis: 504 firm, 256 correct, two-sided binomial
  p = 0.76, 95% Wilson CI [0.464, 0.551].
- Per-domain BalAcc: apartment 48.3; software 53.2; PyPI 50.7.

### PyPI semantics and yanked-aware sensitivity

FreshState's PyPI answer-bearing value is **the latest PEP 440-parseable
non-prerelease, non-development release recorded in PyPI registry
metadata at the checkpoint date, retaining releases marked as yanked**.
This models registry-metadata exposure rather than installer candidate
selection.

The Zenodo v2 ZIP bundles a minimal PyPI registry-history snapshot
(`data/pypi_release_history_snapshot.jsonl`) restricted to package
identifier, fetch metadata, release version, upload timestamp, and the
`yanked` flag, plus an offline audit script (`audit_pypi_snapshot.py`).
The audit reproduces, under the released rule:

- 214 / 214 PyPI candidate-change seeds
- 979 / 979 PyPI monitor-state values
- 140 / 140 retained Task 1 PyPI stale snippet values
- 140 / 140 retained Task 1 PyPI fresh snippet values
- the yanked-aware sensitivity result

A **yanked-aware alternative would affect 4 of 280 retained PyPI
examples (1.4%)**:

- STALE `dbt-adapters`: cached_at 2026-05-07, released `1.23.0`; yanked-aware: None
- FRESH `catalogue`: query_at 2026-05-17, released `2.1.0`; yanked-aware: `2.0.10`
- FRESH `cleo`: query_at 2026-05-17, released `2.2.1`; yanked-aware: `2.1.0`
- FRESH `dbt-common`: query_at 2026-05-17, released `2.0.0`; yanked-aware: `1.38.0`

### Snippet-swap diagnostic

The Option D-aligned snippet-swap diagnostic uses **GPT-4o and
GPT-4o-mini only** over the 122 retained Task 1 web-snippet events,
with explicit `current` / `stale` / `abstain` / `other` outcome
accounting. The prior `today`-anchored snippet-swap outputs have been
retired and are not part of the v2 release.

## v1.0 — 2026-05-21 (historical)

- DOI: https://doi.org/10.5281/zenodo.20337401

Initial public release. Superseded by v2.0; v1 remains addressable on
Zenodo for historical reproduction of v1 numbers. Publications reporting
v1 numbers should cite the v1 DOI; publications reporting v2 numbers
should cite the v2 DOI.
