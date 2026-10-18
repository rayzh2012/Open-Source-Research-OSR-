#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path

import pyarrow.parquet as pq
import tantivy
from huggingface_hub import HfApi

import osr_search_index_pilot as base

ROOT = Path(__file__).resolve().parents[1]
WORK = Path(os.environ.get("OSR_TANTIVY_WORK", "/tmp/osr-tantivy-qgram-pilot"))
RESULT = ROOT / "control" / "tantivy_qgram_pilot_result.json"
INDEX_DIR = WORK / "index"
Q = 3


def qgrams(s: str) -> list[str]:
    if len(s) < Q:
        return [s] if s else []
    return [s[i : i + Q] for i in range(len(s) - Q + 1)]


def choose_parquet(repo: str, preferred: str | None) -> str:
    files = [p for p in HfApi().list_repo_files(repo, repo_type="dataset") if p.endswith(".parquet")]
    if not files:
        raise RuntimeError(f"no parquet files found in {repo}")
    if preferred and preferred in files:
        return preferred
    return sorted(files)[-1]


def build_schema():
    b = tantivy.SchemaBuilder()
    b.add_text_field("corpus", stored=True, tokenizer_name="raw", index_option="basic")
    b.add_text_field("shard", stored=True, tokenizer_name="raw", index_option="basic")
    b.add_unsigned_field("row", stored=True, indexed=False, fast=False)
    b.add_unsigned_field("chunk", stored=True, indexed=False, fast=False)
    b.add_text_field("row_hash", stored=True, tokenizer_name="raw", index_option="basic")
    b.add_text_field("text", stored=False, tokenizer_name="ngram3", index_option="basic")
    return b.build()


def get_doc_value(doc, name: str):
    value = doc[name]
    if isinstance(value, list) and len(value) == 1:
        return value[0]
    return value


