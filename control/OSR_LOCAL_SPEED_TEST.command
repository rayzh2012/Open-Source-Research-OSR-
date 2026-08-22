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

BASE='gdrive:龍族古籍源庫｜Dragon Source Corpus'
CANDIDATES=(
  "$BASE/BULK_SECONDARY_CORPUS/Literature-zh/literature_zh-00233-of-00233.parquet"
  "$BASE/BULK_SECONDARY_CORPUS/Literature-zh/data/literature_zh-00233-of-00233.parquet"
  "$BASE/Literature-zh_229GB/literature_zh-00233-of-00233.parquet"
  "$BASE/BULK_SECONDARY_CORPUS/ChineseWebText2.0-HighQuality/data/CASIA-LM_ChineseWebText2.0_partial-001554.parquet"
  "$BASE/BULK_SECONDARY_CORPUS/ChineseWebText2.0-HighQuality/CASIA-LM_ChineseWebText2.0_partial-001554.parquet"
  "$BASE/ChineseWebText2.0-HighQuality_279GB/data/CASIA-LM_ChineseWebText2.0_partial-001554.parquet"
  "$BASE/ChineseWebText2.0-HighQuality_279GB/CASIA-LM_ChineseWebText2.0_partial-001554.parquet"
)

REMOTE=''
SIZE=''
for p in "${CANDIDATES[@]}"; do
  j=$(rclone size --json "$p" 2>/dev/null || true)
  if [[ -n "$j" ]]; then
    count=$(python3 -c 'import json,sys; j=json.load(sys.stdin); print(j.get("count",0))' <<< "$j" 2>/dev/null || echo 0)
    bytes=$(python3 -c 'import json,sys; j=json.load(sys.stdin); print(j.get("bytes",0))' <<< "$j" 2>/dev/null || echo 0)
    if [[ "$count" == "1" && "$bytes" -gt 0 ]]; then
      REMOTE="$p"
      SIZE="$bytes"
      break
    fi
  fi
done

if [[ -z "$REMOTE" ]]; then
  echo "Could not find a canonical tail shard at known rclone paths."
  echo "Run this and paste the output:"
  echo "rclone lsf '$BASE/BULK_SECONDARY_CORPUS' --dirs-only"
  exit 2
fi

echo "Remote test file: $REMOTE"
echo "Remote size: $SIZE bytes"

echo
echo "== rclone head 64 MiB benchmark =="
START=$(python3 -c 'import time; print(time.time())')
rclone cat "$REMOTE" --head 64M >/dev/null
END=$(python3 -c 'import time; print(time.time())')
python3 - "$START" "$END" <<'PY'
import sys
s,e=map(float,sys.argv[1:])
t=max(e-s,1e-9)
print(f"64 MiB head: {64/t:.1f} MiB/s ({t:.2f}s)")
PY

echo
echo "== rclone tail 1 MiB benchmark =="
START=$(python3 -c 'import time; print(time.time())')
rclone cat "$REMOTE" --tail 1M >/dev/null
END=$(python3 -c 'import time; print(time.time())')
python3 - "$START" "$END" <<'PY'
import sys
s,e=map(float,sys.argv[1:])
t=max(e-s,1e-9)
print(f"1 MiB tail latency: {t:.3f}s")
PY

echo
echo "== one-shard real local hydration test =="
TMPDIR=$(mktemp -d /tmp/osr-speed.XXXXXX)
trap 'rm -rf "$TMPDIR"' EXIT
LOCAL="$TMPDIR/test.parquet"
START=$(python3 -c 'import time; print(time.time())')
rclone copyto "$REMOTE" "$LOCAL" --transfers 1 --checkers 2 --stats 5s --stats-one-line
END=$(python3 -c 'import time; print(time.time())')
python3 - "$START" "$END" "$LOCAL" <<'PY'
import os,sys,time
s,e=map(float,sys.argv[1:3]); p=sys.argv[3]
mb=os.path.getsize(p)/1024/1024
t=max(e-s,1e-9)
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
echo "Interpretation: this bypasses Google Drive for Desktop completely."
echo "If rclone download is healthy but Drive Desktop stat timed out, OSR should use rclone-to-local-temp streaming/cache, not ~/Library/CloudStorage as the data plane."
