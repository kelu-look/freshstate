# FreshState

A benchmark for detecting stale information in web search and RAG pipelines.

FreshState monitors live web pages daily, records ground-truth change events (price updates, version releases, listing expirations), and uses them to evaluate whether language models propagate stale information from outdated search snippets.

**Paper:** *FreshState: A Prospective Benchmark for Detecting Stale Information in Web Search* (ICLR 2026 submission)

## Key Finding

In a controlled snippet-swap experiment on 164 change events across 3 models (GPT-4o, GPT-4o-mini, Claude Sonnet):

| Condition | Current% | Stale% | Abstain% |
|-----------|----------|--------|----------|
| A (Fresh context) | **100%** | 0% | 0% |
| B (Stale context) | 0% | **100%** | 0% |
| C (No context) | 0% | 0% | ~99% |

**All models echo stale values 100% of the time when given outdated search snippets.** Staleness in the retrieval index propagates directly to factual errors in model outputs.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env  # add your API keys
```

## Two Domains

| Domain | Source | URLs Tracked | Seeds (14 days) | Daily Change Rate |
|--------|--------|-------------|-----------------|-------------------|
| Apartments | Craigslist SF Bay | ~2,500 | 68 price changes | ~1% price + ~23% expiration |
| Software | GitHub Releases | 194 | 406 version changes | ~17% |

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

## Snippet-Swap Experiment

After collecting enough seeds, run the evaluation:

```bash
# GPT-4o
python run_experiment.py --model gpt-4o --output results/experiment_gpt4o.jsonl

# GPT-4o-mini
python run_experiment.py --model gpt-4o-mini --output results/experiment_gpt4o_mini.jsonl

# Dry run (see prompts without API calls)
python run_experiment.py --dry-run --limit 5
```

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
├── get_candidates.py       # Candidate URL collection (Craigslist, GitHub, Wikipedia)
├── monitor.py              # Daily change monitor
├── setup_monitor.py        # One-time setup (CDX-based candidate discovery)
├── roll_craigslist.sh      # Daily apartment collection script
├── run_experiment.py       # Snippet-swap LLM experiment
├── extractors.py           # Price / version / availability extraction from HTML
├── wayback_client.py       # Wayback Machine CDX API + live fetch
├── schema.py               # FreshStateRecord dataclass
├── label.py                # Auto-labeling (Fresh/Stale/Ambiguous)
├── snippet_swap.py         # Original 5-condition experiment (Strategy A)
├── seeds/                  # Change-event seeds (benchmark artifact)
│   ├── apartment_monitored_v2.jsonl
│   └── software_monitored.jsonl
├── paper/                  # LaTeX source (ICLR 2026 format)
└── requirements.txt
```

## Extending to New Domains

1. Add a URL collector in `get_candidates.py` (new `get_*()` function)
2. Add an extractor in `extractors.py` (CSS selectors + regex fallback)
3. Register the domain in `extract_value()` dispatch
4. Run `monitor.py --domain your_domain`

## Citation

```bibtex
@inproceedings{freshstate2026,
  title     = {FreshState: A Prospective Benchmark for Detecting Stale Information in Web Search},
  author    = {Anonymous},
  booktitle = {International Conference on Learning Representations (ICLR)},
  year      = {2026},
}
```
