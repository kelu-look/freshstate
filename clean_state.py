"""
Clean up the software state file by re-extracting current values
with the (now tightened) GITHUB_TAG_RE and the confidence floor.

For each URL in monitor_state_software.json with conf < CONF_MIN:
  1. refetch the live page
  2. re-run extract_github_release
  3. if the new extraction is conf >= CONF_MIN, update the record
  4. otherwise, REMOVE the URL from state (it can't be reliably tracked)

Also drops corresponding seeds from seeds/software_monitored.jsonl
whose URL was removed from state.

Writes a backup of the originals.
"""
import json
import shutil
import time
from pathlib import Path

from wayback_client import fetch_live
from extractors import extract_github_release


STATE_PATH = "monitor_state_software.json"
SEEDS_PATH = "seeds/software_monitored.jsonl"
CONF_MIN   = 0.5


def main():
    state = json.loads(Path(STATE_PATH).read_text())
    polluted = {u: m for u, m in state.items() if m.get("conf", 0) < CONF_MIN}
    print(f"[clean] state has {len(state)} URLs; {len(polluted)} below conf={CONF_MIN}")

    # Backup
    shutil.copy(STATE_PATH, STATE_PATH + ".bak")
    shutil.copy(SEEDS_PATH, SEEDS_PATH + ".bak")
    print(f"[clean] backups written: .bak alongside originals")

    rescued, dropped = 0, 0
    today = __import__("datetime").date.today().isoformat()

    for i, (url, meta) in enumerate(sorted(polluted.items())):
        print(f"  [{i+1}/{len(polluted)}] {url}")
        html = fetch_live(url)
        if not html:
            print(f"      fetch failed, dropping")
            del state[url]
            dropped += 1
            time.sleep(1.0)
            continue
        v, span, c = extract_github_release(html)
        if v and c >= CONF_MIN:
            state[url] = {"value": v, "date": today, "conf": c}
            rescued += 1
            print(f"      ✓ rescued: {meta.get('value')!r} -> {v!r} (conf={c})")
        else:
            del state[url]
            dropped += 1
            print(f"      ✗ dropped: still low conf ({c}) value={v!r}")
        time.sleep(1.0)

    Path(STATE_PATH).write_text(json.dumps(state, indent=2))
    print(f"\n[clean] rescued={rescued}, dropped={dropped}, "
          f"final state size={len(state)}")

    # Drop seeds whose URL is no longer in state
    seeds = [json.loads(l) for l in open(SEEDS_PATH)]
    kept_seeds = [s for s in seeds if s["official_url"] in state]
    n_dropped_seeds = len(seeds) - len(kept_seeds)
    with open(SEEDS_PATH, "w") as f:
        for s in kept_seeds:
            f.write(json.dumps(s) + "\n")
    print(f"[clean] seeds: {len(seeds)} -> {len(kept_seeds)} "
          f"(dropped {n_dropped_seeds} seeds from removed URLs)")


if __name__ == "__main__":
    main()
