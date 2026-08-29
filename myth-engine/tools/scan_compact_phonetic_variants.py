from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable

import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download, list_repo_files

from myth_engine.core import KeywordAutomaton, normalize_text

DATASETS = [
    "Geralt-Targaryen/Literature-zh",
    "Morton-Li/ChineseWebText2.0-HighQuality",
]
TEXT_COLUMNS = ("text", "content", "raw_content", "document", "body")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def flatten_groups(groups: dict[str, list[str]]) -> tuple[list[str], dict[str, str]]:
    terms: list[str] = []
    term_group: dict[str, str] = {}
    for group, values in groups.items():
        for term in values:
            if term not in term_group:
                terms.append(term)
                term_group[term] = group
    return terms, term_group


def corpus_files() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for repo_id in DATASETS:
        for name in list_repo_files(repo_id=repo_id, repo_type="dataset"):
            if name.lower().endswith(".parquet"):
                out.append((repo_id, name))
    return sorted(out)


def choose_text_column(path: str) -> str | None:
    pf = pq.ParquetFile(path)
    names = set(pf.schema_arrow.names)
    for col in TEXT_COLUMNS:
        if col in names:
            return col
    return None


def iter_texts(path: str, column: str) -> Iterable[tuple[int, str]]:
    pf = pq.ParquetFile(path)
    row_no = 0
    for batch in pf.iter_batches(columns=[column], batch_size=2048):
        for value in batch.column(0).to_pylist():
            if isinstance(value, str) and value.strip():
                yield row_no, value
            row_no += 1


