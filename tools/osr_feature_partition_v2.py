#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

import osr_feature_extractor_v1 as base


def atomic_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def inventory_identity(inventory: list[tuple[str, str, str]]) -> str:
    payload = json.dumps(
        [{"corpus": c, "repo": r, "shard": s} for c, r, s in inventory],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--partition-index", type=int, required=True)
    ap.add_argument("--partition-count", type=int, required=True)
    ap.add_argument("--limit-per-partition", type=int, default=0)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--feature-schema", default="control/feature_schema_v1.json")
    ap.add_argument("--expected-inventory-sha256", default="")
    args = ap.parse_args()

    if not (0 <= args.partition_index < args.partition_count):
        raise ValueError("partition index out of range")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    parts = out / "parts"
    parts.mkdir(exist_ok=True)

    schema_path = Path(args.feature_schema)
    schema_bytes = schema_path.read_bytes()
    schema = json.loads(schema_bytes.decode("utf-8"))
    schema_sha = hashlib.sha256(schema_bytes).hexdigest()
    machine, regexes, family = base.build_feature_machine(schema)

    inventory: list[tuple[str, str, str]] = []
    for corpus, repo in base.SOURCES:
        for filename in base.list_parquets(repo):
            inventory.append((corpus, repo, filename))
    inventory.sort(key=lambda x: (x[0], x[2]))
    inv_sha = inventory_identity(inventory)
    if args.expected_inventory_sha256 and inv_sha != args.expected_inventory_sha256:
        raise RuntimeError(
            f"inventory identity mismatch: live={inv_sha} expected={args.expected_inventory_sha256}"
        )

    assigned = [
        x for i, x in enumerate(inventory)
        if i % args.partition_count == args.partition_index
    ]
    if args.limit_per_partition > 0:
        assigned = assigned[: args.limit_per_partition]

    assigned_payload = {
        "format": "osr-feature-partition-assignment/v2",
        "partition_index": args.partition_index,
        "partition_count": args.partition_count,
        "feature_schema_sha256": schema_sha,
        "source_inventory_sha256": inv_sha,
        "assigned": [
            {"corpus": c, "repo": r, "shard": s}
            for c, r, s in assigned
        ],
    }
    atomic_json(out / "assigned.json", assigned_payload)

    started = time.time()
    successes: list[dict] = []
    failures: list[dict] = []
    shard_records: list[dict] = []
    feature_occ = Counter()
    feature_rows = Counter()
    pair_rows = Counter()
    bytes_downloaded = 0

    for ordinal, (corpus, repo, filename) in enumerate(assigned, 1):
        key = base.safe_name(f"{corpus}__{filename}")
        part_dir = parts / key
        part_dir.mkdir(parents=True, exist_ok=True)
        local = Path("/tmp") / f"osr-feature-v2-{args.partition_index}-{ordinal}.parquet"
        try:
            size, dl_seconds, shard_sha = base.download(repo, filename, local)
            bytes_downloaded += size
            shard_record, checkpoint = base.scan_shard(
                corpus,
                repo,
                filename,
                local,
                shard_sha,
                size,
                machine,
                regexes,
                family,
                part_dir,
            )
            shard_records.append(shard_record)
            for row in pq.read_table(part_dir / "feature_totals.parquet").to_pylist():
                fid = row["feature_id"]
                feature_occ[fid] += int(row["occurrences"])
                feature_rows[fid] += int(row["rows_with_feature"])
            for row in pq.read_table(part_dir / "cooccurrence.parquet").to_pylist():
                pair_rows[(row["feature_a"], row["feature_b"])] += int(row["rows_cooccurring"])
            successes.append({
                "corpus": corpus,
                "repo": repo,
                "shard": filename,
                "shard_sha256": shard_sha,
                "part": str(part_dir.relative_to(out)),
                "signal_rows": int(shard_record["signal_rows"]),
                "rows_nonempty": int(shard_record["rows_nonempty"]),
                "download_bytes": int(size),
                "download_seconds": round(dl_seconds, 3),
            })
            base.append_jsonl(out / "checkpoint.jsonl", {
                "status": "COMPLETE",
                "corpus": corpus,
                "repo": repo,
                "shard": filename,
                "shard_sha256": shard_sha,
                "part": str(part_dir.relative_to(out)),
            })
            print(json.dumps({
                "partition": args.partition_index,
                "progress": f"{ordinal}/{len(assigned)}",
                "status": "COMPLETE",
                "shard": filename,
                "MiB": round(size / 1048576, 2),
                "signal_rows": shard_record["signal_rows"],
            }, ensure_ascii=False), flush=True)
        except Exception as exc:  # noqa: BLE001
            failure = {
                "corpus": corpus,
                "repo": repo,
                "shard": filename,
                "error": repr(exc),
            }
            failures.append(failure)
            base.append_jsonl(out / "failures.jsonl", {"status": "FAILED", **failure})
            print(json.dumps({
                "partition": args.partition_index,
                "progress": f"{ordinal}/{len(assigned)}",
                "status": "FAILED",
                "shard": filename,
                "error": repr(exc),
            }, ensure_ascii=False), flush=True)
        finally:
            local.unlink(missing_ok=True)
            local.with_suffix(local.suffix + ".part").unlink(missing_ok=True)

        partial = {
            "format": "osr-feature-store-partition/v2",
            "status": "PARTIAL" if failures else "RUNNING",
            "partition_index": args.partition_index,
            "partition_count": args.partition_count,
            "feature_schema_version": schema.get("version"),
            "feature_schema_sha256": schema_sha,
            "source_inventory_sha256": inv_sha,
            "assigned_shards": len(assigned),
            "completed_shards": len(successes),
            "failed_shards": len(failures),
            "bytes_downloaded": bytes_downloaded,
            "elapsed_seconds": round(time.time() - started, 3),
            "successes": successes,
            "failures": failures,
            "raw_text_persisted": False,
        }
        atomic_json(out / "manifest.partial.json", partial)

    summary = {
        "format": "osr-feature-partition-summary/v2",
        "status": "COMPLETE" if not failures and len(successes) == len(assigned) else "PARTIAL",
        "partition_index": args.partition_index,
        "partition_count": args.partition_count,
        "feature_schema_version": schema.get("version"),
        "feature_schema_sha256": schema_sha,
        "source_inventory_sha256": inv_sha,
        "assigned_shards": len(assigned),
        "completed_shards": len(successes),
        "failed_shards": len(failures),
        "bytes_downloaded": bytes_downloaded,
        "rows_scanned": sum(int(x.get("rows_nonempty") or 0) for x in shard_records),
        "signal_rows": sum(int(x.get("signal_rows") or 0) for x in shard_records),
        "elapsed_seconds": round(time.time() - started, 3),
        "shards": shard_records,
        "features": [
            {
                "feature_id": fid,
                "family": family.get(fid, "unknown"),
                "occurrences": int(feature_occ[fid]),
                "rows_with_feature": int(feature_rows[fid]),
            }
            for fid in sorted(feature_occ)
        ],
        "cooccurrence": [
            {
                "feature_a": a,
                "feature_b": b,
                "rows_cooccurring": int(n),
            }
            for (a, b), n in sorted(pair_rows.items())
        ],
        "successes": successes,
        "failures": failures,
        "raw_text_persisted": False,
        "runner": os.environ.get("RUNNER_NAME"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "github_sha": os.environ.get("GITHUB_SHA"),
    }
    atomic_json(out / "partition_summary.json", summary)
    atomic_json(out / "manifest.json", {
        k: v for k, v in summary.items()
        if k not in {"shards", "features", "cooccurrence"}
    })
    print(json.dumps({
        "status": summary["status"],
        "partition_index": args.partition_index,
        "assigned_shards": len(assigned),
        "completed_shards": len(successes),
        "failed_shards": len(failures),
        "bytes_downloaded": bytes_downloaded,
        "elapsed_seconds": summary["elapsed_seconds"],
    }, ensure_ascii=False))
    return 0 if summary["status"] == "COMPLETE" else 3


if __name__ == "__main__":
    raise SystemExit(main())
