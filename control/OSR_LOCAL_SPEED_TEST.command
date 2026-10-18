#!/bin/zsh
set -euo pipefail

if ! command -v rclone >/dev/null 2>&1; then
  echo "rclone not found" >&2
  exit 1
fi
if ! rclone listremotes | grep -qx 'gdrive:'; then
  echo "gdrive: remote not configured" >&2
  exit 1
fi

# Canonical Drive folder IDs, verified from Drive metadata. This avoids all
# path-name assumptions and bypasses Google Drive for Desktop/FUSE entirely.
LIT_FOLDER_ID='1Qc4XVjIVv3KPR39NPFHmluMgjk7NwNEA'
WEB_FOLDER_ID='1P_emXiOUNDxtu3ARLxIbTiJOSAMF7lWD'

find_tail() {
  local folder_id="$1"
  local needle="$2"
  rclone lsf gdrive: -R --files-only --drive-root-folder-id "$folder_id" 2>/dev/null | grep -F "$needle" | head -n 1 || true
}

LIT_REL=$(find_tail "$LIT_FOLDER_ID" 'literature_zh-00233-of-00233.parquet')
WEB_REL=$(find_tail "$WEB_FOLDER_ID" 'CASIA-LM_ChineseWebText2.0_partial-001554.parquet')

if [[ -n "$LIT_REL" ]]; then
  ROOT_ID="$LIT_FOLDER_ID"
  REL="$LIT_REL"
  LABEL='Literature-zh_229GB'
elif [[ -n "$WEB_REL" ]]; then
  ROOT_ID="$WEB_FOLDER_ID"
  REL="$WEB_REL"
  LABEL='ChineseWebText2.0-HighQuality_279GB'
else
  echo "Could not locate either canonical tail shard by Drive folder ID."
  echo "Literature folder ID: $LIT_FOLDER_ID"
  echo "WebText folder ID:    $WEB_FOLDER_ID"
  echo
  echo "Diagnostic commands:"
  echo "rclone lsf gdrive: -R --files-only --drive-root-folder-id '$LIT_FOLDER_ID' | tail -20"
  echo "rclone lsf gdrive: -R --files-only --drive-root-folder-id '$WEB_FOLDER_ID' | tail -20"
  exit 2
fi

REMOTE="gdrive:$REL"
RC=(--drive-root-folder-id "$ROOT_ID")

SIZE_JSON=$(rclone size --json "$REMOTE" "${RC[@]}")
SIZE=$(python3 -c 'import json,sys; j=json.load(sys.stdin); print(j.get("bytes",0))' <<< "$SIZE_JSON")
COUNT=$(python3 -c 'import json,sys; j=json.load(sys.stdin); print(j.get("count",0))' <<< "$SIZE_JSON")
if [[ "$COUNT" != "1" || "$SIZE" -le 0 ]]; then
  echo "Resolved shard but rclone size validation failed: $REMOTE" >&2
  exit 3
fi

echo "Corpus: $LABEL"
echo "Drive folder ID: $ROOT_ID"
echo "Remote test file: $REL"
echo "Remote size: $SIZE bytes"

echo
echo "== rclone head 64 MiB benchmark =="
START=$(python3 -c 'import time; print(time.time())')
rclone cat "$REMOTE" "${RC[@]}" --head 67108864 >/dev/null
END=$(python3 -c 'import time; print(time.time())')
python3 - "$START" "$END" <<'PY'
import sys
s,e=map(float,sys.argv[1:]); t=max(e-s,1e-9)
print(f"64 MiB head: {64/t:.1f} MiB/s ({t:.2f}s)")
PY

echo
echo "== rclone tail 1 MiB benchmark =="
START=$(python3 -c 'import time; print(time.time())')
rclone cat "$REMOTE" "${RC[@]}" --tail 1048576 >/dev/null
END=$(python3 -c 'import time; print(time.time())')
python3 - "$START" "$END" <<'PY'
import sys
s,e=map(float,sys.argv[1:]); t=max(e-s,1e-9)
print(f"1 MiB tail latency: {t:.3f}s")
PY

echo
echo "== one-shard real local hydration test =="
TMPDIR=$(mktemp -d /tmp/osr-speed.XXXXXX)
trap 'rm -rf "$TMPDIR"' EXIT
LOCAL="$TMPDIR/test.parquet"
START=$(python3 -c 'import time; print(time.time())')
rclone copyto "$REMOTE" "$LOCAL" "${RC[@]}" --transfers 1 --checkers 2 --stats 5s --stats-one-line
END=$(python3 -c 'import time; print(time.time())')
python3 - "$START" "$END" "$LOCAL" <<'PY'
import os,sys,time
s,e=map(float,sys.argv[1:3]); p=sys.argv[3]
mb=os.path.getsize(p)/1024/1024; t=max(e-s,1e-9)
print(f"Full shard download: {mb:.1f} MiB at {mb/t:.1f} MiB/s ({t:.2f}s)")
try:
    import pyarrow.parquet as pq
except Exception:
    print("pyarrow missing; footer test skipped")
else:
    t0=time.perf_counter(); pf=pq.ParquetFile(p); md=pf.metadata; dt=time.perf_counter()-t0
    print(f"Local Parquet footer: {dt:.3f}s | rows={md.num_rows} row_groups={md.num_row_groups}")
PY

echo
echo "Interpretation: Drive folder IDs + rclone are now the canonical Mac data path."
echo "Google Drive for Desktop/FUSE is intentionally bypassed."
