#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import time
from pathlib import Path

import pyarrow.parquet as pq
import requests
from huggingface_hub import HfApi, hf_hub_url

SOURCES = [
    ("Literature-zh", "Geralt-Targaryen/Literature-zh"),
    ("ChineseWebText2.0-HighQuality", "Morton-Li/ChineseWebText2.0-HighQuality"),
]


def list_parquets(repo: str) -> list[str]:
    return sorted(p for p in HfApi().list_repo_files(repo, repo_type="dataset") if p.endswith(".parquet"))


def download(repo: str, filename: str, dest: Path) -> tuple[int, float, str]:
    url = hf_hub_url(repo, filename=filename, repo_type="dataset")
    h = hashlib.sha256(); total = 0; t0 = time.time()
    with requests.get(url, stream=True, timeout=(30, 240)) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for block in r.iter_content(8 * 1024 * 1024):
                if not block:
                    continue
                f.write(block); h.update(block); total += len(block)
    return total, time.time() - t0, h.hexdigest()


def text_col(pf: pq.ParquetFile) -> str:
    names = [f.name for f in pf.schema_arrow if str(f.type) in {"string", "large_string"}]
    for n in ("text", "content", "body"):
        if n in names:
            return n
    if not names:
        raise RuntimeError("No string column")
    return names[0]


def scan_file(source: str, repo: str, filename: str, local: Path, pack: dict) -> dict:
    pf = pq.ParquetFile(local)
    colname = text_col(pf)
    terms = pack["terms"]
    sample_cap = int(pack.get("sample_hits_per_term_per_shard", 3))
    ctx = int(pack.get("context_chars", 180))
    counts = {t: 0 for t in terms}
    samples = {t: [] for t in terms}
    rows_scanned = 0
    chars_scanned = 0
    t0 = time.time()
    global_row = 0
    for batch in pf.iter_batches(batch_size=256, columns=[colname]):
        col = batch.column(0)
        for i in range(len(col)):
            text = col[i].as_py()
            row = global_row; global_row += 1
            if not isinstance(text, str) or not text:
                continue
            rows_scanned += 1; chars_scanned += len(text)
            for term in terms:
                n = text.count(term)
                if not n:
                    continue
                counts[term] += n
                if len(samples[term]) < sample_cap:
                    pos = text.find(term)
                    start = max(0, pos - ctx); end = min(len(text), pos + len(term) + ctx)
                    samples[term].append({
                        "row": row,
                        "position": pos,
                        "snippet": text[start:end],
                        "row_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    })
    elapsed = time.time() - t0
    nonzero = {k: v for k, v in counts.items() if v}
    return {
        "source": source,
        "repo": repo,
        "file": filename,
        "rows": pf.metadata.num_rows,
        "row_groups": pf.metadata.num_row_groups,
        "rows_scanned": rows_scanned,
        "chars_scanned": chars_scanned,
        "scan_seconds": round(elapsed, 3),
        "nonzero_counts": nonzero,
        "samples": {k: v for k, v in samples.items() if v},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker-index", type=int, required=True)
    ap.add_argument("--worker-count", type=int, required=True)
    ap.add_argument("--limit-per-worker", type=int, default=0)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--query-pack", default="control/stage2_query_pack.json")
    args = ap.parse_args()

    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    pack = json.loads(Path(args.query_pack).read_text("utf-8"))
    inventory = []
    for source, repo in SOURCES:
        for filename in list_parquets(repo):
            inventory.append((source, repo, filename))
    inventory.sort(key=lambda x: (x[0], x[2]))
    assigned = [x for i, x in enumerate(inventory) if i % args.worker_count == args.worker_index]
    if args.limit_per_worker > 0:
        assigned = assigned[:args.limit_per_worker]

    results = []
    bytes_downloaded = 0
    t_all = time.time()
    for n, (source, repo, filename) in enumerate(assigned, 1):
        local = Path("/tmp") / f"osr-{args.worker_index}-{n}.parquet"
        nb, ds, sha = download(repo, filename, local)
        rec = scan_file(source, repo, filename, local, pack)
        rec.update({
            "download_bytes": nb,
            "download_seconds": round(ds, 3),
            "download_mib_s": round(nb / 1048576 / ds, 3) if ds else None,
            "sha256": sha,
        })
        results.append(rec); bytes_downloaded += nb
        local.unlink(missing_ok=True)
        print(json.dumps({"progress": f"{n}/{len(assigned)}", "file": filename, "download_mib_s": rec["download_mib_s"], "hits": sum(rec["nonzero_counts"].values())}, ensure_ascii=False), flush=True)

    summary = {
        "status": "PASS",
        "worker_index": args.worker_index,
        "worker_count": args.worker_count,
        "assigned_shards": len(assigned),
        "bytes_downloaded": bytes_downloaded,
        "elapsed_seconds": round(time.time() - t_all, 3),
        "query_pack_version": pack.get("version"),
        "terms": pack["terms"],
        "results": results,
        "runner": os.environ.get("RUNNER_NAME"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
    }
    raw = json.dumps(summary, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with gzip.open(out / "result.json.gz", "wb", compresslevel=6) as f:
        f.write(raw)
    (out / "summary.json").write_text(json.dumps({k:v for k,v in summary.items() if k != "results"}, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"status":"PASS","worker":args.worker_index,"shards":len(assigned),"MiB":round(bytes_downloaded/1048576,1),"seconds":summary["elapsed_seconds"]}, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