def main() -> int:
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    INDEX_DIR.mkdir()

    schema = build_schema()
    index = tantivy.Index(schema, path=str(INDEX_DIR))
    analyzer = tantivy.TextAnalyzerBuilder(tantivy.Tokenizer.ngram(3, 3, False)).build()
    index.register_tokenizer("ngram3", analyzer)

    writer = index.writer(heap_size=512_000_000, num_threads=4)
    source_results = []
    sampled_text_bytes = 0
    chunks_indexed = 0
    started_all = time.time()

    for src_idx, source in enumerate(base.SOURCES):
        filename = choose_parquet(source["repo"], source["preferred"])
        local = WORK / f"source-{src_idx}.parquet"
        nbytes, dl_seconds, sha = base.download(source["repo"], filename, local)
        pf = pq.ParquetFile(local)
        colname = base.text_column(pf)
        rows = 0
        text_bytes = 0
        source_chunks = 0
        sample_phrase = None
        sample_locator = None
        global_row = 0
        stop = False

        for batch in pf.iter_batches(batch_size=128, columns=[colname]):
            col = batch.column(0)
            for i in range(len(col)):
                value = col[i].as_py()
                row_index = global_row
                global_row += 1
                if not isinstance(value, str) or not value:
                    continue
                raw_bytes = len(value.encode("utf-8"))
                if rows >= base.DOC_LIMIT_PER_SOURCE or text_bytes + raw_bytes > base.TEXT_BYTE_LIMIT_PER_SOURCE:
                    stop = True
                    break
                rows += 1
                text_bytes += raw_bytes
                row_hash = hashlib.sha256(value.encode("utf-8")).hexdigest()
                if sample_phrase is None:
                    sample_phrase = base.first_cjk_phrase(value, n=6)
                    if sample_phrase:
                        sample_locator = {"row": row_index, "row_hash": row_hash}
                for chunk_id, piece in base.chunks(value):
                    writer.add_document(
                        tantivy.Document(
                            corpus=[source["name"]],
                            shard=[filename],
                            row=row_index,
                            chunk=chunk_id,
                            row_hash=[row_hash],
                            text=[piece],
                        )
                    )
                    source_chunks += 1
                    chunks_indexed += 1
            if stop:
                break

        sampled_text_bytes += text_bytes
        source_results.append(
            {
                "corpus": source["name"],
                "repo": source["repo"],
                "file": filename,
                "download_bytes": nbytes,
                "download_seconds": round(dl_seconds, 3),
                "download_mib_s": round(nbytes / 1048576 / dl_seconds, 3) if dl_seconds else None,
                "sha256": sha,
                "text_column": colname,
                "rows_sampled": rows,
                "chunks_indexed": source_chunks,
                "text_bytes": text_bytes,
                "sample_phrase": sample_phrase,
                "sample_locator": sample_locator,
                "parquet_rows": pf.metadata.num_rows,
                "row_groups": pf.metadata.num_row_groups,
            }
        )
        local.unlink(missing_ok=True)

    commit_started = time.time()
    writer.commit()
    writer.wait_merging_threads()
    ingest_seconds = time.time() - started_all
    commit_seconds = time.time() - commit_started
    index.reload()
    searcher = index.searcher()

    index_bytes = base.dir_size(INDEX_DIR)
    queries = []
    for source in source_results:
        phrase = source.get("sample_phrase")
        if not phrase or len(phrase) < Q:
            continue
        grams = qgrams(phrase)
        # Each explicit 3-gram term uses the same ngram3 analyzer and produces one token.
        query_text = " AND ".join(f'text:\"{g}\"' for g in grams)
        q0 = time.time()
        query = index.parse_query(query_text, ["text"])
        result = searcher.search(query, 20)
        elapsed = time.time() - q0
        hits = []
        for score, addr in result.hits:
            doc = searcher.doc(addr)
            hits.append(
                {
                    "score": score,
                    "corpus": get_doc_value(doc, "corpus"),
                    "shard": get_doc_value(doc, "shard"),
                    "row": get_doc_value(doc, "row"),
                    "chunk": get_doc_value(doc, "chunk"),
                    "row_hash": get_doc_value(doc, "row_hash"),
                }
            )
        expected = source.get("sample_locator") or {}
        expected_found = any(
            h.get("corpus") == source["corpus"]
            and h.get("row") == expected.get("row")
            and h.get("row_hash") == expected.get("row_hash")
            for h in hits
        )
        queries.append(
            {
                "corpus": source["corpus"],
                "phrase": phrase,
                "qgrams": grams,
                "candidate_count": result.count,
                "returned": len(hits),
                "expected_locator_found": expected_found,
                "elapsed_ms": round(elapsed * 1000, 3),
                "hits": hits[:5],
            }
        )

    result = {
        "status": "PASS",
        "engine": "Tantivy q-gram locator pilot",
        "tantivy_version": getattr(tantivy, "__version__", None),
        "tokenizer": "NgramTokenizer(3,3,false)",
        "index_record_option": "basic (DocID only; no freq; no positions)",
        "text_stored": False,
        "locator_fields_stored": ["corpus", "shard", "row", "chunk", "row_hash"],
        "chunk_chars": base.CHUNK_CHARS,
        "chunk_overlap": base.CHUNK_OVERLAP,
        "sources": source_results,
        "sampled_text_bytes": sampled_text_bytes,
        "chunks_indexed": chunks_indexed,
        "index_data_bytes": index_bytes,
        "index_to_sampled_text_ratio": round(index_bytes / sampled_text_bytes, 4) if sampled_text_bytes else None,
        "total_index_seconds": round(ingest_seconds, 3),
        "final_commit_seconds": round(commit_seconds, 3),
        "index_mib_s_on_sampled_text": round(sampled_text_bytes / 1048576 / ingest_seconds, 3) if ingest_seconds else None,
        "queries": queries,
        "total_seconds": round(time.time() - started_all, 3),
        "runner": os.environ.get("RUNNER_NAME"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "github_sha": os.environ.get("GITHUB_SHA"),
        "production_contract": "q-gram candidates -> locator -> exact substring recheck against source row; no phrase positions stored in index",
    }
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
