from __future__ import annotations

import argparse
import collections
import gzip
import json
from pathlib import Path

EXPECTED_FULL_SHARDS = 1788


def merge_bounded(target: dict[str, list[dict]], incoming: dict[str, list[dict]], limit: int) -> None:
    for key, rows in incoming.items():
        seen = {x.get("sample_sha256") for x in target[key]}
        for row in rows:
            h = row.get("sample_sha256")
            if h in seen:
                continue
            target[key].append(row)
            seen.add(h)
            if len(target[key]) >= limit:
                break


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--sample-limit", type=int, default=60)
    ap.add_argument("--max-pilot-artifact-mib", type=float, default=5.0)
    args = ap.parse_args()

    indir = Path(args.input_dir)
    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    stats = collections.Counter()
    term_occurrences = collections.Counter()
    term_rows = collections.Counter()
    group_occurrences = collections.Counter()
    anchor_group_counts = collections.Counter()
    pair_counts = collections.Counter()
    term_samples: dict[str, list[dict]] = collections.defaultdict(list)
    pair_samples: dict[str, list[dict]] = collections.defaultdict(list)
    errors: list[dict] = []
    modes = set()
    corpus_seen = set()
    pack_ids = set()
    worker_meta = []
    max_worker_mib = 0.0

    for meta_path in sorted(indir.rglob("worker-*-meta.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        worker_meta.append(meta)
        max_worker_mib = max(max_worker_mib, float(meta.get("artifact_mib", 0.0)))

    for path in sorted(indir.rglob("worker-*-compact.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            obj = json.load(fh)
        if obj.get("mode"):
            modes.add(obj["mode"])
        if obj.get("corpus_parquet_files_seen") is not None:
            corpus_seen.add(int(obj["corpus_parquet_files_seen"]))
        if obj.get("pack_id"):
            pack_ids.add(obj["pack_id"])
        stats.update(obj.get("stats", {}))
        term_occurrences.update(obj.get("term_occurrences", {}))
        term_rows.update(obj.get("term_rows", {}))
        group_occurrences.update(obj.get("group_occurrences", {}))
        anchor_group_counts.update(obj.get("anchor_group_counts", {}))
        pair_counts.update(obj.get("priority_pair_counts", {}))
        errors.extend(obj.get("errors", []))
        merge_bounded(term_samples, obj.get("term_samples", {}), args.sample_limit)
        merge_bounded(pair_samples, obj.get("pair_samples", {}), args.sample_limit)

    mode = next(iter(modes)) if len(modes) == 1 else ("unknown" if not modes else "mixed")
    corpus_count = next(iter(corpus_seen)) if len(corpus_seen) == 1 else None
    assigned = int(stats.get("assigned_shards", 0))
    completed = int(stats.get("completed_shards", 0))
    failed = int(stats.get("failed_shards", 0))
    full_verified = (
        mode == "full"
        and corpus_count == EXPECTED_FULL_SHARDS
        and assigned == EXPECTED_FULL_SHARDS
        and completed == EXPECTED_FULL_SHARDS
        and failed == 0
        and not errors
    )
    pilot_size_pass = mode != "pilot" or max_worker_mib <= args.max_pilot_artifact_mib

    status = {
        "stage": "GONGGONG_GUN_PHONETIC_COMPACT_V1",
        "mode": mode,
        "pack_ids": sorted(pack_ids),
        "status": "PASS" if full_verified else ("PILOT_PASS" if mode == "pilot" and failed == 0 and pilot_size_pass else "PARTIAL_OR_FAILED"),
        "full_corpus_verified": full_verified,
        "pilot_size_gate_pass": pilot_size_pass,
        "max_worker_artifact_mib": max_worker_mib,
        "max_pilot_artifact_mib": args.max_pilot_artifact_mib,
        "corpus_parquet_files_seen": corpus_count,
        "assigned_shards": assigned,
        "completed_shards": completed,
        "failed_shards": failed,
        "error_count": len(errors),
        "evidence_rule": "Compact counts and bounded samples are discovery evidence only; rehydrate and date sources before identity judgments."
    }

    result = {
        "status": status,
        "stats": dict(stats),
        "term_occurrences": term_occurrences.most_common(),
        "term_rows": term_rows.most_common(),
        "group_occurrences": group_occurrences.most_common(),
        "anchor_group_counts": anchor_group_counts.most_common(),
        "priority_pair_counts": pair_counts.most_common(),
        "term_samples": dict(term_samples),
        "pair_samples": dict(pair_samples),
        "errors": errors,
        "worker_meta": worker_meta,
    }
    (outdir / "gonggong-gun-phonetic-compact.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    (outdir / "gonggong-gun-phonetic-status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )

    # Guardrail: a pilot that already creates oversized compact artifacts must fail loudly.
    if mode == "pilot" and not pilot_size_pass:
        raise SystemExit(f"Pilot artifact size gate failed: max worker {max_worker_mib:.2f} MiB > {args.max_pilot_artifact_mib:.2f} MiB")
    if failed:
        raise SystemExit(f"Worker shard failures: {failed}")


if __name__ == "__main__":
    main()
