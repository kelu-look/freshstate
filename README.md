# FreshState

**FreshState: An Endpoint-Validated, Age-Matched Benchmark for Stale
Evidence in Web-Augmented Language Models.**

FreshState is a benchmark for detecting stale evidence in web-augmented
LLMs. It monitors web pages and registry metadata, records
endpoint-validated change records (price updates, version releases,
expiration), and uses them to evaluate whether language models propagate
stale information from outdated search snippets.

---

## Canonical frozen release (v2.0)

> **Zenodo DOI:** https://doi.org/10.5281/zenodo.20416346
> **Filename:** `freshstate_artifact_v2_optionD_final_publishable.zip`
> **Verified ZIP SHA-256:**
> `e43036b3665afee2974379a549047bde8994395c6a4fc91e2332ec92bec00506`
>
> The Zenodo v2 deposit is the immutable, citable, fully reproducible
> artifact corresponding to the paper. **This GitHub repository is the
> living project workspace and may evolve after the archived release.**
> Use the Zenodo v2 ZIP for reproduction; use this repository to follow
> ongoing development.

---

## What v2 contains

- **524-example Task 1 evaluation set** = 262 stale + 262 fresh
- **Per-domain composition:** apartment 59/59; software 63/63; PyPI 140/140
- **Exact within-domain age matching:** mean age 9.77 days in both classes;
  Kolmogorov–Smirnov D = 0, p = 1.0
- **Zero within-domain stale/fresh source overlap**
- **Query-at-aligned GPT-4o-mini verifier (temperature 0):**
  BalAcc 50.8 / Macro-F1 50.7 / AUROC 50.8 (near chance; 504 firm answers;
  256 correct; two-sided binomial p = 0.76; 95% Wilson CI [0.464, 0.551])
- **Snippet-swap diagnostic:** GPT-4o and GPT-4o-mini, with explicit
  `current` / `stale` / `abstain` / `other` outcome accounting (no
  third-model claim)
- **Software API-canonical reclassification:** 91 retained stale / 10
  reclassified fresh / 1 excluded (relative to the 102 HTML-flagged
  software candidates)

## Three v2 corrections relative to v1

1. **Endpoint-supported fresh candidates at cached and query times.**
2. **Within-domain source uniqueness on both stale and fresh sides.**
3. **API-canonical software endpoint validation replacing noisy
   HTML-extractor value assignment.**

## PyPI semantics (please read)

FreshState's PyPI answer-bearing value is **the latest PEP 440-parseable
non-prerelease, non-development release recorded in PyPI registry metadata
at the checkpoint date, retaining releases marked as yanked**. This
matches the released `pypi_collect.py` behavior and models registry-metadata
exposure rather than installer candidate selection.

The Zenodo v2 ZIP bundles a minimal PyPI registry-history snapshot
(`data/pypi_release_history_snapshot.jsonl`) and an offline audit script
(`audit_pypi_snapshot.py`) that reproduces the 214 candidate-change seeds,
979 monitor-state values, and all 140 stale + 140 fresh Task 1 PyPI
examples under the released rule. A **yanked-aware alternative would
affect 4 of 280 retained PyPI examples (1.4%)**; the four affected
examples are enumerated in the paper's Limitations and Data Card.

## Reproducing the v2 numbers

> **The current GitHub tree on `main` is not byte-identical to the v2
> Zenodo ZIP.** Several files required for v2 reproduction (the
> Option D builder, the bundled PyPI/GitHub release-history snapshots,
> the query-at-aligned verifier prompt and output, the Option D-aligned
> snippet-swap outputs, the offline PyPI audit script, etc.) are either
> absent from this repository or differ from the published versions.
> Do not attempt to reproduce v2 from a `git clone` of this repository.

To reproduce v2 numbers, download and extract the Zenodo v2 ZIP first:

