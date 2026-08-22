#!/bin/zsh
set -euo pipefail
python3 - <<'PY'
import glob, os, time
from pathlib import Path

cands=[]
for pat in (
    str(Path.home()/"Library/CloudStorage/GoogleDrive-*/My Drive"),
    str(Path.home()/"Library/CloudStorage/GoogleDrive-*/MyDrive"),
    str(Path.home()/"Google Drive/My Drive"),
    str(Path.home()/"Google Drive"),
): cands += [Path(x) for x in glob.glob(pat)]
root=next((p for p in cands if p.is_dir()),None)
if not root:
    raise SystemExit("No Google Drive for Desktop filesystem found under ~/Library/CloudStorage. Install/enable it first.")
print("Drive root:",root)
patterns=[
    "**/literature_zh-00233-of-00233.parquet",
    "**/CASIA-LM_ChineseWebText2.0_partial-001554.parquet",
]
file=None
for pat in patterns:
    hits=list(root.glob(pat))
    if hits:
        file=hits[0]; break
if not file: raise SystemExit("Could not find a canonical tail Parquet shard")
print("Test file:",file)
size=file.stat().st_size
sample=min(size,64*1024*1024)
start=time.perf_counter(); n=0
with file.open('rb') as f:
    while n<sample:
        b=f.read(min(8*1024*1024,sample-n))
        if not b: break
        n+=len(b)
elapsed=time.perf_counter()-start
print(f"Sequential first {n/1024/1024:.1f} MiB: {n/1024/1024/elapsed:.1f} MiB/s ({elapsed:.2f}s)")
start=time.perf_counter()
with file.open('rb') as f:
    f.seek(max(0,size-1024*1024)); tail=f.read(1024*1024)
elapsed=time.perf_counter()-start
print(f"Random tail 1 MiB: {elapsed:.3f}s")
try:
    import pyarrow.parquet as pq
except Exception:
    print("pyarrow missing; install with: python3 -m pip install --user pyarrow")
else:
    start=time.perf_counter(); pf=pq.ParquetFile(file); md=pf.metadata; elapsed=time.perf_counter()-start
    print(f"Parquet footer open: {elapsed:.3f}s | rows={md.num_rows} row_groups={md.num_row_groups}")
print("\nRule of thumb: >=30 MiB/s sequential and sub-2s footer/tail is workable; >=80 MiB/s is very comfortable for the identity/preflight path.")
PY
echo
read -k 1 "?Press any key to close..."