def groups_in_context(context: str, groups: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    matched_groups: list[str] = []
    matched_terms: list[str] = []
    for group, terms in groups.items():
        local = [t for t in terms if t in context]
        if local:
            matched_groups.append(group)
            matched_terms.extend(local)
    return sorted(set(matched_groups)), sorted(set(matched_terms))


def stable_sample_key(obj: dict[str, Any]) -> str:
    return sha256_text("|".join([
        str(obj.get("repo_id", "")),
        str(obj.get("shard", "")),
        str(obj.get("row_no", "")),
        str(obj.get("term", "")),
        str(obj.get("context_sha256", "")),
    ]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query-pack", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--worker-index", type=int, required=True)
    ap.add_argument("--worker-count", type=int, required=True)
    ap.add_argument("--mode", choices=["pilot", "full"], default="pilot")
    ap.add_argument("--pilot-files", type=int, default=3)
    args = ap.parse_args()

    pack = json.loads(Path(args.query_pack).read_text(encoding="utf-8"))
    seed_terms, term_group = flatten_groups(pack["seed_groups"])
    automaton = KeywordAutomaton(seed_terms)
    radius = int(pack.get("context_radius", 260))
    max_term_samples = int(pack.get("max_samples_per_term_per_worker", 24))
    max_pair_samples = int(pack.get("max_samples_per_pair_per_worker", 16))
    anchor_required = set(pack.get("always_require_anchor_groups_for_terms", []))

    all_files = corpus_files()
    assigned = [x for i, x in enumerate(all_files) if i % args.worker_count == args.worker_index]
    if args.mode == "pilot":
        assigned = assigned[: args.pilot_files]

    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    stats = collections.Counter()
    term_occurrences = collections.Counter()
    term_rows = collections.Counter()
    group_occurrences = collections.Counter()
    anchor_group_counts = collections.Counter()
    pair_counts = collections.Counter()
    shard_term_rows: dict[str, collections.Counter] = {}
    term_samples: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    pair_samples: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    errors: list[dict[str, str]] = []

    for repo_id, shard in assigned:
        stats["assigned_shards"] += 1
        tmpdir = tempfile.mkdtemp(prefix="phonetic-compact-")
        local = None
        shard_key = f"{repo_id}::{shard}"
        shard_counter = collections.Counter()
        try:
            local = hf_hub_download(repo_id=repo_id, filename=shard, repo_type="dataset", local_dir=tmpdir)
            text_col = choose_text_column(local)
            if not text_col:
                stats["missing_text_column"] += 1
                continue

            for row_no, raw in iter_texts(local, text_col):
                stats["rows"] += 1
                text = normalize_text(raw)
                if not text:
                    continue
                matches = automaton.scan(text)
                if not matches:
                    continue
                stats["rows_with_seed"] += 1

                row_seen_terms: set[str] = set()
                for pos, term in matches:
                    term_occurrences[term] += 1
                    group = term_group[term]
                    group_occurrences[group] += 1
                    row_seen_terms.add(term)

                    start = max(0, pos - radius)
                    end = min(len(text), pos + len(term) + radius)
                    context = text[start:end]
                    anchor_groups, anchor_terms = groups_in_context(context, pack["anchor_groups"])

                    if term in anchor_required and not anchor_groups:
                        stats["filtered_anchor_required"] += 1
                        continue

                    for ag in anchor_groups:
                        anchor_group_counts[f"{group}::{ag}"] += 1

                    pair_hits: list[str] = []
                    for seed_group, anchor_group in pack.get("priority_pairs", []):
                        if group == seed_group and anchor_group in anchor_groups:
                            key = f"{seed_group}::{anchor_group}"
                            pair_counts[key] += 1
                            pair_hits.append(key)

                    sample = {
                        "repo_id": repo_id,
                        "shard": shard,
                        "row_no": row_no,
                        "term": term,
                        "seed_group": group,
                        "anchor_groups": anchor_groups,
                        "anchor_terms": anchor_terms,
                        "priority_pairs": pair_hits,
                        "context": context,
                        "context_sha256": sha256_text(context),
                    }
                    sample["sample_sha256"] = stable_sample_key(sample)

                    if len(term_samples[term]) < max_term_samples:
                        term_samples[term].append(sample)
                    for pair_key in pair_hits:
                        if len(pair_samples[pair_key]) < max_pair_samples:
                            pair_samples[pair_key].append(sample)

                for term in row_seen_terms:
                    term_rows[term] += 1
                    shard_counter[term] += 1

            stats["completed_shards"] += 1
            shard_term_rows[shard_key] = shard_counter
        except Exception as exc:
            stats["failed_shards"] += 1
            errors.append({"repo_id": repo_id, "shard": shard, "error": repr(exc)})
        finally:
            if local and os.path.exists(local):
                try:
                    os.remove(local)
                except OSError:
                    pass
            shutil.rmtree(tmpdir, ignore_errors=True)

    payload = {
        "pack_id": pack.get("pack_id"),
        "mode": args.mode,
        "worker_index": args.worker_index,
        "worker_count": args.worker_count,
        "corpus_parquet_files_seen": len(all_files),
        "stats": dict(stats),
        "term_occurrences": dict(term_occurrences),
        "term_rows": dict(term_rows),
        "group_occurrences": dict(group_occurrences),
        "anchor_group_counts": dict(anchor_group_counts),
        "priority_pair_counts": dict(pair_counts),
        "shard_term_rows": {k: dict(v) for k, v in shard_term_rows.items()},
        "term_samples": dict(term_samples),
        "pair_samples": dict(pair_samples),
        "errors": errors,
        "truth_gate": pack.get("truth_gate"),
    }

    out_path = outdir / f"worker-{args.worker_index:02d}-compact.json.gz"
    with gzip.open(out_path, "wt", encoding="utf-8", compresslevel=9) as fh:
        json.dump(payload, fh, ensure_ascii=False, sort_keys=True)

    size_bytes = out_path.stat().st_size
    meta = {
        "worker_index": args.worker_index,
        "mode": args.mode,
        "assigned_shards": int(stats.get("assigned_shards", 0)),
        "completed_shards": int(stats.get("completed_shards", 0)),
        "failed_shards": int(stats.get("failed_shards", 0)),
        "artifact_bytes": size_bytes,
        "artifact_mib": round(size_bytes / (1024 * 1024), 4),
    }
    (outdir / f"worker-{args.worker_index:02d}-meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
