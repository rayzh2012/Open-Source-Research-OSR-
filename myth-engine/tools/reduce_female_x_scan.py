from __future__ import annotations

import argparse
import collections
import csv
import gzip
import json
import sqlite3
from pathlib import Path

EXPECTED_FULL_SHARDS = 1788


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
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS seen (h TEXT PRIMARY KEY)")

    merged_hits = outdir / "female-x-merged-hits.jsonl.gz"
    candidate_counts: collections.Counter[str] = collections.Counter()
    candidate_anchor_counts: collections.Counter[str] = collections.Counter()
    total_stats: collections.Counter[str] = collections.Counter()
    worker_summaries = []
    errors = []
    unique_hits = 0

    with gzip.open(merged_hits, "wt", encoding="utf-8", compresslevel=6) as out:
        for path in sorted(indir.rglob("worker-*-hits.jsonl.gz")):
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    obj = json.loads(line)
                    h = obj.get("context_sha256")
                    if not h:
                        continue
                    cur = db.execute("INSERT OR IGNORE INTO seen(h) VALUES (?)", (h,))
                    if cur.rowcount:
                        out.write(json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n")
                        unique_hits += 1
        db.commit()

    for path in sorted(indir.rglob("worker-*-candidates.json")):
        obj = json.loads(path.read_text(encoding="utf-8"))
        candidate_counts.update(dict(obj.get("candidate_counts", [])))
        candidate_anchor_counts.update(dict(obj.get("candidate_anchor_counts", [])))

    modes = set()
    requested_worker_counts = set()
    active_worker_summaries = 0
    skipped_worker_summaries = 0

    for path in sorted(indir.rglob("worker-*-summary.json")):
        obj = json.loads(path.read_text(encoding="utf-8"))
        worker_summaries.append(obj)
        if obj.get("mode"):
            modes.add(obj["mode"])
        if obj.get("worker_count") is not None:
            requested_worker_counts.add(int(obj["worker_count"]))
        if obj.get("skipped"):
            skipped_worker_summaries += 1
            continue
        active_worker_summaries += 1
        total_stats.update(obj.get("stats", {}))
        errors.extend(obj.get("errors", []))

    ranked_csv = outdir / "female-x-candidate-ranking.csv"
    with ranked_csv.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "candidate", "count", "west_geography", "chishui_water",
            "frog_wa", "ritual", "mythic_context"
        ])
        for candidate, count in candidate_counts.most_common():
            w.writerow([
                candidate,
                count,
                candidate_anchor_counts.get(f"{candidate}\twest_geography", 0),
                candidate_anchor_counts.get(f"{candidate}\tchishui_water", 0),
                candidate_anchor_counts.get(f"{candidate}\tfrog_wa", 0),
                candidate_anchor_counts.get(f"{candidate}\tritual", 0),
                candidate_anchor_counts.get(f"{candidate}\tmythic_context", 0),
            ])

    mode = next(iter(modes)) if len(modes) == 1 else ("unknown" if not modes else "mixed")
    corpus_files_seen_values = {
        int(x.get("corpus_parquet_files_seen"))
        for x in worker_summaries
        if not x.get("skipped") and x.get("corpus_parquet_files_seen") is not None
    }
    corpus_files_seen = (
        next(iter(corpus_files_seen_values))
        if len(corpus_files_seen_values) == 1 else None
    )

    assigned = int(total_stats.get("assigned_shards", 0))
    completed = int(total_stats.get("completed_shards", 0))
    failed = int(total_stats.get("failed_shards", 0))

    # FULL PASS is deliberately strict. No candidate count, partial artifact, or
    # successful reducer is allowed to masquerade as complete corpus coverage.
    if mode == "full":
        full_verified = (
            corpus_files_seen == EXPECTED_FULL_SHARDS
            and assigned == EXPECTED_FULL_SHARDS
            and completed == EXPECTED_FULL_SHARDS
            and failed == 0
            and len(errors) == 0
            and active_worker_summaries > 0
        )
        status_value = "PASS" if full_verified else "PARTIAL_OR_FAILED"
    elif mode == "pilot":
        full_verified = False
        status_value = "PILOT_ONLY"
    else:
        full_verified = False
        status_value = "UNVERIFIED"

    status = {
        "stage": "FEMALE_X_CORPUS_ENTITY_COMPILATION_V1",
        "mode": mode,
        "status": status_value,
        "full_corpus_verified": full_verified,
        "canonical_shards_expected_full": EXPECTED_FULL_SHARDS,
        "corpus_parquet_files_seen": corpus_files_seen,
        "assigned_shards": assigned,
        "completed_shards": completed,
        "failed_shards": failed,
        "error_count": len(errors),
        "active_worker_summaries": active_worker_summaries,
        "skipped_worker_summaries": skipped_worker_summaries,
        "requested_worker_counts": sorted(requested_worker_counts),
        "evidence_rule": "Candidate discovery is retrieval evidence only; no candidate name implies entity identity or merge.",
    }
    (outdir / "female-x-scan-status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    report = {
        "unique_context_hits": unique_hits,
        "candidate_count": len(candidate_counts),
        "stats": dict(total_stats),
        "failed_shards": failed,
        "errors": errors,
        "top_200_candidates": candidate_counts.most_common(200),
        "status": status,
        "worker_summaries": worker_summaries,
    }
    (outdir / "female-x-scan-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    db.close()
    try:
        db_path.unlink()
    except OSError:
        pass
    for suffix in ("-wal", "-shm"):
        try:
            Path(str(db_path) + suffix).unlink()
        except OSError:
            pass


if __name__ == "__main__":
    main()