```bash
# 1. Download the canonical v2 deposit from Zenodo
#    DOI:   https://doi.org/10.5281/zenodo.20416346
#    File:  freshstate_artifact_v2_optionD_final_publishable.zip
#    SHA-256: e43036b3665afee2974379a549047bde8994395c6a4fc91e2332ec92bec00506

# 2. Verify the SHA-256 against the value above
shasum -a 256 freshstate_artifact_v2_optionD_final_publishable.zip

# 3. Extract and enter the archive
unzip freshstate_artifact_v2_optionD_final_publishable.zip -d freshstate-v2
cd freshstate-v2

# 4. Install deps (no API key needed for the verification path)
pip install -r requirements.txt

# 5. Reproduce: every command below is offline (no API / no network)
python build_eval_set.py
python audit_pypi_snapshot.py
python run_baselines.py --eval_set data/eval_task1.jsonl
python reproduce_tables.py
```

`reproduce_tables.py` prints the released dataset summary, the cleanup
reconciliation, the naive-vs-age-matched ablation, the
extractor-validation results, the per-domain LLM verifier, the Task 1
baselines and Task 2 oracle ceiling, and the Option D-aligned
snippet-swap diagnostic, together with an **EXPECTED OUTPUTS** block
listing the exact numbers a reviewer should see.

## Resource at a glance (v2)

- **Three domains:** Craigslist apartments (HTML); GitHub release pages
  (HTML, with API-canonical revalidation of final software values); PyPI
  packages (structured JSON registry-history reconstruction).
- **4,301 web URLs + 979 PyPI packages** monitored.
- **696 candidate-change seeds:** web-domain seeds emitted by prospective
  daily monitoring; PyPI seeds emitted by structured registry-history
  reconstruction over the 2026-05-08 → 2026-05-17 checkpoint window.
- **524-example Task 1 evaluation set** with zero within-domain stale/fresh
  source overlap and exact within-domain age matching.
- **Three benchmark tasks:** zero-fetch stale-evidence detection,
  freshness-aware verification (a domain-appropriate endpoint-verification
  oracle), and freshness-aware reranking (defined; empirical evaluation
  deferred to future work).

## Licensing

- Project-authored source code and reproduction scripts: **MIT License**
  (`LICENSE-CODE-MIT.txt`).
- FreshState-authored annotations, labels, endpoint-support verdicts,
  selection reports, audit judgments, prompt templates, result files,
  evaluation-set organization, and documentation: **CC BY 4.0**
  (`LICENSE-DATA-CC-BY-4.0.txt`).
- Source-derived factual fields drawn from Craigslist, GitHub, or PyPI
  underlying content (release tags, package versions, rental-price values,
  URLs, HTTP statuses, minimal GitHub Releases API and PyPI
  registry-history provenance fields) are included in the Zenodo v2 ZIP
  solely as provenance required for reproduction; FreshState does not
  assert ownership over or relicense any underlying third-party platform
  content represented in those fields.
- Underlying Craigslist pages, GitHub release pages and repositories,
  PyPI registry/platform content, other third-party webpage content,
  platform trademarks, and third-party software dependencies are **not
  relicensed** by FreshState; they remain subject to their respective
  upstream rights. See `LICENSE.md` in the Zenodo v2 ZIP for the full
  license map.

## Version history

| Version | Status | DOI |
|---|---|---|
| **v2.0** (canonical, current) | **published, frozen, citable** | https://doi.org/10.5281/zenodo.20416346 |
| v1.0 (historical) | superseded; remains addressable for reproduction of v1 numbers | https://doi.org/10.5281/zenodo.20337401 |

See `CHANGELOG.md` for the v1 → v2 diff.

## Citation

```bibtex
@misc{lu2026freshstate,
  title        = {{FreshState}: {An Endpoint-Validated, Age-Matched Benchmark for Stale Evidence in Web-Augmented Language Models}},
  author       = {Lu, Ke},
  year         = {2026},
  howpublished = {Zenodo},
  doi          = {10.5281/zenodo.20416346},
  url          = {https://doi.org/10.5281/zenodo.20416346},
}
```
