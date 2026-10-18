#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Iterable

import pyarrow.parquet as pq
import requests
from huggingface_hub import HfApi, hf_hub_url

ROOT = Path(__file__).resolve().parents[1]
WORK = Path(os.environ.get("OSR_PILOT_WORK", "/tmp/osr-search-index-pilot"))
RESULT = ROOT / "control" / "search_index_pilot_result.json"
QW_IMAGE = os.environ.get("OSR_QUICKWIT_IMAGE", "quickwit/quickwit:0.9.0")
INDEX_ID = "osr-pilot"
DOC_LIMIT_PER_SOURCE = int(os.environ.get("OSR_PILOT_ROWS", "3000"))
TEXT_BYTE_LIMIT_PER_SOURCE = int(os.environ.get("OSR_PILOT_TEXT_BYTES", str(96 * 1024 * 1024)))
CHUNK_CHARS = int(os.environ.get("OSR_PILOT_CHUNK_CHARS", "8192"))
CHUNK_OVERLAP = int(os.environ.get("OSR_PILOT_CHUNK_OVERLAP", "128"))

SOURCES = [
    {
        "name": "Literature-zh",
        "repo": "Geralt-Targaryen/Literature-zh",
        "preferred": "literature_zh-00233-of-00233.parquet",
    },
    {
        "name": "ChineseWebText2.0-HighQuality",
        "repo": "Morton-Li/ChineseWebText2.0-HighQuality",
        "preferred": None,
    },
]

_CJK = re.compile(r"[\u3400-\u9fff]")


def run(cmd: list[str], *, input_bytes: bytes | None = None, check: bool = True) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, input=input_bytes, check=check, capture_output=True)


def dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def choose_parquet(repo: str, preferred: str | None) -> str:
    files = [p for p in HfApi().list_repo_files(repo, repo_type="dataset") if p.endswith(".parquet")]
    if not files:
        raise RuntimeError(f"no parquet files found in {repo}")
    if preferred and preferred in files:
        return preferred
    # Deterministic representative shard. The last lexical shard is convenient for completion checks.
    return sorted(files)[-1]


def download(repo: str, filename: str, dest: Path) -> tuple[int, float, str]:
    url = hf_hub_url(repo, filename=filename, repo_type="dataset")
    sha = hashlib.sha256()
    total = 0
    started = time.time()
    with requests.get(url, stream=True, timeout=(30, 180)) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for block in r.iter_content(chunk_size=8 * 1024 * 1024):
                if not block:
                    continue
                f.write(block)
                sha.update(block)
                total += len(block)
    return total, time.time() - started, sha.hexdigest()


def text_column(pf: pq.ParquetFile) -> str:
    fields = list(pf.schema_arrow)
    names = [f.name for f in fields if str(f.type) in {"string", "large_string"}]
    for preferred in ("text", "content", "body"):
        if preferred in names:
            return preferred
    if not names:
        raise RuntimeError(f"no string column in schema: {pf.schema_arrow}")
    return names[0]


def chunks(text: str) -> Iterable[tuple[int, str]]:
    if not text:
        return
    step = max(1, CHUNK_CHARS - CHUNK_OVERLAP)
    ordinal = 0
    for start in range(0, len(text), step):
        piece = text[start : start + CHUNK_CHARS]
        if not piece:
            break
        yield ordinal, piece
        ordinal += 1
        if start + CHUNK_CHARS >= len(text):
            break


def first_cjk_phrase(text: str, n: int = 4) -> str | None:
    chars = _CJK.findall(text)
    if len(chars) < n:
        return None
    # Need contiguous CJK text, not characters collected across punctuation.
    m = re.search(rf"[\u3400-\u9fff]{{{n},}}", text)
    return m.group(0)[:n] if m else None


