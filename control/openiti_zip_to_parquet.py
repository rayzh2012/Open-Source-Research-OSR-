#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

HEADER_END = "#META#Header#End#"
URI_RE = re.compile(r"^(?P<uri>.+)\.(?P<status>completed|inProgress|mARkdown)$")

SCHEMA = pa.schema([
    ("source_id", pa.string()),
    ("version", pa.string()),
    ("path", pa.string()),
    ("uri", pa.string()),
    ("status", pa.string()),
    ("author_uri", pa.string()),
    ("book_uri", pa.string()),
    ("version_uri", pa.string()),
    ("title", pa.string()),
    ("author", pa.string()),
    ("text", pa.string()),
    ("text_chars", pa.int64()),
    ("text_sha256", pa.string()),
])


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_partition(key: str, count: int) -> int:
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:16], 16) % count


def decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace")


def strip_openiti_header(text: str) -> tuple[str, str]:
    if HEADER_END not in text:
        return "", text.strip()
    head, body = text.split(HEADER_END, 1)
    return head.strip(), body.lstrip("\r\n ")


def parse_uri(name: str) -> tuple[str, str, str, str] | None:
    base = Path(name).name
    m = URI_RE.match(base)
    if not m:
        return None
    version_uri = m.group("uri")
    status = m.group("status")
    parts = version_uri.split(".")
    author_uri = parts[0] if parts else version_uri
    book_uri = ".".join(parts[:2]) if len(parts) >= 2 else author_uri
    return version_uri, status, author_uri, book_uri


def load_metadata(path: Path | None) -> dict[str, dict[str, str]]:
    if path is None or not path.exists():
        return {}
    raw = path.read_text("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw), delimiter="\t")
    out: dict[str, dict[str, str]] = {}
    for row in reader:
        keys = []
        for k, v in row.items():
            if not v:
                continue
            lk = (k or "").lower()
            if any(token in lk for token in ("uri", "id", "version")):
                keys.append(v.strip())
        for key in keys:
            out.setdefault(key, row)
    return out


def pick(row: dict[str, str], *needles: str) -> str:
    for key, value in row.items():
        lk = (key or "").lower()
        if value and any(n in lk for n in needles):
            return value.strip()
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True)
    ap.add_argument("--metadata-tsv", default="")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--partitions", type=int, default=32)
    ap.add_argument("--version", default="2025.1.9")
    args = ap.parse_args()
    if not 1 <= args.partitions <= 256:
        raise SystemExit("partitions must be 1..256")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    meta = load_metadata(Path(args.metadata_tsv) if args.metadata_tsv else None)

    writers: dict[int, pq.ParquetWriter] = {}
    buffers: dict[int, list[dict]] = {i: [] for i in range(args.partitions)}
    docs = [0] * args.partitions
    chars = [0] * args.partitions
    replacement_chars = 0
    skipped = 0
    total_uncompressed = 0

    def flush(idx: int) -> None:
        rows = buffers[idx]
        if not rows:
            return
        path = out / f"openiti-{args.version}-part-{idx:03d}.parquet"
        table = pa.Table.from_pylist(rows, schema=SCHEMA)
        if idx not in writers:
            writers[idx] = pq.ParquetWriter(
                path, SCHEMA, compression="zstd", compression_level=6,
                use_dictionary=True, write_statistics=True,
            )
        writers[idx].write_table(table)
        buffers[idx] = []

    with zipfile.ZipFile(args.zip) as zf:
        for info in zf.infolist():
            if info.is_dir() or info.file_size <= 0:
                continue
            parsed = parse_uri(info.filename)
            if parsed is None:
                skipped += 1
                continue
            version_uri, status, author_uri, book_uri = parsed
            data = zf.read(info)
            total_uncompressed += len(data)
            text0 = decode_text(data)
            replacement_chars += text0.count("\ufffd")
            _, text = strip_openiti_header(text0)
            if not text.strip():
                skipped += 1
                continue
            row_meta = meta.get(version_uri) or meta.get(book_uri) or meta.get(author_uri) or {}
            title = pick(row_meta, "title")
            author = pick(row_meta, "author")
            idx = stable_partition(version_uri, args.partitions)
            encoded = text.encode("utf-8")
            buffers[idx].append({
                "source_id": "openiti",
                "version": args.version,
                "path": info.filename,
                "uri": version_uri,
                "status": status,
                "author_uri": author_uri,
                "book_uri": book_uri,
                "version_uri": version_uri,
                "title": title,
                "author": author,
                "text": text,
                "text_chars": len(text),
                "text_sha256": hashlib.sha256(encoded).hexdigest(),
            })
            docs[idx] += 1
            chars[idx] += len(text)
            if len(buffers[idx]) >= 128:
                flush(idx)

    for idx in range(args.partitions):
        flush(idx)
    for writer in writers.values():
        writer.close()

    parts = []
    for idx in range(args.partitions):
        path = out / f"openiti-{args.version}-part-{idx:03d}.parquet"
        if not path.exists():
            pq.write_table(pa.Table.from_pylist([], schema=SCHEMA), path, compression="zstd")
        parts.append({
            "partition": idx,
            "file": path.name,
            "documents": docs[idx],
            "text_chars": chars[idx],
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })

    manifest = {
        "format": "osr-openiti-normalized/v1",
        "source_id": "openiti",
        "version": args.version,
        "partitions": args.partitions,
        "documents": sum(docs),
        "text_chars": sum(chars),
        "zip_uncompressed_bytes_scanned": total_uncompressed,
        "replacement_chars": replacement_chars,
        "skipped_non_text_entries": skipped,
        "raw_text_persisted_in_feature_ready_parquet": True,
        "partitioner": "sha256(version_uri) stable bucket",
        "parts": parts,
    }
    payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    manifest["inventory_sha256"] = hashlib.sha256(payload).hexdigest()
    (out / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({k: manifest[k] for k in ("documents", "text_chars", "partitions", "inventory_sha256")}, ensure_ascii=False))
    return 0 if manifest["documents"] > 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
