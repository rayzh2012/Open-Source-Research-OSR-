#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import time
from pathlib import Path

import requests

URL = "https://huggingface.co/datasets/Geralt-Targaryen/Literature-zh/resolve/main/literature_zh-00233-of-00233.parquet?download=true"
EXPECTED_NAME = "literature_zh-00233-of-00233.parquet"


def mib(n: int) -> float:
    return n / (1024 * 1024)


def main() -> int:
    print("OSR_COLAB_HF_SMOKE_V1")
    print("python:", sys.version.replace("\n", " "))
    print("runtime_host:", os.uname().nodename)

    with tempfile.TemporaryDirectory(prefix="osr-colab-smoke-") as td:
        out = Path(td) / EXPECTED_NAME
        h = hashlib.sha256()
        total = 0
        t0 = time.perf_counter()
        with requests.get(URL, stream=True, timeout=(30, 120)) as r:
            r.raise_for_status()
            print("http_status:", r.status_code)
            print("content_length:", r.headers.get("content-length"))
            with out.open("wb") as f:
                for chunk in r.iter_content(chunk_size=8 * 1024 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    h.update(chunk)
                    total += len(chunk)
        dt = time.perf_counter() - t0
        rate = mib(total) / dt if dt else 0.0
        print(f"download: {mib(total):.1f} MiB in {dt:.2f}s = {rate:.1f} MiB/s")
        print("sha256:", h.hexdigest())

        try:
            import pyarrow.parquet as pq
        except Exception:
            print("pyarrow missing; installing...")
            import subprocess
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "pyarrow"])
            import pyarrow.parquet as pq

        t1 = time.perf_counter()
        pf = pq.ParquetFile(out)
        footer_dt = time.perf_counter() - t1
        print(f"parquet_footer: {footer_dt:.4f}s rows={pf.metadata.num_rows} row_groups={pf.metadata.num_row_groups}")
        print("columns:", ",".join(pf.schema.names))

    print("OSR_COLAB_HF_SMOKE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
