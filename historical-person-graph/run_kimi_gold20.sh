#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

OUT_DIR="${OUT_DIR:-historical-person-graph/live-out}"
MODEL="${SUB2API_MODEL:-${KIMI_MODEL:-kimi}}"
TMP_DIR="$OUT_DIR/.candidate"
rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"

# Support two execution modes:
# 1. Existing logged-in Kimi Code session: set KIMI_CODE_PRE_EXTRACTED to a JSONL
#    file of {id, extraction} records (no API key / Sub2API gateway needed).
# 2. Sub2API/Kimi gateway: set SUB2API_BASE_URL + SUB2API_API_KEY.
PRE_EXTRACTED_ARG=""
if [ -n "${KIMI_CODE_PRE_EXTRACTED:-}" ]; then
  PRE_EXTRACTED_ARG="--pre-extracted-jsonl $KIMI_CODE_PRE_EXTRACTED"
else
  : "${SUB2API_BASE_URL:?Set SUB2API_BASE_URL to the existing Sub2API gateway, or set KIMI_CODE_PRE_EXTRACTED for local-session mode}"
  : "${SUB2API_API_KEY:?Set SUB2API_API_KEY to the project-specific key, or set KIMI_CODE_PRE_EXTRACTED for local-session mode}"
fi

# Build into a disposable candidate directory. Nothing is promoted until the
# source-grounding + semantic gold audit passes.
python3 tools/osr_historical_person_graph.py build \
  --input historical-person-graph/fixtures/lvguang_gold_20.jsonl \
  --db "$TMP_DIR/lvguang_gold_20.sqlite" \
  --graph-json "$TMP_DIR/lvguang_gold_20.graph.json" \
  ${PRE_EXTRACTED_ARG:+$PRE_EXTRACTED_ARG} \
  --model "$MODEL" \
  --max-records 20 \
  --fail-fast \
  | tee "$TMP_DIR/run.log"

python3 tools/osr_historical_person_graph_audit.py \
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
