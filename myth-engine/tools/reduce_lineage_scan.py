from __future__ import annotations

import argparse
import collections
import csv
import gzip
import hashlib
import json
import sqlite3
from pathlib import Path

EXPECTED_FULL_SHARDS = 1788


def fallback_hash(obj: dict) -> str:
    payload = "|".join([
        str(obj.get("repo_id", "")),
        str(obj.get("shard", "")),
        str(obj.get("row_no", "")),
        str(obj.get("trigger_term", "")),
        str(obj.get("context_sha256", "")),
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", required=True)
    ap.add_argument("--output-dir", required=True)
    args = ap.parse_args()

    indir = Path(args.input_dir)
    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    db_path = outdir / "dedupe.sqlite"
    db = sqlite3.connect(db_path)
    db.execute("CREATE TABLE IF NOT EXISTS seen (h TEXT PRIMARY KEY)")

    merged = outdir / "gonggong-gun-merged-hits.jsonl.gz"
    group_counts = collections.Counter()
    pair_counts = collections.Counter()
    anchor_counts = collections.Counter()
    total_stats = collections.Counter()
    summaries = []
    errors = []
    unique_hits = 0

    with gzip.open(merged, "wt", encoding="utf-8", compresslevel=6) as out:
        for path in sorted(indir.rglob("worker-*-hits.jsonl.gz")):
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    obj = json.loads(line)
                    h = obj.get("hit_sha256") or fallback_hash(obj)
                    cur = db.execute("INSERT OR IGNORE INTO seen(h) VALUES (?)", (h,))
                    if not cur.rowcount:
                        continue
                    out.write(json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n")
                    unique_hits += 1
                    for g in obj.get("seed_groups", []):
                        group_counts[g] += 1
                    for p in obj.get("priority_pairs", []):
                        pair_counts[p] += 1
                    for a in obj.get("anchor_groups", []):
                        anchor_counts[a] += 1
        db.commit()

    modes = set()
    corpus_seen_values = set()
    active = 0
    skipped = 0
    for path in sorted(indir.rglob("worker-*-summary.json")):
        obj = json.loads(path.read_text(encoding="utf-8"))
        summaries.append(obj)
        if obj.get("skipped"):
            skipped += 1
            continue
        active += 1
        if obj.get("mode"):
            modes.add(obj["mode"])
        if obj.get("corpus_parquet_files_seen") is not None:
            corpus_seen_values.add(int(obj["corpus_parquet_files_seen"]))
        total_stats.update(obj.get("stats", {}))
        errors.extend(obj.get("errors", []))

    mode = next(iter(modes)) if len(modes) == 1 else ("unknown" if not modes else "mixed")
    corpus_seen = next(iter(corpus_seen_values)) if len(corpus_seen_values) == 1 else None
    assigned = int(total_stats.get("assigned_shards", 0))
    completed = int(total_stats.get("completed_shards", 0))
    failed = int(total_stats.get("failed_shards", 0))
    full_verified = (
        mode == "full"
        and corpus_seen == EXPECTED_FULL_SHARDS
        and assigned == EXPECTED_FULL_SHARDS
        and completed == EXPECTED_FULL_SHARDS
        and failed == 0
        and not errors
        and active > 0
    )

    status = {
        "stage": "GONGGONG_GUN_LINEAGE_CORPUS_V1",
        "mode": mode,
        "status": "PASS" if full_verified else ("PILOT_ONLY" if mode == "pilot" else "PARTIAL_OR_FAILED"),
        "full_corpus_verified": full_verified,
        "canonical_shards_expected_full": EXPECTED_FULL_SHARDS,
        "corpus_parquet_files_seen": corpus_seen,
        "assigned_shards": assigned,
        "completed_shards": completed,
        "failed_shards": failed,
        "error_count": len(errors),
        "unique_hits": unique_hits,
        "evidence_rule": "Co-occurrence is retrieval evidence only; relation type must be adjudicated against source chronology and wording."
    }
    (outdir / "gonggong-gun-scan-status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    report = {
        "status": status,
        "group_counts": group_counts.most_common(),
        "priority_pair_counts": pair_counts.most_common(),
        "anchor_counts": anchor_counts.most_common(),
        "stats": dict(total_stats),
        "errors": errors,
        "worker_summaries": summaries,
    }
    (outdir / "gonggong-gun-scan-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    with (outdir / "gonggong-gun-priority-pairs.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["pair", "hit_contexts"])
        w.writerows(pair_counts.most_common())

    db.close()
    try:
        db_path.unlink()
    except OSError:
        pass


if __name__ == "__main__":
    main()
