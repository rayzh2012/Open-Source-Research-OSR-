#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path

import pyarrow.parquet as pq
import tantivy
from huggingface_hub import HfApi

import osr_search_index_pilot as base

ROOT = Path(__file__).resolve().parents[1]
WORK = Path(os.environ.get("OSR_ROUTER_WORK", "/tmp/osr-shard-router-pilot"))
RESULT = ROOT / "control" / "shard_router_pilot_result.json"
INDEX_DIR = WORK / "index"
Q = 2


def grams(s: str) -> list[str]:
    return [s[i:i+Q] for i in range(max(0, len(s)-Q+1))]


def choose_parquet(repo: str, preferred: str | None) -> str:
    files = [p for p in HfApi().list_repo_files(repo, repo_type="dataset") if p.endswith(".parquet")]
    if preferred and preferred in files:
        return preferred
    return sorted(files)[-1]


def main() -> int:
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    INDEX_DIR.mkdir()

    b = tantivy.SchemaBuilder()
    b.add_text_field("corpus", stored=True, tokenizer_name="raw", index_option="basic")
    b.add_text_field("shard", stored=True, tokenizer_name="raw", index_option="basic")
    b.add_text_field("text", stored=False, tokenizer_name="ngram2", index_option="basic")
    schema = b.build()
    index = tantivy.Index(schema, path=str(INDEX_DIR))
    index.register_tokenizer(
        "ngram2",
        tantivy.TextAnalyzerBuilder(tantivy.Tokenizer.ngram(2, 2, False)).build(),
    )
    writer = index.writer(heap_size=1_000_000_000, num_threads=4)

    sources = []
    raw_parquet_bytes = 0
    source_text_bytes = 0
    started = time.time()
    for i, src in enumerate(base.SOURCES):
        filename = choose_parquet(src["repo"], src["preferred"])
        local = WORK / f"source-{i}.parquet"
        nbytes, dl_s, sha = base.download(src["repo"], filename, local)
        raw_parquet_bytes += nbytes
        pf = pq.ParquetFile(local)
        colname = base.text_column(pf)
        pieces: list[str] = []
        text_bytes = 0
        sample_phrase = None
        for batch in pf.iter_batches(batch_size=256, columns=[colname]):
            col = batch.column(0)
            for j in range(len(col)):
                v = col[j].as_py()
                if not isinstance(v, str) or not v:
                    continue
                pieces.append(v)
                text_bytes += len(v.encode("utf-8"))
                if sample_phrase is None:
                    sample_phrase = base.first_cjk_phrase(v, n=8)
        joined = "\n".join(pieces)
        source_text_bytes += text_bytes
        writer.add_document(tantivy.Document(corpus=[src["name"]], shard=[filename], text=[joined]))
        sources.append({
            "corpus": src["name"], "repo": src["repo"], "file": filename,
            "parquet_bytes": nbytes, "download_seconds": round(dl_s,3),
            "download_mib_s": round(nbytes/1048576/dl_s,3) if dl_s else None,
            "sha256": sha, "text_column": colname, "rows": pf.metadata.num_rows,
            "text_bytes": text_bytes, "sample_phrase": sample_phrase,
        })
        del joined, pieces
        local.unlink(missing_ok=True)

    writer.commit()
    writer.wait_merging_threads()
    index_seconds = time.time() - started
    index.reload()
    searcher = index.searcher()
    queries = []
    for src in sources:
        phrase = src["sample_phrase"]
        gs = grams(phrase)
        query_text = " AND ".join(f'text:\"{g}\"' for g in gs)
        q0 = time.time()
        result = searcher.search(index.parse_query(query_text, ["text"]), 20)
        hits = []
        for score, addr in result.hits:
            doc = searcher.doc(addr)
            hits.append({"score": score, "corpus": doc["corpus"][0], "shard": doc["shard"][0]})
        queries.append({
            "corpus": src["corpus"], "phrase": phrase, "bigrams": gs,
            "candidate_shards": result.count, "elapsed_ms": round((time.time()-q0)*1000,3),
            "hits": hits,
        })

    index_bytes = base.dir_size(INDEX_DIR)
    result = {
        "status": "PASS",
        "engine": "Tantivy shard router pilot",
        "tokenizer": "NgramTokenizer(2,2,false)",
        "index_record_option": "basic",
        "document_granularity": "one Parquet shard = one index document",
        "text_stored": False,
        "sources": sources,
        "raw_parquet_bytes": raw_parquet_bytes,
        "source_text_bytes": source_text_bytes,
        "index_data_bytes": index_bytes,
        "index_to_raw_parquet_ratio": round(index_bytes/raw_parquet_bytes,4),
        "index_to_source_text_ratio": round(index_bytes/source_text_bytes,4),
        "index_seconds_including_download": round(index_seconds,3),
        "queries": queries,
        "runner": os.environ.get("RUNNER_NAME"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "github_sha": os.environ.get("GITHUB_SHA"),
        "production_contract": "router index returns candidate shard IDs; exact search then scans only candidate Parquet shards and emits row locators",
    }
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
