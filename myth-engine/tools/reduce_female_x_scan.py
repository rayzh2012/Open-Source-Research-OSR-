from __future__ import annotations

import argparse
import collections
import csv
import gzip
import json
import sqlite3
from pathlib import Path


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
                    cur = db.execute("INSERT OR IGNORE INTO seen(h) VALUES (?)", (h,))
                    if cur.rowcount:
                        out.write(json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n")
                        unique_hits += 1
        db.commit()

    for path in sorted(indir.rglob("worker-*-candidates.json")):
        obj = json.loads(path.read_text(encoding="utf-8"))
        candidate_counts.update(dict(obj.get("candidate_counts", [])))
        candidate_anchor_counts.update(dict(obj.get("candidate_anchor_counts", [])))

    for path in sorted(indir.rglob("worker-*-summary.json")):
        obj = json.loads(path.read_text(encoding="utf-8"))
        worker_summaries.append(obj)
        total_stats.update(obj.get("stats", {}))
        errors.extend(obj.get("errors", []))

    ranked_csv = outdir / "female-x-candidate-ranking.csv"
    with ranked_csv.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["candidate", "count", "west_geography", "chishui_water", "frog_wa", "ritual", "mythic_context"])
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

    report = {
        "unique_context_hits": unique_hits,
        "candidate_count": len(candidate_counts),
        "stats": dict(total_stats),
        "failed_shards": len(errors),
        "errors": errors,
        "top_200_candidates": candidate_counts.most_common(200),
        "worker_summaries": worker_summaries,
    }
    (outdir / "female-x-scan-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
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