def materialize_docs(source: dict, parquet_path: Path, out) -> dict:
    pf = pq.ParquetFile(parquet_path)
    colname = text_column(pf)
    rows = 0
    docs = 0
    text_bytes = 0
    sample_phrase = None
    sample_locator = None
    global_row = 0

    for batch in pf.iter_batches(batch_size=128, columns=[colname]):
        col = batch.column(0)
        for i in range(len(col)):
            value = col[i].as_py()
            row_index = global_row
            global_row += 1
            if not isinstance(value, str) or not value:
                continue
            raw_bytes = len(value.encode("utf-8"))
            if rows >= DOC_LIMIT_PER_SOURCE or text_bytes + raw_bytes > TEXT_BYTE_LIMIT_PER_SOURCE:
                return {
                    "text_column": colname,
                    "rows_sampled": rows,
                    "chunks_indexed": docs,
                    "text_bytes": text_bytes,
                    "sample_phrase": sample_phrase,
                    "sample_locator": sample_locator,
                    "parquet_rows": pf.metadata.num_rows,
                    "row_groups": pf.metadata.num_row_groups,
                }
            rows += 1
            text_bytes += raw_bytes
            row_hash = hashlib.sha256(value.encode("utf-8")).hexdigest()
            if sample_phrase is None:
                sample_phrase = first_cjk_phrase(value)
                if sample_phrase:
                    sample_locator = {"row": row_index, "row_hash": row_hash}
            for chunk_id, piece in chunks(value):
                doc = {
                    "corpus": source["name"],
                    "shard": parquet_path.name,
                    "row": row_index,
                    "chunk": chunk_id,
                    "row_hash": row_hash,
                    "text": piece,
                }
                out.write(json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n")
                docs += 1

    return {
        "text_column": colname,
        "rows_sampled": rows,
        "chunks_indexed": docs,
        "text_bytes": text_bytes,
        "sample_phrase": sample_phrase,
        "sample_locator": sample_locator,
        "parquet_rows": pf.metadata.num_rows,
        "row_groups": pf.metadata.num_row_groups,
    }


def wait_quickwit(timeout: int = 60) -> None:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            r = requests.get("http://127.0.0.1:7280/api/v1/version", timeout=3)
            if r.ok:
                return
            last = f"HTTP {r.status_code} {r.text[:200]}"
        except Exception as exc:  # noqa: BLE001
            last = repr(exc)
        time.sleep(1)
    raise RuntimeError(f"quickwit did not become ready: {last}")


def main() -> int:
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    qwdata = WORK / "qwdata"
    qwdata.mkdir()
    ndjson = WORK / "docs.ndjson"
    source_results = []

    total_started = time.time()
    with ndjson.open("w", encoding="utf-8") as out:
        for idx, source in enumerate(SOURCES):
            filename = choose_parquet(source["repo"], source["preferred"])
            local = WORK / f"source-{idx}.parquet"
            nbytes, seconds, sha = download(source["repo"], filename, local)
            materialized = materialize_docs(source, local, out)
            source_results.append(
                {
                    "corpus": source["name"],
                    "repo": source["repo"],
                    "file": filename,
                    "download_bytes": nbytes,
                    "download_seconds": round(seconds, 3),
                    "download_mib_s": round(nbytes / 1048576 / seconds, 3) if seconds else None,
                    "sha256": sha,
                    **materialized,
                }
            )
            local.unlink(missing_ok=True)

    ndjson_bytes = ndjson.stat().st_size
    config = WORK / "index.yaml"
    config.write_text(
        """version: 0.7
index_id: osr-pilot
doc_mapping:
  mode: strict
  field_mappings:
    - name: corpus
      type: text
      tokenizer: raw
      stored: true
    - name: shard
      type: text
      tokenizer: raw
      stored: true
    - name: row
      type: u64
      fast: true
      stored: true
    - name: chunk
      type: u64
      fast: true
      stored: true
    - name: row_hash
      type: text
      tokenizer: raw
      stored: true
    - name: text
      type: text
      tokenizer: chinese_compatible
      record: position
      stored: false
indexing_settings:
  commit_timeout_secs: 10
search_settings:
  default_search_fields: [text]
""",
        encoding="utf-8",
    )

    # Start Quickwit with local index storage. Pilot index is intentionally ephemeral.
    run(["docker", "rm", "-f", "osr-qw-pilot"], check=False)
    run(
        [
            "docker", "run", "-d", "--name", "osr-qw-pilot", "--network=host",
            "-v", f"{qwdata}:/quickwit/qwdata",
            QW_IMAGE, "run",
        ]
    )
    try:
        wait_quickwit()
        r = requests.post(
            "http://127.0.0.1:7280/api/v1/indexes",
            data=config.read_bytes(),
            headers={"content-type": "application/yaml"},
            timeout=30,
        )
        if not r.ok:
            raise RuntimeError(f"create index failed: {r.status_code} {r.text[:2000]}")

        ingest_started = time.time()
        with ndjson.open("rb") as fh:
            proc = subprocess.run(
                [
                    "docker", "run", "--rm", "--network=host", "-i", QW_IMAGE,
                    "index", "ingest", "--index", INDEX_ID, "--force",
                    "--endpoint", "http://127.0.0.1:7280", "--timeout", "30m",
                ],
                stdin=fh,
                capture_output=True,
            )
        ingest_seconds = time.time() - ingest_started
        if proc.returncode:
            raise RuntimeError(
                "quickwit ingest failed\nSTDOUT:\n"
                + proc.stdout.decode("utf-8", "replace")[-6000:]
                + "\nSTDERR:\n"
                + proc.stderr.decode("utf-8", "replace")[-6000:]
            )

        index_bytes = dir_size(qwdata)
        queries = []
        for source in source_results:
            phrase = source.get("sample_phrase")
            if not phrase:
                continue
            started = time.time()
            sr = requests.get(
                f"http://127.0.0.1:7280/api/v1/{INDEX_ID}/search",
                params={"query": f'text:\"{phrase}\"', "max_hits": 5},
                timeout=30,
            )
            elapsed = time.time() - started
            sr.raise_for_status()
            payload = sr.json()
            queries.append(
                {
                    "corpus": source["corpus"],
                    "phrase": phrase,
                    "num_hits": payload.get("num_hits"),
                    "elapsed_ms": round(elapsed * 1000, 3),
                    "hits": payload.get("hits", [])[:3],
                }
            )

        sampled_text_bytes = sum(x["text_bytes"] for x in source_results)
        result = {
            "status": "PASS",
            "engine": "Quickwit/Tantivy pilot",
            "quickwit_image": QW_IMAGE,
            "tokenizer": "chinese_compatible + positions",
            "text_stored": False,
            "locator_fields_stored": ["corpus", "shard", "row", "chunk", "row_hash"],
            "chunk_chars": CHUNK_CHARS,
            "chunk_overlap": CHUNK_OVERLAP,
            "sources": source_results,
            "sampled_text_bytes": sampled_text_bytes,
            "ndjson_bytes": ndjson_bytes,
            "index_data_bytes": index_bytes,
            "index_to_sampled_text_ratio": round(index_bytes / sampled_text_bytes, 4) if sampled_text_bytes else None,
            "ingest_seconds": round(ingest_seconds, 3),
            "ingest_mib_s_on_sampled_text": round(sampled_text_bytes / 1048576 / ingest_seconds, 3) if ingest_seconds else None,
            "queries": queries,
            "total_seconds": round(time.time() - total_started, 3),
            "runner": os.environ.get("RUNNER_NAME"),
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "github_sha": os.environ.get("GITHUB_SHA"),
            "decision_note": "Pilot only. Full 508GB backfill requires durable object/index storage; do not persist the full index in GitHub artifacts.",
        }
        RESULT.parent.mkdir(parents=True, exist_ok=True)
        RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        run(["docker", "rm", "-f", "osr-qw-pilot"], check=False)


if __name__ == "__main__":
    raise SystemExit(main())
