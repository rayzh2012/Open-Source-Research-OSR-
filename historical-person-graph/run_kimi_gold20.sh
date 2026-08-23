#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

: "${SUB2API_BASE_URL:?Set SUB2API_BASE_URL to the existing Sub2API gateway}"
: "${SUB2API_API_KEY:?Set SUB2API_API_KEY to the project-specific key}"

OUT_DIR="${OUT_DIR:-historical-person-graph/live-out}"
MODEL="${SUB2API_MODEL:-${KIMI_MODEL:-kimi}}"
mkdir -p "$OUT_DIR"

python tools/osr_historical_person_graph.py build \
  --input historical-person-graph/fixtures/lvguang_gold_20.jsonl \
  --db "$OUT_DIR/lvguang_gold_20.sqlite" \
  --graph-json "$OUT_DIR/lvguang_gold_20.graph.json" \
  --model "$MODEL" \
  --max-records 20 \
  --fail-fast \
  | tee "$OUT_DIR/run.log"

python - "$OUT_DIR/lvguang_gold_20.graph.json" <<'PY'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
obj = json.loads(p.read_text('utf-8'))
assert len(obj['sources']) == 20, len(obj['sources'])
assert len(obj['nodes']) >= 1, 'no person nodes extracted'
assert len(obj['events']) >= 1, 'no events extracted'
assert len(obj['slices']) >= 1, 'no historical slices extracted'
print(json.dumps({
    'status': 'LIVE_PASS',
    'sources': len(obj['sources']),
    'nodes': len(obj['nodes']),
    'edges': len(obj['edges']),
    'events': len(obj['events']),
    'slices': len(obj['slices']),
    'graph_json': str(p),
}, ensure_ascii=False))
PY

echo "Open historical-person-graph/explorer.html and load: $OUT_DIR/lvguang_gold_20.graph.json"
