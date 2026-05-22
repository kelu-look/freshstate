"""
Fetch the top-N most-downloaded PyPI packages.

Uses Hugo van Kemenade's daily snapshot:
  https://hugovk.github.io/top-pypi-packages/top-pypi-packages.min.json

Writes one package name per line to candidates/pypi_top_1000.txt.
"""
import argparse
import json
import sys
from pathlib import Path

import requests


SNAPSHOT_URLS = [
    "https://hugovk.github.io/top-pypi-packages/top-pypi-packages.min.json",
    "https://hugovk.github.io/top-pypi-packages/top-pypi-packages-30-days.min.json",
]


def fetch_list():
    for url in SNAPSHOT_URLS:
        try:
            resp = requests.get(url, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            rows = data.get("rows") or data.get("packages") or []
            if rows:
                print(f"  [snapshot] {url}: {len(rows)} packages")
                return rows
        except Exception as e:
            print(f"  [snapshot] {url} failed: {e}", file=sys.stderr)
    return []


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=1000)
    p.add_argument("--output", default="candidates/pypi_top_1000.txt")
    args = p.parse_args()

    rows = fetch_list()
    if not rows:
        print("[error] could not fetch top-pypi-packages snapshot", file=sys.stderr)
        sys.exit(1)
    # Each row has 'project' name + 'download_count'
    names = [r.get("project") or r.get("name") for r in rows]
    names = [n for n in names if n][: args.n]

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text("\n".join(names) + "\n")
    print(f"[done] wrote {len(names)} package names to {args.output}")


if __name__ == "__main__":
    main()
