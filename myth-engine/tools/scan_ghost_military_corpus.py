from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import os
import shutil
import tempfile
import time
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


def anchor_groups_in_context(context: str, anchors: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    groups: list[str] = []
    terms: list[str] = []
    for group, values in anchors.items():
        local = [term for term in values if term in context]
        if local:
            groups.append(group)
            terms.extend(local)
    return sorted(set(groups)), sorted(set(terms))


def policy_allows(group: str, anchor_groups: list[str], pack: dict[str, Any]) -> tuple[bool, str]:
    policy = pack.get("policy", {}).get(group, "retain")
    aset = set(anchor_groups)
    if policy == "retain":
        return True, "direct_exact_term"
    if policy == "require_any_anchor_group":
        ok = bool(aset)
        return ok, "context_anchor_present" if ok else "missing_context_anchor"
    if policy == "require_underworld_anchor":
        ok = "underworld" in aset
        return ok, "underworld_anchor_present" if ok else "missing_underworld_anchor"
    return True, f"unknown_policy_fallback:{policy}"


def scan_shard(
    local_path: str,
    repo_id: str,
    shard: str,
    pack: dict[str, Any],
    automaton: KeywordAutomaton,
    term_group: dict[str, str],
    out_fh,
    deadline: float,
    hit_budget: int,
    seen: set[str],
) -> tuple[dict[str, int], bool]:
    stats = collections.Counter()
    text_col = choose_text_column(local_path)
    if not text_col:
        stats["missing_text_column"] += 1
        return dict(stats), False

    radius = int(pack.get("context_radius", 260))
    stop_requested = False
    for row_no, raw in iter_texts(local_path, text_col):
        if row_no % 1024 == 0 and time.monotonic() >= deadline:
            stats["deadline_inside_shard"] += 1
            stop_requested = True
            break
        if stats["hits"] >= hit_budget:
            stats["hit_budget_reached"] += 1
            stop_requested = True
            break

        text = normalize_text(raw)
        if not text:
            continue
        stats["rows"] += 1
        matches = automaton.scan(text)
        if not matches:
            continue
        stats["rows_with_term"] += 1

        for pos, term in matches:
            group = term_group[term]
            start = max(0, pos - radius)
            end = min(len(text), pos + len(term) + radius)
            context = text[start:end]
            anchor_groups, anchor_terms = anchor_groups_in_context(context, pack["anchors"])
            allowed, reason = policy_allows(group, anchor_groups, pack)
            if not allowed:
                stats[f"filtered_{group}"] += 1
                continue

            norm = normalize_text(context)
            hit_hash = sha256_text("|".join([repo_id, shard, str(row_no), term, norm]))
            if hit_hash in seen:
                stats["deduped"] += 1
                continue
            seen.add(hit_hash)
            obj = {
                "repo_id": repo_id,
                "shard": shard,
                "row_no": row_no,
                "term": term,
                "term_group": group,
                "anchor_groups": anchor_groups,
                "anchor_terms": anchor_terms,
                "policy_reason": reason,
                "context": context,
                "context_sha256": sha256_text(norm),
                "hit_sha256": hit_hash,
            }
            out_fh.write((json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
            stats["hits"] += 1
            stats[f"hits_group_{group}"] += 1
            stats[f"hits_term::{term}"] += 1

            if stats["hits"] >= hit_budget:
                stop_requested = True
                break
        if stop_requested:
            break

    return dict(stats), stop_requested


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query-pack", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--worker-index", type=int, required=True)
    ap.add_argument("--worker-count", type=int, required=True)
    ap.add_argument("--max-seconds", type=int, default=600)
    args = ap.parse_args()

    started = time.monotonic()
    deadline = started + max(60, args.max_seconds)
    pack = json.loads(Path(args.query_pack).read_text(encoding="utf-8"))
    terms, term_group = flatten_groups(pack["term_groups"])
    automaton = KeywordAutomaton(terms)
    all_files = corpus_files()
    assigned = [x for i, x in enumerate(all_files) if i % args.worker_count == args.worker_index]
    hit_budget = int(pack.get("max_hits_per_worker", 20000))

    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    hits_path = outdir / f"worker-{args.worker_index:02d}-hits.jsonl.gz"
    summary_path = outdir / f"worker-{args.worker_index:02d}-summary.json"

    aggregate = collections.Counter()
    errors: list[dict[str, str]] = []
    completed_names: list[str] = []
    seen: set[str] = set()
    stop_reason = "assigned_shards_exhausted"

    with gzip.open(hits_path, "wb", compresslevel=6) as out_fh:
        for repo_id, shard in assigned:
            remaining = deadline - time.monotonic()
            if remaining < 60:
                stop_reason = "soft_deadline_before_next_shard"
                break
            if aggregate["hits"] >= hit_budget:
                stop_reason = "worker_hit_budget"
                break

            aggregate["assigned_attempted"] += 1
            tmpdir = tempfile.mkdtemp(prefix="ghost-military-")
            local = None
            try:
                local = hf_hub_download(
                    repo_id=repo_id,
                    filename=shard,
                    repo_type="dataset",
                    local_dir=tmpdir,
                )
                stats, stop_requested = scan_shard(
                    local,
                    repo_id,
                    shard,
                    pack,
                    automaton,
                    term_group,
                    out_fh,
                    deadline,
                    hit_budget - aggregate["hits"],
                    seen,
                )
                aggregate.update(stats)
                if not stop_requested:
                    aggregate["completed_shards"] += 1
                    completed_names.append(f"{repo_id}:{shard}")
                else:
                    aggregate["partial_shards"] += 1
                    stop_reason = "deadline_or_hit_budget_inside_shard"
                    break
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

    elapsed = time.monotonic() - started
    summary = {
        "pack_id": pack.get("pack_id"),
        "worker_index": args.worker_index,
        "worker_count": args.worker_count,
        "max_seconds": args.max_seconds,
        "elapsed_seconds": round(elapsed, 3),
        "corpus_parquet_files_seen": len(all_files),
        "assigned_shards_total": len(assigned),
        "stop_reason": stop_reason,
        "stats": dict(aggregate),
        "completed_shards": completed_names,
        "errors": errors,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main()
