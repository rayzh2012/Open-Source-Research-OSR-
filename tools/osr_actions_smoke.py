#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import pyarrow.parquet as pq
import requests

URL = "https://huggingface.co/datasets/Geralt-Targaryen/Literature-zh/resolve/main/literature_zh-00233-of-00233.parquet?download=true"
OUT = Path("/tmp/literature_zh-00233-of-00233.parquet")
RESULT = Path("control/stage2_smoke_result.json")


def main() -> int:
    t0 = time.time()
    sha = hashlib.sha256()
    total = 0
    with requests.get(URL, stream=True, timeout=(30, 120)) as r:
        r.raise_for_status()
        with OUT.open("wb") as f:
            for chunk in r.iter_content(chunk_size=8 * 1024 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                sha.update(chunk)
                total += len(chunk)
    dl_s = time.time() - t0

    t1 = time.time()
    pf = pq.ParquetFile(OUT)
    schema = pf.schema_arrow
    text_cols = [f.name for f in schema if str(f.type) in {"string", "large_string"}]
    footer_s = time.time() - t1

    sample = None
    if text_cols:
        table = pf.read_row_group(0, columns=[text_cols[0]])
        col = table.column(0)
        for i in range(min(len(col), 100)):
            v = col[i].as_py()
            if isinstance(v, str) and v:
                sample = {"column": text_cols[0], "row": i, "chars": len(v), "sha256": hashlib.sha256(v.encode("utf-8")).hexdigest()}
                break

    result = {
        "status": "PASS",
        "source": "Geralt-Targaryen/Literature-zh",
        "file": OUT.name,
        "bytes": total,
        "download_seconds": round(dl_s, 3),
        "download_mib_s": round(total / 1048576 / dl_s, 3) if dl_s else None,
        "sha256": sha.hexdigest(),
        "rows": pf.metadata.num_rows,
        "row_groups": pf.metadata.num_row_groups,
        "text_columns": text_cols,
        "footer_seconds": round(footer_s, 6),
        "sample": sample,
        "runner": os.environ.get("RUNNER_NAME"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "github_sha": os.environ.get("GITHUB_SHA"),
    }
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    OUT.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
