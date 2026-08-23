#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

: "${SUB2API_BASE_URL:?Set SUB2API_BASE_URL to the existing Sub2API gateway}"
: "${SUB2API_API_KEY:?Set SUB2API_API_KEY to the project-specific key}"

OUT_DIR="${OUT_DIR:-historical-person-graph/live-out}"
MODEL="${SUB2API_MODEL:-${KIMI_MODEL:-kimi}}"
TMP_DIR="$OUT_DIR/.candidate"
rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"

# Build into a disposable candidate directory. Nothing is promoted until the
# source-grounding + semantic gold audit passes.
python tools/osr_historical_person_graph.py build \
  --input historical-person-graph/fixtures/lvguang_gold_20.jsonl \
  --db "$TMP_DIR/lvguang_gold_20.sqlite" \
  --graph-json "$TMP_DIR/lvguang_gold_20.graph.json" \
  --model "$MODEL" \
  --max-records 20 \
  --fail-fast \
  | tee "$TMP_DIR/run.log"

python tools/osr_historical_person_graph_audit.py \
  --db "$TMP_DIR/lvguang_gold_20.sqlite" \
  --graph-json "$TMP_DIR/lvguang_gold_20.graph.json" \
  --expectations historical-person-graph/fixtures/lvguang_gold_20_expectations.json \
  --strict \
  | tee "$TMP_DIR/audit.json"

# Promote only audited output. A failed audit leaves the candidate isolated for diagnosis.
mkdir -p "$OUT_DIR"
mv "$TMP_DIR/lvguang_gold_20.sqlite" "$OUT_DIR/lvguang_gold_20.sqlite"
mv "$TMP_DIR/lvguang_gold_20.graph.json" "$OUT_DIR/lvguang_gold_20.graph.json"
mv "$TMP_DIR/run.log" "$OUT_DIR/run.log"
mv "$TMP_DIR/audit.json" "$OUT_DIR/audit.json"
rmdir "$TMP_DIR"

echo "LIVE_PASS: audited Kimi output promoted to $OUT_DIR"
echo "Open historical-person-graph/explorer.html and load: $OUT_DIR/lvguang_gold_20.graph.json"
