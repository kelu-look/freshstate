# FreshState

A benchmark for detecting stale evidence in web-augmented LLMs.

FreshState monitors live web pages and registry metadata, records
ground-truth change events (price updates, version releases, listing
expirations), and uses them to evaluate whether language models
propagate stale information from outdated search snippets.

**Paper:** *FreshState: A Prospective Benchmark and Resource for
Stale Evidence in Web-Augmented LLMs* (CIKM 2026 Resource Track
submission).

## Quickstart

```bash
# 1. Install deps (no API key needed)
pip install -r requirements.txt

# 2. Rebuild the labeled Task 1 eval set (602 examples, 3 domains)
python build_eval_set.py

# 3. Run cheap baselines + LLM verifier (from cached predictions)
python run_baselines.py --eval_set data/eval_task1.jsonl

# 4. Print every paper table at once
python reproduce_tables.py
```

Steps 1–4 reproduce every numerical claim in the paper without any
API key, network access, or GPU. `reproduce_tables.py` also prints
an **EXPECTED OUTPUTS** block listing the exact numbers a reviewer
should see, so the smoke test takes well under a minute.

**Notes**

- The LLM verifier rerun (`run_verifier.py`) requires `OPENAI_API_KEY`.
- Saved LLM outputs (verifier + snippet-swap, 3 models) are included in `results/`.
- Manual validation logs are included in `validation/` (price, GitHub, expiration).
- The snippet-swap rerun (`run_experiment.py`) requires both OpenAI and Anthropic keys; the saved logs in `results/experiment_*.jsonl` are sufficient for verification.

**Main files**

- `data/eval_task1.jsonl` — 602-example age-matched Task 1 eval set (3 domains)
- `data/eval_task1_naive.jsonl` — naive construction for the Table 4 ablation
- `data/schema.md` — field-by-field data card
- `seeds/` — 696 change-event seeds across Craigslist, GitHub, PyPI
- `results/` — saved baseline and LLM verifier outputs
- `validation/` — saved manual audit logs (price, GitHub, expiration)
- `prompts/` — system + user prompt files used by the LLM scripts

### What each step needs

| Step | API key | Network | Cost |
|---|---|---|---|
| `reproduce_tables.py` (verification path) | no | no | $0 |
| `build_eval_set.py` | no | no | $0 |
| `run_baselines.py` (Tables 4, 5) | no | no | $0 |
| `run_verifier.py` (LLM verifier row) | **OpenAI** | yes | ~$0.12 |
| `run_experiment.py` (Table 7) | **OpenAI + Anthropic** | yes | ~$2.50 |
| `validate_extractors.py` (interactive audit) | no | yes (fetches URLs) | $0 |
| `pypi_collect.py` (re-fetch PyPI seeds) | no | yes (PyPI JSON API) | $0 |

## Resource at a glance

- **Three domains**: Craigslist apartments (HTML), GitHub releases
  (HTML), PyPI packages (JSON registry API)
- **4,301 web URLs + 979 registry packages** monitored
- **696 ground-truth change events** (75 apartment + 407 GitHub +
  214 PyPI)
- **602-example Task 1 evaluation set** (`data/eval_task1.jsonl`):
  301 stale + 301 fresh, class- and age-balanced per domain
- **Three benchmark tasks** (stale-evidence detection,
  freshness-aware verification, reranking)
- **Six baselines** spanning a random-chance floor (≤50.3%) and an
  extractor-verifier ceiling (100% by construction; 82.8–100% in
  validation)
- **Snippet-swap diagnostic**: all three tested LLMs (GPT-4o,
  GPT-4o-mini, Claude Sonnet) echo stale snippets 100% of the time,
  confirming faithful generation propagates retrieval staleness

## Setup

```bash
pip install -r requirements.txt
```

Optional model reruns require API keys (saved outputs in `results/`
are sufficient for verification, so this step is not needed for the
quickstart path):

```bash
export OPENAI_API_KEY="..."
export ANTHROPIC_API_KEY="..."
```

## Three Domains

| Domain | Source | Entities | Seeds | Notes |
|---|---|---|---|---|
| Apartments | Craigslist SF Bay | 4,144 URLs | 75 price changes | ~1% price + ~23% expiration / day |
| Software | GitHub Releases | 157 URLs (post-cleanup) | 407 version changes | ~17% / day |
| PyPI | PyPI JSON API | 979 packages | 214 version changes | ~2.5% / day |

Software-pool reconciliation: 200 GitHub candidates → 192 baselined
(8 had no parseable release tag) → 194 in-window (2 first releases
during monitoring) → 157 after the low-confidence cleanup pass
(38 audited, 1 rescued, 37 removed). See `data/schema.md` for the
full data card and the paper §Validation for the validation-driven
cleanup details.

## Daily Data Collection

Run these two commands once per day:

```bash
# Apartment listings (collects new candidates + monitors all tracked URLs)
bash roll_craigslist.sh

# Software releases
python monitor.py \
    --candidates candidates/software_stable.txt \
    --domain software \
    --state monitor_state_software.json \
    --seeds seeds/software_monitored.jsonl
```

## Reproducing the paper

The fastest reviewer path:

```bash
# Print every table in the paper using the included results files:
python reproduce_tables.py
```

This reads the pre-computed seeds, eval sets, baseline results, and
validation logs included in the artifact and prints all paper tables
plus an "EXPECTED OUTPUTS" block that lets you spot-check numbers
against the paper without re-running anything.

To regenerate from scratch:

