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


def scan_shard(local_path: str, repo_id: str, shard: str, pack: dict[str, Any], out_fh) -> dict[str, int]:
    stats = collections.Counter()
    text_col = choose_text_column(local_path)
    if not text_col:
        stats["missing_text_column"] += 1
        return dict(stats)

    seed_terms, seed_term_group = flatten_groups(pack["seed_groups"])
    seed_automaton = KeywordAutomaton(seed_terms)
    radius = int(pack.get("context_radius", 260))
    min_groups = int(pack.get("minimum_distinct_seed_groups", 2))
    single_anchor_min = int(pack.get("retain_single_group_if_anchor_groups", 3))
    seen: set[str] = set()

    for row_no, raw in iter_texts(local_path, text_col):
        text = normalize_text(raw)
        if not text:
            continue
        stats["rows"] += 1
        matches = seed_automaton.scan(text)
        if not matches:
            continue
        stats["rows_with_seed"] += 1

        # One evidence record per distinct local context, centered on each exact seed occurrence.
        for pos, term in matches:
            start = max(0, pos - radius)
            end = min(len(text), pos + len(term) + radius)
            context = text[start:end]
            seed_groups, seed_matches = groups_in_context(context, pack["seed_groups"])
            anchor_groups, anchor_matches = groups_in_context(context, pack["anchors"])
            if len(seed_groups) < min_groups and not (len(seed_groups) == 1 and len(anchor_groups) >= single_anchor_min):
                stats["filtered_low_context"] += 1
                continue

            pair_hits: list[str] = []
            seed_group_set = set(seed_groups)
            for a, b in pack.get("priority_pairs", []):
                if a in seed_group_set and b in seed_group_set:
                    pair_hits.append(f"{a}::{b}")

            normalized = normalize_text(context)
            hit_hash = sha256_text("|".join([repo_id, shard, str(row_no), term, normalized]))
            if hit_hash in seen:
                continue
            seen.add(hit_hash)
            obj = {
                "repo_id": repo_id,
                "shard": shard,
                "row_no": row_no,
                "trigger_term": term,
                "trigger_group": seed_term_group.get(term),
                "seed_groups": seed_groups,
                "seed_terms": seed_matches,
                "anchor_groups": anchor_groups,
                "anchor_terms": anchor_matches,
                "priority_pairs": pair_hits,
                "context": context,
                "context_sha256": sha256_text(normalized),
                "hit_sha256": hit_hash,
            }
            out_fh.write((json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
            stats["hits"] += 1
            stats["priority_pair_hits"] += len(pair_hits)
    return dict(stats)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query-pack", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--worker-index", type=int, required=True)
    ap.add_argument("--worker-count", type=int, required=True)
    ap.add_argument("--mode", choices=["pilot", "full"], default="full")
    ap.add_argument("--pilot-files", type=int, default=2)
    args = ap.parse_args()

    pack = json.loads(Path(args.query_pack).read_text(encoding="utf-8"))
    all_files = corpus_files()
    assigned = [x for i, x in enumerate(all_files) if i % args.worker_count == args.worker_index]
    if args.mode == "pilot":
        assigned = assigned[: args.pilot_files]

    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    hits_path = outdir / f"worker-{args.worker_index:02d}-hits.jsonl.gz"
    summary_path = outdir / f"worker-{args.worker_index:02d}-summary.json"

    aggregate = collections.Counter()
    errors: list[dict[str, str]] = []

    with gzip.open(hits_path, "wb", compresslevel=6) as out_fh:
        for repo_id, shard in assigned:
            aggregate["assigned_shards"] += 1
            tmpdir = tempfile.mkdtemp(prefix="lineage-")
            local = None
            try:
                local = hf_hub_download(repo_id=repo_id, filename=shard, repo_type="dataset", local_dir=tmpdir)
                aggregate.update(scan_shard(local, repo_id, shard, pack, out_fh))
                aggregate["completed_shards"] += 1
            except Exception as exc:
                aggregate["failed_shards"] += 1
                errors.append({"repo_id": repo_id, "shard": shard, "error": repr(exc)})
            finally:
                if local and os.path.exists(local):
                    try:
                        os.remove(local)
                    except OSError:
                        pass
                shutil.rmtree(tmpdir, ignore_errors=True)

    summary = {
        "pack_id": pack.get("pack_id"),
        "mode": args.mode,
        "worker_index": args.worker_index,
        "worker_count": args.worker_count,
        "corpus_parquet_files_seen": len(all_files),
        "stats": dict(aggregate),
        "errors": errors,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main()
