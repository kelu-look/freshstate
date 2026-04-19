#!/bin/bash
# Rolls Craigslist candidates daily:
# 1. Collect 300 fresh listings into a dated file
# 2. Baseline new URLs into the apartment state
# 3. Run the monitor on yesterday's batch
set -e
cd /Users/kelu/Documents/GitHub/freshstate

PYTHON=/Users/kelu/anaconda3/bin/python3
DATE=$(date +%Y%m%d)
CANDIDATES=candidates/craigslist_${DATE}.txt
LOG=logs/roll_craigslist_${DATE}.log

mkdir -p logs

echo "[$(date)] Starting rolling Craigslist collection..." | tee -a $LOG

# Step 1: Collect fresh candidates
$PYTHON get_candidates.py \
    --source craigslist --city sfbay \
    --output $CANDIDATES --limit 300 2>&1 | tee -a $LOG

# Step 2: Baseline new URLs (merges into shared state file)
$PYTHON -c "
import json, time, sys
from pathlib import Path
from wayback_client import fetch_live
from extractors import extract_value

candidates_path = sys.argv[1]
state_path = 'monitor_state_apartment_v2.json'

with open(candidates_path) as f:
    urls = [l.strip() for l in f if l.strip()]

state = json.loads(Path(state_path).read_text()) if Path(state_path).exists() else {}
today = __import__('datetime').date.today().isoformat()
new_baselines = 0

for url in urls:
    if url in state:
        continue
    html = fetch_live(url)
    if not html:
        time.sleep(0.8)
        continue
    value, span, conf = extract_value(html, 'apartment', 'price_change')
    if value and conf >= 0.5:
        state[url] = {'value': value, 'date': today, 'conf': conf}
        new_baselines += 1
    time.sleep(0.8)

Path(state_path).write_text(json.dumps(state))
print(f'[baseline] +{new_baselines} new baselines, {len(state)} total')
" $CANDIDATES 2>&1 | tee -a $LOG

# Step 3: Build a combined candidate list from ALL previously baselined URLs
ALL_CANDIDATES=candidates/all_apartment_urls.txt
$PYTHON -c "
import json
from pathlib import Path
state = json.loads(Path('monitor_state_apartment_v2.json').read_text())
with open('$ALL_CANDIDATES', 'w') as f:
    for url in state:
        f.write(url + '\n')
print(f'[all-candidates] {len(state)} URLs written to $ALL_CANDIDATES')
" 2>&1 | tee -a $LOG

# Step 4: Monitor ALL known URLs for changes (not just today's batch)
$PYTHON monitor.py \
    --candidates $ALL_CANDIDATES \
    --domain apartment \
    --state monitor_state_apartment_v2.json \
    --seeds seeds/apartment_monitored_v2.jsonl 2>&1 | tee -a $LOG

echo "[$(date)] Done." | tee -a $LOG