```bash
# 1. Build the labeled Task 1 evaluation sets (602 examples each, 3 domains)
python build_eval_set.py                         # age-matched (the release set)
python build_eval_set.py --naive \
    --output data/eval_task1_naive.jsonl         # naive ablation set

# 2. Cheap baselines (no API key needed) — Table 5 + ablation
python run_baselines.py --eval_set data/eval_task1.jsonl
python run_baselines.py --eval_set data/eval_task1_naive.jsonl \
    --output results/baselines_naive.json

# 3. LLM verifier baseline (requires OPENAI_API_KEY, ~$0.06 in API calls)
python run_verifier.py --model gpt-4o-mini \
    --eval-set data/eval_task1.jsonl \
    --output results/verifier_task1.jsonl

# 4. Snippet-swap diagnostic — Table 7 (requires OPENAI/Anthropic keys; ~$2.50 total)
python run_experiment.py --model gpt-4o      --output results/experiment_gpt4o.jsonl
python run_experiment.py --model gpt-4o-mini --output results/experiment_gpt4o_mini.jsonl
python run_experiment.py --model claude-sonnet-4-20250514 --output results/experiment_claude.jsonl

# 5. Manual extractor validation (interactive, opens URLs in browser)
python validate_extractors.py --extractor expiration --n 100
python validate_extractors.py --extractor price --n 1000 \
    --live-only --target-judged 50          # apartments expire fast; pre-fetch and skip
python validate_extractors.py --extractor github --n 100

# Print every paper table with current numbers:
python reproduce_tables.py
```

Expected results match the EXPECTED OUTPUTS block printed by
`reproduce_tables.py`; reviewer-facing values are also listed in the
paper's tables.

## Pipeline Overview

```
get_candidates.py      Collect candidate URLs (Craigslist, GitHub)
        |
   [baseline]          Fetch each URL, extract initial value
        |
    monitor.py         Daily: re-fetch, detect value changes → seeds
        |
 run_experiment.py     Snippet-swap: fresh vs stale context → LLM accuracy
```

## File Structure

```
freshstate/
├── README.md                       # this file
├── LICENSE.md                      # license map (code, data, prompts, deps)
├── LICENSE-CODE-MIT.txt            # MIT (project-authored code)
├── LICENSE-DATA-CC-BY-4.0.txt      # CC BY 4.0 (curated records + docs)
├── requirements.txt
├── get_candidates.py               # Candidate URL collection (Craigslist, GitHub)
├── pypi_collect.py                 # PyPI JSON-API collector (PEP 440)
├── collect_top_packages.py         # Top-1000 PyPI snapshot fetch
├── monitor.py                      # Daily change monitor (confidence-floor filtered)
├── setup_monitor.py                # One-time setup
├── roll_craigslist.sh              # Daily apartment collection script
├── extractors.py                   # Price / GitHub-release extractors
├── wayback_client.py               # Wayback Machine CDX API + live fetch
├── build_eval_set.py               # Constructs the Task 1 labeled eval set
├── run_baselines.py                # Task 1 cheap baselines (age, prior, LR)
├── run_verifier.py                 # Task 1 LLM verifier baseline
├── run_experiment.py               # Snippet-swap LLM experiment
├── validate_extractors.py          # Interactive manual validation tool
├── clean_state.py                  # Confidence-floor cleanup pass
├── rescore_expiration.py           # Rescore expiration audit under aligned 4xx definition
├── reproduce_tables.py             # Prints all paper tables in one command
├── candidates/
│   └── pypi_top_1000.txt           # top 1,000 PyPI packages by 30-day downloads
├── data/
│   ├── eval_task1.jsonl            # 602 labeled stale/fresh snippet pairs (3 domains)
│   ├── eval_task1_naive.jsonl      # ablation: naive construction
│   ├── pypi_extraction_failures.jsonl  # 21 packages excluded (no_stable_before_window)
│   └── schema.md                   # field-by-field data card
├── seeds/                          # 696 change-event seeds (75 apt + 407 GitHub + 214 PyPI)
├── monitor_state_*.json            # latest extracted value per URL/package (3 files)
├── prompts/                        # system + user prompts for verifier and snippet-swap
├── results/                        # saved baseline + verifier + snippet-swap outputs
└── validation/                     # manual audit logs (price, GitHub, expiration)
```

## Extending to New Domains

1. Add a URL collector in `get_candidates.py` (new `get_*()` function)
2. Add an extractor in `extractors.py` (CSS selectors + regex fallback)
3. Register the domain in `extract_value()` dispatch
4. Run `monitor.py --domain your_domain`

## Licensing

- Project-authored source code and reproduction scripts: **MIT License**. See [`LICENSE-CODE-MIT.txt`](LICENSE-CODE-MIT.txt).
- FreshState-curated benchmark records, evaluation sets, state/metadata files, validation logs, result files, prompt templates, saved model-output records, schema documentation, and README documentation: **CC BY 4.0**. See [`LICENSE-DATA-CC-BY-4.0.txt`](LICENSE-DATA-CC-BY-4.0.txt).
- Underlying third-party webpages, repository content, registry/platform content, trademarks, and third-party software dependencies are **not relicensed** by FreshState. See [`LICENSE.md`](LICENSE.md) for the full licensing map.

## Citation

```bibtex
@inproceedings{lu2026freshstate,
  title     = {FreshState: A Prospective Benchmark and Resource for Stale Evidence in Web-Augmented LLMs},
  author    = {Lu, Ke},
  booktitle = {Proceedings of the 35th ACM International Conference on Information and Knowledge Management (CIKM Resource Track)},
  year      = {2026},
}
```
