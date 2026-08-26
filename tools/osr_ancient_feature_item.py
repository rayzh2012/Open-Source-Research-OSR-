#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

import osr_feature_extractor_v1 as base


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe(value: str) -> str:
    stem = re.sub(r"[^0-9A-Za-z._-]+", "_", value).strip("_")[:80]
    return stem or "source"


def rclone_cat(remote: str) -> str | None:
    p = subprocess.run(["rclone", "cat", remote], text=True, capture_output=True)
    return p.stdout if p.returncode == 0 else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--item-json", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--feature-schema", default="control/feature_schema_v1.json")
    ap.add_argument("--feature-remote-root", required=True)
    args = ap.parse_args()

    item = json.loads(Path(args.item_json).read_text("utf-8"))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    part_dir = out / "features"
    part_dir.mkdir(exist_ok=True)

    schema_bytes = Path(args.feature_schema).read_bytes()
    schema = json.loads(schema_bytes.decode("utf-8"))
    schema_sha = hashlib.sha256(schema_bytes).hexdigest()
    logical_hash = hashlib.sha256(item["logical_key"].encode("utf-8")).hexdigest()[:16]
    remote_rel = "/".join([
        "v1", schema_sha, safe(item["group"]), safe(item["corpus"]),
        logical_hash, item["sha256"].lower(),
    ])
    complete_remote = args.feature_remote_root.rstrip("/") + "/" + remote_rel + "/COMPLETE.json"
    prior = rclone_cat(complete_remote)
    if prior:
        try:
            obj = json.loads(prior)
            if (
                obj.get("status") == "COMPLETE"
                and obj.get("source_parquet_sha256") == item["sha256"].lower()
                and obj.get("feature_schema_sha256") == schema_sha
            ):
                obj["status"] = "SKIPPED_ALREADY_COMPLETE"
                obj["remote_rel"] = remote_rel
                (out / "RESULT.json").write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", "utf-8")
                print(json.dumps(obj, ensure_ascii=False))
                return 0
        except Exception:
            pass

    machine, regexes, family = base.build_feature_machine(schema)
    local = Path("/tmp") / ("ancient-feature-" + hashlib.sha1(item["remote"].encode()).hexdigest()[:12] + ".parquet")
    started = time.time()
    p = subprocess.run(
        ["rclone", "copyto", item["remote"], str(local), "--retries", "8", "--low-level-retries", "16", "--stats", "30s"],
        text=True,
    )
    if p.returncode != 0:
        raise SystemExit(p.returncode)
    actual_sha = sha256_file(local)
    expected_sha = item["sha256"].lower()
    if actual_sha != expected_sha:
        raise RuntimeError(f"upstream parquet SHA mismatch expected={expected_sha} actual={actual_sha}")

    size = local.stat().st_size
    shard_record, _ = base.scan_shard(
        item["corpus"], "drive:" + item["group"], item["path"], local,
        actual_sha, size, machine, regexes, family, part_dir,
    )
    local.unlink(missing_ok=True)

    files = []
    for pth in sorted(part_dir.rglob("*")):
        if pth.is_file():
            files.append({
                "path": pth.relative_to(out).as_posix(),
                "bytes": pth.stat().st_size,
                "sha256": sha256_file(pth),
            })
    files_manifest = {
        "format": "osr-ancient-feature-files/v1",
        "source_parquet_sha256": actual_sha,
        "feature_schema_sha256": schema_sha,
        "files": files,
    }
    (out / "FILES.json").write_text(json.dumps(files_manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")

    result = {
        "format": "osr-ancient-feature-item/v1",
        "status": "COMPLETE",
        "group": item["group"],
        "corpus": item["corpus"],
        "logical_key": item["logical_key"],
        "source_remote": item["remote"],
        "source_path": item["path"],
        "source_parquet_sha256": actual_sha,
        "source_bytes": size,
        "feature_schema_version": schema.get("version"),
        "feature_schema_sha256": schema_sha,
        "rows": int(shard_record["rows"]),
        "rows_nonempty": int(shard_record["rows_nonempty"]),
        "signal_rows": int(shard_record["signal_rows"]),
        "chars": int(shard_record["chars"]),
        "feature_file_count": len(files),
        "remote_rel": remote_rel,
        "elapsed_seconds": round(time.time() - started, 3),
        "raw_text_persisted": False,
    }
    (out / "RESULT.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
