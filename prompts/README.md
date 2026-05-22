# Prompts

These are the exact prompts used by `run_experiment.py` (snippet-swap diagnostic, Table 7) and `run_verifier.py` (LLM verifier baseline, Table 5 row 5). They are kept here as standalone files for reviewer convenience; the same strings are hard-coded in the corresponding Python scripts.

Placeholders use Python `str.format`-style braces:

* `{url}`, `{repo}` — the source URL / repository or package identifier
* `{snippet}` — the constructed web-search-result snippet, filled with either the **current** value (Condition A), the **stale** value (Condition B), or omitted entirely (Condition C / verifier prompt with no snippet)
* `{value}` — the answer-bearing value injected into the snippet template (price string or release tag)

## Files

| File | Used by | Role |
| --- | --- | --- |
| `snippet_swap_system.txt` | `run_experiment.py` | System prompt (Conditions A, B) |
| `snippet_swap_system_no_context.txt` | `run_experiment.py` | System prompt (Condition C, no snippet) |
| `snippet_swap_user_apt.txt` | `run_experiment.py` | Apartment-domain user prompt |
| `snippet_swap_user_sw.txt` | `run_experiment.py` | Software/PyPI-domain user prompt |
| `verifier_system.txt` | `run_verifier.py` | LLM verifier system prompt |
| `verifier_user.txt` | `run_verifier.py` | LLM verifier user prompt |
