#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import ahocorasick
import pyarrow as pa
import pyarrow.parquet as pq
import requests
from huggingface_hub import HfApi, hf_hub_url

SOURCES = [
    ("Literature-zh", "Geralt-Targaryen/Literature-zh"),
    ("ChineseWebText2.0-HighQuality", "Morton-Li/ChineseWebText2.0-HighQuality"),
]

ROW_SCHEMA = pa.schema([
    ("corpus", pa.string()),
    ("repo", pa.string()),
    ("shard", pa.string()),
    ("row", pa.int64()),
    ("row_sha256", pa.string()),
    ("char_len", pa.int64()),
    ("utf8_bytes", pa.int64()),
    ("cjk_chars", pa.int64()),
    ("ascii_chars", pa.int64()),
    ("digit_chars", pa.int64()),
    ("feature_ids", pa.list_(pa.string())),
    ("feature_counts", pa.list_(pa.int32())),
    ("first_positions", pa.list_(pa.int64())),
    ("regex_feature_ids", pa.list_(pa.string())),
    ("regex_counts", pa.list_(pa.int32())),
    ("year_min", pa.int32()),
    ("year_max", pa.int32()),
    ("explicit_year_count", pa.int32()),
])

SHARD_SCHEMA = pa.schema([
    ("corpus", pa.string()),
    ("repo", pa.string()),
    ("shard", pa.string()),
    ("shard_sha256", pa.string()),
    ("download_bytes", pa.int64()),
    ("rows", pa.int64()),
    ("rows_nonempty", pa.int64()),
    ("signal_rows", pa.int64()),
    ("chars", pa.int64()),
    ("newline_count", pa.int64()),
    ("sentence_terminal_count", pa.int64()),
    ("within_shard_duplicate_rows", pa.int64()),
    ("explicit_year_mentions", pa.int64()),
    ("year_min", pa.int32()),
    ("year_max", pa.int32()),
    ("scan_seconds", pa.float64()),
])

PAIR_SCHEMA = pa.schema([
    ("corpus", pa.string()),
    ("repo", pa.string()),
    ("shard", pa.string()),
    ("feature_a", pa.string()),
    ("feature_b", pa.string()),
    ("rows_cooccurring", pa.int64()),
])

FEATURE_TOTAL_SCHEMA = pa.schema([
    ("corpus", pa.string()),
    ("repo", pa.string()),
    ("shard", pa.string()),
    ("feature_id", pa.string()),
    ("family", pa.string()),
    ("occurrences", pa.int64()),
    ("rows_with_feature", pa.int64()),
])

CJK_RE = re.compile(r"[\u3400-\u9fff]")
ASCII_RE = re.compile(r"[\x00-\x7f]")
DIGIT_RE = re.compile(r"[0-9]")
YEAR_VALUE_RE = re.compile(r"(?:公元前|西元前)?([0-9]{1,4})年")


def list_parquets(repo: str) -> list[str]:
    return sorted(p for p in HfApi().list_repo_files(repo, repo_type="dataset") if p.endswith(".parquet"))


def download(repo: str, filename: str, dest: Path) -> tuple[int, float, str]:
    url = hf_hub_url(repo, filename=filename, repo_type="dataset")
    sha = hashlib.sha256()
    total = 0
    started = time.time()
    with requests.get(url, stream=True, timeout=(30, 240)) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for block in r.iter_content(8 * 1024 * 1024):
                if not block:
                    continue
                f.write(block)
                sha.update(block)
                total += len(block)
    return total, time.time() - started, sha.hexdigest()


def text_column(pf: pq.ParquetFile) -> str:
    names = [f.name for f in pf.schema_arrow if str(f.type) in {"string", "large_string"}]
    for name in ("text", "content", "body"):
        if name in names:
            return name
    if not names:
        raise RuntimeError(f"No text-like string column: {pf.schema_arrow}")
    return names[0]


def safe_name(path: str) -> str:
    return re.sub(r"[^0-9A-Za-z._-]+", "__", path).strip("_")


def build_feature_machine(schema: dict):
    term_to_features: dict[str, list[str]] = defaultdict(list)
    feature_family: dict[str, str] = {}
    for feat in schema["features"]:
        fid = feat["id"]
        feature_family[fid] = feat["family"]
        for term in feat.get("terms", []):
            if fid not in term_to_features[term]:
                term_to_features[term].append(fid)

    machine = ahocorasick.Automaton()
    for term, fids in term_to_features.items():
        machine.add_word(term, (term, tuple(fids)))
    machine.make_automaton()

    regexes = []
    for feat in schema.get("regex_features", []):
        feature_family[feat["id"]] = feat["family"]
        regexes.append((feat["id"], re.compile(feat["pattern"])))
    return machine, regexes, feature_family


