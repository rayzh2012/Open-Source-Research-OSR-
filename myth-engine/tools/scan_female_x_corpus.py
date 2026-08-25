from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import os
import re
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


def flatten_seed_groups(pack: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    terms: list[str] = []
    term_group: dict[str, str] = {}
    for group, values in pack["seed_groups"].items():
        for term in values:
            if term not in term_group:
                terms.append(term)
                term_group[term] = group
    return terms, term_group


def flatten_anchor_groups(pack: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    terms: list[str] = []
    term_group: dict[str, str] = {}
    for group, values in pack["anchors"].items():
        for term in values:
            if term not in term_group:
                terms.append(term)
                term_group[term] = group
    return terms, term_group


def corpus_files() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for repo_id in DATASETS:
        files = list_repo_files(repo_id=repo_id, repo_type="dataset")
        for name in files:
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
        arr = batch.column(0).to_pylist()
        for value in arr:
            if isinstance(value, str) and value.strip():
                yield row_no, value
            row_no += 1


def anchor_groups_in_context(context: str, anchors: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    groups: list[str] = []
    matched: list[str] = []
    for group, terms in anchors.items():
        local = [t for t in terms if t in context]
        if local:
            groups.append(group)
            matched.extend(local)
    return groups, matched


def emit_hit(
    fh,
    *,
    repo_id: str,
    shard: str,
    row_no: int,
    kind: str,
    term: str,
    group: str,
    context: str,
    anchor_groups: list[str],
    anchors: list[str],
) -> str:
    context_hash = sha256_text(normalize_text(context))
    obj = {
        "repo_id": repo_id,
        "shard": shard,
        "row_no": row_no,
        "kind": kind,
        "term": term,
        "entity_group": group,
        "context": context,
        "anchor_groups": anchor_groups,
        "anchors": sorted(set(anchors)),
        "context_sha256": context_hash,
    }
    fh.write((json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
    return context_hash


def scan_shard(
    local_path: str,
    repo_id: str,
    shard: str,
    pack: dict[str, Any],
    seed_terms: list[str],
    seed_group: dict[str, str],
    out_fh,
    seen_hashes: set[str],
    candidate_counter: collections.Counter[str],
    candidate_anchor_counter: collections.Counter[str],
) -> dict[str, int]:
    stats = collections.Counter()
    text_col = choose_text_column(local_path)
    if not text_col:
        stats["missing_text_column"] += 1
        return dict(stats)

    seed_automaton = KeywordAutomaton(seed_terms)
    anchor_terms, _ = flatten_anchor_groups(pack)
    anchor_automaton = KeywordAutomaton(anchor_terms)
    female_re = re.compile(pack["discovery"]["regex"])
    stop = set(pack.get("female_x_stoplist", []))
    radius = int(pack["discovery"].get("context_radius", 180))
    min_groups = int(pack["discovery"].get("minimum_anchor_groups", 2))

    for row_no, raw in iter_texts(local_path, text_col):
        text = normalize_text(raw)
        if not text:
            continue
        stats["rows"] += 1

        # Fast reject: if neither seeds, female-X pattern prefix, nor anchors are present,
        # skip the expensive context work. The automata keep this tokenizer-free.
        seed_matches = seed_automaton.scan(text)
        discovery_possible = "女" in text
        anchor_possible = bool(anchor_automaton.scan(text)) if discovery_possible else False
        if not seed_matches and not (discovery_possible and anchor_possible):
            continue

        # Seed retrieval: identity is NOT asserted; every spelling is just a retrieval key.
        matched_seed_terms = sorted({term for _, term in seed_matches}, key=len, reverse=True)
        for term in matched_seed_terms:
            start = 0
            while True:
                pos = text.find(term, start)
                if pos < 0:
                    break
                left = max(0, pos - radius)
                right = min(len(text), pos + len(term) + radius)
                context = text[left:right]
                agroups, amatches = anchor_groups_in_context(context, pack["anchors"])
                h = sha256_text(context)
                if h not in seen_hashes:
                    seen_hashes.add(h)
                    emit_hit(
                        out_fh,
                        repo_id=repo_id,
                        shard=shard,
                        row_no=row_no,
                        kind="seed",
                        term=term,
                        group=seed_group[term],
                        context=context,
                        anchor_groups=agroups,
                        anchors=amatches,
                    )
                    stats["seed_hits"] += 1
                start = pos + max(1, len(term))

        # Discovery retrieval: retain only candidates embedded in >= N independent
        # anchor groups. This prevents modern 女主/女友 noise from flooding outputs.
        for m in female_re.finditer(text):
            candidate = m.group(0)
            if candidate in stop:
                continue
            # If this exact string is already a seed spelling, seed handling above owns it.
            if candidate in seed_group:
                continue
            left = max(0, m.start() - radius)
            right = min(len(text), m.end() + radius)
            context = text[left:right]
            agroups, amatches = anchor_groups_in_context(context, pack["anchors"])
            if len(set(agroups)) < min_groups:
                continue
            candidate_counter[candidate] += 1
            for g in set(agroups):
                candidate_anchor_counter[f"{candidate}\t{g}"] += 1
            h = sha256_text(context)
            if h in seen_hashes:
                continue
            seen_hashes.add(h)
            emit_hit(
                out_fh,
                repo_id=repo_id,
                shard=shard,
                row_no=row_no,
                kind="discovery",
                term=candidate,
                group="female_x_discovery",
                context=context,
                anchor_groups=agroups,
                anchors=amatches,
            )
            stats["discovery_hits"] += 1

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
    seed_terms, seed_group = flatten_seed_groups(pack)
    all_files = corpus_files()
    assigned = [x for i, x in enumerate(all_files) if i % args.worker_count == args.worker_index]
    if args.mode == "pilot":
        assigned = assigned[: args.pilot_files]

    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    hits_path = outdir / f"worker-{args.worker_index:02d}-hits.jsonl.gz"
    summary_path = outdir / f"worker-{args.worker_index:02d}-summary.json"
    candidates_path = outdir / f"worker-{args.worker_index:02d}-candidates.json"

    seen_hashes: set[str] = set()
    candidate_counter: collections.Counter[str] = collections.Counter()
    candidate_anchor_counter: collections.Counter[str] = collections.Counter()
    aggregate = collections.Counter()
    errors: list[dict[str, str]] = []

    with gzip.open(hits_path, "wb", compresslevel=6) as out_fh:
        for repo_id, shard in assigned:
            aggregate["assigned_shards"] += 1
            tmpdir = tempfile.mkdtemp(prefix="female-x-")
            local = None
            try:
                local = hf_hub_download(
                    repo_id=repo_id,
                    filename=shard,
                    repo_type="dataset",
                    local_dir=tmpdir,
                )
                stats = scan_shard(
                    local,
                    repo_id,
                    shard,
                    pack,
                    seed_terms,
                    seed_group,
                    out_fh,
                    seen_hashes,
                    candidate_counter,
                    candidate_anchor_counter,
                )
                aggregate.update(stats)
                aggregate["completed_shards"] += 1
            except Exception as exc:  # keep the worker moving; reducer will surface errors
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
    candidates_path.write_text(
        json.dumps(
            {
                "candidate_counts": candidate_counter.most_common(),
                "candidate_anchor_counts": candidate_anchor_counter.most_common(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