def script_counts(text: str) -> tuple[int, int, int]:
    # Only called for sparse signal rows; never for the whole corpus.
    return (
        len(CJK_RE.findall(text)),
        len(ASCII_RE.findall(text)),
        len(DIGIT_RE.findall(text)),
    )


def explicit_year_values(text: str) -> list[int]:
    out = []
    for m in YEAR_VALUE_RE.finditer(text):
        value = int(m.group(1))
        if m.group(0).startswith(("公元前", "西元前")):
            value = -value
        out.append(value)
    return out


def write_table(rows: list[dict], schema: pa.Schema, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows, schema=schema) if rows else pa.Table.from_pylist([], schema=schema)
    pq.write_table(table, path, compression="zstd", compression_level=9, use_dictionary=True)


def scan_shard(
    *,
    corpus: str,
    repo: str,
    filename: str,
    local: Path,
    shard_sha256: str,
    download_bytes: int,
    machine,
    regexes,
    feature_family: dict[str, str],
    out_dir: Path,
) -> dict:
    started = time.time()
    pf = pq.ParquetFile(local)
    colname = text_column(pf)

    rows_nonempty = 0
    signal_rows = 0
    chars = 0
    newlines = 0
    sentence_terminals = 0
    duplicate_rows = 0
    seen_row_hashes: set[bytes] = set()
    explicit_year_mentions = 0
    shard_year_min = None
    shard_year_max = None

    row_records: list[dict] = []
    pair_counts: Counter[tuple[str, str]] = Counter()
    feature_occurrences: Counter[str] = Counter()
    feature_rows: Counter[str] = Counter()

    global_row = 0
    for batch in pf.iter_batches(batch_size=256, columns=[colname]):
        col = batch.column(0)
        for i in range(len(col)):
            text = col[i].as_py()
            row_index = global_row
            global_row += 1
            if not isinstance(text, str) or not text:
                continue

            rows_nonempty += 1
            chars += len(text)
            newlines += text.count("\n")
            sentence_terminals += text.count("。") + text.count("！") + text.count("？") + text.count("!") + text.count("?")

            # 64-bit stable duplicate key. This is shard-local QA only; row_sha256 below remains the evidence identity.
            dup_key = hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest()
            if dup_key in seen_row_hashes:
                duplicate_rows += 1
            else:
                seen_row_hashes.add(dup_key)

            counts: Counter[str] = Counter()
            first_pos: dict[str, int] = {}
            for end, payload in machine.iter(text):
                term, fids = payload
                start = end - len(term) + 1
                for fid in fids:
                    counts[fid] += 1
                    if fid not in first_pos or start < first_pos[fid]:
                        first_pos[fid] = start

            regex_counts: Counter[str] = Counter()
            for fid, rx in regexes:
                n = sum(1 for _ in rx.finditer(text))
                if n:
                    regex_counts[fid] = n

            years = explicit_year_values(text) if regex_counts.get("TEMPORAL_EXPLICIT_YEAR") else []
            if years:
                explicit_year_mentions += len(years)
                ymin, ymax = min(years), max(years)
                shard_year_min = ymin if shard_year_min is None else min(shard_year_min, ymin)
                shard_year_max = ymax if shard_year_max is None else max(shard_year_max, ymax)
            else:
                ymin = ymax = None

            if not counts and not regex_counts:
                continue

            signal_rows += 1
            encoded = text.encode("utf-8")
            cjk, ascii_count, digits = script_counts(text)
            feature_ids = sorted(counts)
            for fid in feature_ids:
                feature_occurrences[fid] += counts[fid]
                feature_rows[fid] += 1
            for a, b in combinations(feature_ids, 2):
                pair_counts[(a, b)] += 1

            row_records.append({
                "corpus": corpus,
                "repo": repo,
                "shard": filename,
                "row": row_index,
                "row_sha256": hashlib.sha256(encoded).hexdigest(),
                "char_len": len(text),
                "utf8_bytes": len(encoded),
                "cjk_chars": cjk,
                "ascii_chars": ascii_count,
                "digit_chars": digits,
                "feature_ids": feature_ids,
                "feature_counts": [int(counts[f]) for f in feature_ids],
                "first_positions": [int(first_pos[f]) for f in feature_ids],
                "regex_feature_ids": sorted(regex_counts),
                "regex_counts": [int(regex_counts[f]) for f in sorted(regex_counts)],
                "year_min": ymin,
                "year_max": ymax,
                "explicit_year_count": len(years),
            })

    shard_key = safe_name(filename)
    row_path = out_dir / "rows" / f"{corpus}__{shard_key}.parquet"
    write_table(row_records, ROW_SCHEMA, row_path)

    pair_records = [
        {
            "corpus": corpus,
            "repo": repo,
            "shard": filename,
            "feature_a": a,
            "feature_b": b,
            "rows_cooccurring": int(n),
        }
        for (a, b), n in sorted(pair_counts.items())
    ]

    feature_records = [
        {
            "corpus": corpus,
            "repo": repo,
            "shard": filename,
            "feature_id": fid,
            "family": feature_family.get(fid, "unknown"),
            "occurrences": int(feature_occurrences[fid]),
            "rows_with_feature": int(feature_rows[fid]),
        }
        for fid in sorted(feature_occurrences)
    ]

    scan_seconds = time.time() - started
    shard_record = {
        "corpus": corpus,
        "repo": repo,
        "shard": filename,
        "shard_sha256": shard_sha256,
        "download_bytes": download_bytes,
        "rows": pf.metadata.num_rows,
        "rows_nonempty": rows_nonempty,
        "signal_rows": signal_rows,
        "chars": chars,
        "newline_count": newlines,
        "sentence_terminal_count": sentence_terminals,
        "within_shard_duplicate_rows": duplicate_rows,
        "explicit_year_mentions": explicit_year_mentions,
        "year_min": shard_year_min,
        "year_max": shard_year_max,
        "scan_seconds": round(scan_seconds, 6),
    }
    return {
        "shard": shard_record,
        "pairs": pair_records,
        "feature_totals": feature_records,
        "row_feature_file": str(row_path.relative_to(out_dir)),
        "row_feature_rows": len(row_records),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker-index", type=int, required=True)
    ap.add_argument("--worker-count", type=int, required=True)
    ap.add_argument("--limit-per-worker", type=int, default=0)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--feature-schema", default="control/feature_schema_v1.json")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    schema_path = Path(args.feature_schema)
    schema_bytes = schema_path.read_bytes()
    feature_schema = json.loads(schema_bytes.decode("utf-8"))
    schema_sha256 = hashlib.sha256(schema_bytes).hexdigest()
    machine, regexes, feature_family = build_feature_machine(feature_schema)

    inventory = []
    for corpus, repo in SOURCES:
        for filename in list_parquets(repo):
            inventory.append((corpus, repo, filename))
    inventory.sort(key=lambda x: (x[0], x[2]))
    assigned = [x for i, x in enumerate(inventory) if i % args.worker_count == args.worker_index]
    if args.limit_per_worker > 0:
        assigned = assigned[: args.limit_per_worker]

    all_shards: list[dict] = []
    all_pairs: list[dict] = []
    all_feature_totals: list[dict] = []
    row_files = []
    bytes_downloaded = 0
    started_all = time.time()

    for n, (corpus, repo, filename) in enumerate(assigned, 1):
        local = Path("/tmp") / f"osr-feature-{args.worker_index}-{n}.parquet"
        size, dl_seconds, shard_sha = download(repo, filename, local)
        rec = scan_shard(
            corpus=corpus,
            repo=repo,
            filename=filename,
            local=local,
            shard_sha256=shard_sha,
            download_bytes=size,
            machine=machine,
            regexes=regexes,
            feature_family=feature_family,
            out_dir=out_dir,
        )
        local.unlink(missing_ok=True)
        bytes_downloaded += size
        all_shards.append(rec["shard"])
        all_pairs.extend(rec["pairs"])
        all_feature_totals.extend(rec["feature_totals"])
        row_files.append({"shard": filename, "file": rec["row_feature_file"], "rows": rec["row_feature_rows"]})
        print(json.dumps({
            "progress": f"{n}/{len(assigned)}",
            "corpus": corpus,
            "shard": filename,
            "MiB": round(size / 1048576, 2),
            "signal_rows": rec["shard"]["signal_rows"],
            "scan_seconds": rec["shard"]["scan_seconds"],
        }, ensure_ascii=False), flush=True)

    write_table(all_shards, SHARD_SCHEMA, out_dir / "shard_features.parquet")
    write_table(all_pairs, PAIR_SCHEMA, out_dir / "cooccurrence.parquet")
    write_table(all_feature_totals, FEATURE_TOTAL_SCHEMA, out_dir / "feature_totals.parquet")

    manifest = {
        "format": "osr-feature-store-worker/v1",
        "feature_schema_version": feature_schema.get("version"),
        "feature_schema_sha256": schema_sha256,
        "worker_index": args.worker_index,
        "worker_count": args.worker_count,
        "assigned_shards": len(assigned),
        "bytes_downloaded": bytes_downloaded,
        "signal_rows": sum(x["signal_rows"] for x in all_shards),
        "rows_scanned": sum(x["rows_nonempty"] for x in all_shards),
        "elapsed_seconds": round(time.time() - started_all, 3),
        "row_feature_files": row_files,
        "tables": {
            "shard_features": "shard_features.parquet",
            "feature_totals": "feature_totals.parquet",
            "cooccurrence": "cooccurrence.parquet",
            "row_features": "rows/*.parquet"
        },
        "raw_text_persisted": False,
        "runner": os.environ.get("RUNNER_NAME"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "github_sha": os.environ.get("GITHUB_SHA"),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
